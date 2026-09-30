from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from ..deps import get_current_user, get_db
from ..models import Company, Contact, User
from ..schemas import ContactCreate, ContactDetail, ContactOut, ContactUpdate
from ..services.crm import (
    contact_deals,
    enrich_contact,
    enrich_contacts,
    require_user,
)
from ..services.logging_service import log_action

router = APIRouter(prefix="/api/contacts", tags=["contacts"])

SORTS = {
    "name": Contact.full_name,
    "created_at": Contact.created_at,
    "updated_at": Contact.updated_at,
    "email": Contact.email,
}


def _get_contact_or_404(db: Session, contact_id: int, *, load: bool = False) -> Contact:
    stmt = select(Contact).where(Contact.id == contact_id)
    if load:
        stmt = stmt.options(joinedload(Contact.company), joinedload(Contact.owner))
    contact = db.scalar(stmt)
    if not contact:
        raise HTTPException(status_code=404, detail="Контакт не найден")
    return contact


def _ensure_unique_email(db: Session, email: str, contact_id: Optional[int] = None) -> None:
    email = (email or "").strip().lower()
    if not email:
        return
    existing = db.scalar(select(Contact).where(func.lower(Contact.email) == email))
    if existing and existing.id != contact_id:
        raise HTTPException(status_code=400, detail="Контакт с таким email уже существует")


def _validate_company(db: Session, company_id: Optional[int]) -> None:
    if company_id and not db.get(Company, company_id):
        raise HTTPException(status_code=400, detail="Компания не найдена")


@router.get("", response_model=list[ContactOut])
def list_contacts(
    response: Response,
    q: Optional[str] = None,
    company_id: Optional[int] = None,
    owner_id: Optional[int] = None,
    sort: str = "updated_at",
    order: str = "desc",
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    limit = max(1, min(limit, 200))
    stmt = select(Contact)
    count_stmt = select(func.count(Contact.id))

    if q and q.strip():
        like = "%" + q.strip() + "%"
        condition = or_(
            Contact.full_name.ilike(like),
            Contact.email.ilike(like),
            Contact.phone.ilike(like),
            Contact.position.ilike(like),
        )
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    if company_id:
        stmt = stmt.where(Contact.company_id == company_id)
        count_stmt = count_stmt.where(Contact.company_id == company_id)
    if owner_id:
        stmt = stmt.where(Contact.owner_id == owner_id)
        count_stmt = count_stmt.where(Contact.owner_id == owner_id)

    column = SORTS.get(sort, Contact.updated_at)
    stmt = stmt.order_by(column.asc() if order == "asc" else column.desc())
    total = db.scalar(count_stmt) or 0
    response.headers["X-Total-Count"] = str(total)

    contacts = list(db.scalars(stmt.offset(max(0, offset)).limit(limit)).all())
    return enrich_contacts(db, contacts)


@router.post("", response_model=ContactOut, status_code=201)
def create_contact(
    payload: ContactCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    data = payload.model_dump()
    data["full_name"] = data["full_name"].strip()
    _ensure_unique_email(db, data.get("email", ""))
    _validate_company(db, data.get("company_id"))
    require_user(db, data.get("owner_id"))
    if not data.get("owner_id"):
        data["owner_id"] = user.id

    contact = Contact(**data)
    db.add(contact)
    db.flush()
    log_action(db, user.id, "contact_create", "contact", contact.id, contact.full_name)
    db.commit()
    db.refresh(contact)
    return enrich_contact(db, contact)


@router.get("/{contact_id}", response_model=ContactDetail)
def get_contact(
    contact_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    contact = _get_contact_or_404(db, contact_id, load=True)
    data = enrich_contact(db, contact).model_dump()
    return ContactDetail(**data, deals=contact_deals(db, contact.id))


@router.patch("/{contact_id}", response_model=ContactOut)
def update_contact(
    contact_id: int,
    payload: ContactUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    contact = _get_contact_or_404(db, contact_id)
    data = payload.model_dump(exclude_unset=True)

    if "full_name" in data:
        data["full_name"] = (data["full_name"] or "").strip()
        if not data["full_name"]:
            raise HTTPException(status_code=400, detail="Имя контакта обязательно")
    if "email" in data:
        _ensure_unique_email(db, data["email"] or "", contact_id)
    if "company_id" in data:
        _validate_company(db, data["company_id"])
    if "owner_id" in data:
        require_user(db, data["owner_id"])

    changed = ", ".join(data.keys())
    for field, value in data.items():
        setattr(contact, field, value)

    log_action(db, user.id, "contact_update", "contact", contact.id, changed)
    db.commit()
    db.refresh(contact)
    return enrich_contact(db, contact)


@router.delete("/{contact_id}", status_code=204)
def delete_contact(
    contact_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    contact = _get_contact_or_404(db, contact_id)
    name = contact.full_name
    db.delete(contact)
    log_action(db, user.id, "contact_delete", "contact", contact_id, name)
    db.commit()
    return None
