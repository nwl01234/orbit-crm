from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from ..deps import get_current_user, get_db
from ..models import Company, Contact, User
from ..schemas import CompanyCreate, CompanyDetail, CompanyOut, CompanyUpdate
from ..services.crm import (
    company_deals,
    enrich_companies,
    enrich_company,
    enrich_contacts,
    require_user,
)
from ..services.logging_service import log_action

router = APIRouter(prefix="/api/companies", tags=["companies"])

SORTS = {
    "name": Company.name,
    "created_at": Company.created_at,
    "updated_at": Company.updated_at,
    "industry": Company.industry,
}


def _get_company_or_404(db: Session, company_id: int, *, load: bool = False) -> Company:
    stmt = select(Company).where(Company.id == company_id)
    if load:
        stmt = stmt.options(joinedload(Company.contacts), joinedload(Company.owner))
    company = db.scalar(stmt)
    if not company:
        raise HTTPException(status_code=404, detail="Компания не найдена")
    return company


def _ensure_unique_name(db: Session, name: str, company_id: Optional[int] = None) -> None:
    existing = db.scalar(select(Company).where(func.lower(Company.name) == name.strip().lower()))
    if existing and existing.id != company_id:
        raise HTTPException(status_code=400, detail="Компания с таким названием уже существует")


@router.get("", response_model=list[CompanyOut])
def list_companies(
    response: Response,
    q: Optional[str] = None,
    industry: Optional[str] = None,
    owner_id: Optional[int] = None,
    sort: str = "updated_at",
    order: str = "desc",
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    limit = max(1, min(limit, 200))
    stmt = select(Company)
    count_stmt = select(func.count(Company.id))

    if q and q.strip():
        like = "%" + q.strip() + "%"
        condition = or_(
            Company.name.ilike(like),
            Company.domain.ilike(like),
            Company.industry.ilike(like),
            Company.email.ilike(like),
        )
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    if industry:
        stmt = stmt.where(Company.industry == industry)
        count_stmt = count_stmt.where(Company.industry == industry)
    if owner_id:
        stmt = stmt.where(Company.owner_id == owner_id)
        count_stmt = count_stmt.where(Company.owner_id == owner_id)

    column = SORTS.get(sort, Company.updated_at)
    stmt = stmt.order_by(column.asc() if order == "asc" else column.desc())
    total = db.scalar(count_stmt) or 0
    response.headers["X-Total-Count"] = str(total)

    companies = list(db.scalars(stmt.offset(max(0, offset)).limit(limit)).all())
    return enrich_companies(db, companies)


@router.post("", response_model=CompanyOut, status_code=201)
def create_company(
    payload: CompanyCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    data = payload.model_dump()
    data["name"] = data["name"].strip()
    _ensure_unique_name(db, data["name"])
    require_user(db, data.get("owner_id"))

    if not data.get("owner_id"):
        data["owner_id"] = user.id
    if not data.get("domain") and data.get("website"):
        data["domain"] = data["website"].removeprefix("https://").removeprefix("http://").strip("/")

    company = Company(**data)
    db.add(company)
    db.flush()
    log_action(db, user.id, "company_create", "company", company.id, company.name)
    db.commit()
    db.refresh(company)
    return enrich_company(db, company)


@router.get("/{company_id}", response_model=CompanyDetail)
def get_company(
    company_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    company = _get_company_or_404(db, company_id, load=True)
    data = enrich_company(db, company).model_dump()
    contacts = enrich_contacts(db, list(company.contacts))
    deals = company_deals(db, company.id)
    return CompanyDetail(**data, contacts=contacts, deals=deals)


@router.patch("/{company_id}", response_model=CompanyOut)
def update_company(
    company_id: int,
    payload: CompanyUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    company = _get_company_or_404(db, company_id)
    data = payload.model_dump(exclude_unset=True)

    if "name" in data:
        data["name"] = (data["name"] or "").strip()
        if not data["name"]:
            raise HTTPException(status_code=400, detail="Название компании обязательно")
        _ensure_unique_name(db, data["name"], company_id)
    if "owner_id" in data:
        require_user(db, data["owner_id"])

    changed = ", ".join(data.keys())
    for field, value in data.items():
        setattr(company, field, value)

    log_action(db, user.id, "company_update", "company", company.id, changed)
    db.commit()
    db.refresh(company)
    return enrich_company(db, company)


@router.delete("/{company_id}", status_code=204)
def delete_company(
    company_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    company = _get_company_or_404(db, company_id, load=True)
    name = company.name
    for contact in list(company.contacts):
        contact.company_id = None
    db.delete(company)
    log_action(db, user.id, "company_delete", "company", company_id, name)
    db.commit()
    return None


@router.get("/{company_id}/contacts")
def company_contacts(
    company_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    _get_company_or_404(db, company_id)
    contacts = list(
        db.scalars(select(Contact).where(Contact.company_id == company_id).order_by(Contact.full_name)).all()
    )
    return enrich_contacts(db, contacts)
