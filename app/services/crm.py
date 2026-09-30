from typing import Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Application, Comment, Company, Contact, Task, User
from ..schemas import ApplicationListOut, ApplicationOut, CompanyOut, ContactOut

LEGAL_PREFIXES = ("ооо", "оао", "зао", "пао", "ао", "ип", "llc", "ltd", "inc", "corp")


def is_legal_entity(name: str) -> bool:
    first = (name or "").strip().lower().split(" ")[0] if (name or "").strip() else ""
    return first in LEGAL_PREFIXES


def require_user(db: Session, user_id: Optional[int]) -> None:
    if user_id and not db.get(User, user_id):
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="Сотрудник не найден")


def _company_names(db: Session, ids: Iterable[Optional[int]]) -> dict[int, str]:
    clean = {value for value in ids if value}
    if not clean:
        return {}
    return {row.id: row.name for row in db.scalars(select(Company).where(Company.id.in_(clean))).all()}


def _contact_names(db: Session, ids: Iterable[Optional[int]]) -> dict[int, str]:
    clean = {value for value in ids if value}
    if not clean:
        return {}
    return {row.id: row.full_name for row in db.scalars(select(Contact).where(Contact.id.in_(clean))).all()}


def _user_names(db: Session, ids: Iterable[Optional[int]]) -> dict[int, str]:
    clean = {value for value in ids if value}
    if not clean:
        return {}
    return {row.id: row.full_name for row in db.scalars(select(User).where(User.id.in_(clean))).all()}


def enrich_applications(
    db: Session, applications: list[Application], *, with_counts: bool = True
) -> list[ApplicationOut]:
    if not applications:
        return []

    ids = [application.id for application in applications]
    comments_map: dict[int, int] = {}
    tasks_map: dict[int, int] = {}
    if with_counts:
        comments_map = {
            app_id: int(count)
            for app_id, count in db.execute(
                select(Comment.app_id, func.count(Comment.id))
                .where(Comment.app_id.in_(ids))
                .group_by(Comment.app_id)
            )
        }
        tasks_map = {
            app_id: int(count)
            for app_id, count in db.execute(
                select(Task.app_id, func.count(Task.id))
                .where(Task.app_id.in_(ids), Task.is_done.is_(False))
                .group_by(Task.app_id)
            )
        }

    companies = _company_names(db, (application.company_id for application in applications))
    contacts = _contact_names(db, (application.contact_id for application in applications))
    users = _user_names(db, (application.assigned_to_id for application in applications))

    result: list[ApplicationOut] = []
    for application in applications:
        data = ApplicationOut.model_validate(application).model_dump()
        data["comments_count"] = comments_map.get(application.id, 0)
        data["open_tasks_count"] = tasks_map.get(application.id, 0)
        data["assigned_to_name"] = users.get(application.assigned_to_id)
        data["company_name"] = companies.get(application.company_id)
        data["contact_name"] = contacts.get(application.contact_id)
        result.append(ApplicationOut(**data))
    return result


def enrich_application(db: Session, application: Application) -> ApplicationOut:
    return enrich_applications(db, [application])[0]


def enrich_companies(db: Session, companies: list[Company]) -> list[CompanyOut]:
    if not companies:
        return []
    ids = [company.id for company in companies]

    contacts_count = {
        company_id: int(count)
        for company_id, count in db.execute(
            select(Contact.company_id, func.count(Contact.id))
            .where(Contact.company_id.in_(ids))
            .group_by(Contact.company_id)
        )
    }
    deal_rows = db.execute(
        select(
            Application.company_id,
            func.count(Application.id),
            func.sum(
                func.coalesce(
                    Application.amount,
                    0,
                )
            ),
            func.max(Application.updated_at),
        )
        .where(Application.company_id.in_(ids))
        .group_by(Application.company_id)
    ).all()
    deal_stats = {
        company_id: {"count": int(count), "amount": float(amount or 0), "last": last}
        for company_id, count, amount, last in deal_rows
    }
    open_rows = db.execute(
        select(Application.company_id, func.count(Application.id))
        .where(Application.company_id.in_(ids), Application.status.in_(["new", "in_progress"]))
        .group_by(Application.company_id)
    )
    open_map = {company_id: int(count) for company_id, count in open_rows}
    users = _user_names(db, (company.owner_id for company in companies))

    result = []
    for company in companies:
        stats = deal_stats.get(company.id, {"count": 0, "amount": 0.0})
        data = CompanyOut.model_validate(company).model_dump()
        data["owner_name"] = users.get(company.owner_id)
        data["contacts_count"] = contacts_count.get(company.id, 0)
        data["deals_count"] = stats["count"]
        data["open_deals_count"] = open_map.get(company.id, 0)
        data["pipeline_amount"] = stats["amount"]
        result.append(CompanyOut(**data))
    return result


def enrich_company(db: Session, company: Company) -> CompanyOut:
    return enrich_companies(db, [company])[0]


def enrich_contacts(db: Session, contacts: list[Contact]) -> list[ContactOut]:
    if not contacts:
        return []
    ids = [contact.id for contact in contacts]
    rows = db.execute(
        select(
            Application.contact_id,
            func.count(Application.id),
            func.sum(
                func.coalesce(Application.amount, 0),
            ),
            func.max(Application.created_at),
        )
        .where(Application.contact_id.in_(ids))
        .group_by(Application.contact_id)
    ).all()
    stats = {
        contact_id: {"count": int(count), "last": last}
        for contact_id, count, _amount, last in rows
    }
    open_rows = db.execute(
        select(Application.contact_id, func.count(Application.id))
        .where(Application.contact_id.in_(ids), Application.status.in_(["new", "in_progress"]))
        .group_by(Application.contact_id)
    )
    open_map = {contact_id: int(count) for contact_id, count in open_rows}
    companies = _company_names(db, (contact.company_id for contact in contacts))
    users = _user_names(db, (contact.owner_id for contact in contacts))

    result = []
    for contact in contacts:
        entry = stats.get(contact.id, {"count": 0, "last": None})
        data = ContactOut.model_validate(contact).model_dump()
        data["company_name"] = companies.get(contact.company_id)
        data["owner_name"] = users.get(contact.owner_id)
        data["deals_count"] = entry["count"]
        data["open_deals_count"] = open_map.get(contact.id, 0)
        data["last_deal_at"] = entry["last"]
        data["initials"] = contact.initials
        result.append(ContactOut(**data))
    return result


def enrich_contact(db: Session, contact: Contact) -> ContactOut:
    return enrich_contacts(db, [contact])[0]


def resolve_client_links(
    db: Session,
    *,
    company_id: Optional[int],
    contact_id: Optional[int],
    client_name: str,
    client_email: str,
    client_phone: str,
    client_contact: str,
    owner_id: Optional[int],
) -> dict:
    """Resolve free-text client fields into real company/contact records.

    The UI supports both "pick existing" and "type a new client" flows. This
    keeps the book of business consistent without forcing an upfront import.
    """
    from fastapi import HTTPException

    company: Optional[Company] = None
    contact: Optional[Contact] = None

    if contact_id:
        contact = db.get(Contact, contact_id)
        if not contact:
            raise HTTPException(status_code=400, detail="Контакт не найден")
        company = contact.company
    elif company_id:
        company = db.get(Company, company_id)
        if not company:
            raise HTTPException(status_code=400, detail="Компания не найдена")

    name = (client_name or "").strip()
    if not company and not contact:
        if name and not is_legal_entity(name):
            contact = Contact(
                full_name=name,
                email=client_email or (client_contact if "@" in client_contact else ""),
                phone=client_phone,
                owner_id=owner_id,
            )
            db.add(contact)
            db.flush()
        elif name:
            company = db.scalar(select(Company).where(func.lower(Company.name) == name.lower()))
            if not company:
                domain = client_email.split("@")[-1] if "@" in client_email else ""
                company = Company(
                    name=name,
                    email=client_email,
                    phone=client_phone,
                    domain=domain,
                    website=("https://" + domain) if domain else "",
                    owner_id=owner_id,
                )
                db.add(company)
                db.flush()
    elif contact and not company and name and is_legal_entity(name):
        company = db.scalar(select(Company).where(func.lower(Company.name) == name.lower()))
        if company and not contact.company_id:
            contact.company_id = company.id

    if company and not contact:
        contact_name = (client_contact or "").strip()
        if contact_name and "@" not in contact_name and contact_name.lower() != company.name.lower():
            email = client_email or (contact_name if "@" in contact_name else "")
            contact = Contact(
                full_name=contact_name,
                email=email,
                phone=client_phone,
                company_id=company.id,
                owner_id=owner_id,
            )
            db.add(contact)
            db.flush()

    client_name_value = (company.name if company else (contact.full_name if contact else name)) or ""
    client_email_value = client_email or (contact.email if contact else (company.email if company else ""))
    client_phone_value = client_phone or (contact.phone if contact else (company.phone if company else ""))
    client_contact_value = client_contact or (contact.email if contact else "")

    return {
        "company_id": company.id if company else None,
        "contact_id": contact.id if contact else None,
        "client_name": client_name_value,
        "client_email": client_email_value,
        "client_phone": client_phone_value,
        "client_contact": client_contact_value,
    }


def company_deals(db: Session, company_id: int, limit: int = 50) -> list[ApplicationListOut]:
    applications = list(
        db.scalars(
            select(Application)
            .where(Application.company_id == company_id)
            .order_by(Application.created_at.desc())
            .limit(limit)
        ).all()
    )
    enriched = enrich_applications(db, applications, with_counts=False)
    return [
        ApplicationListOut.model_validate(item) for item in enriched
    ]


def contact_deals(db: Session, contact_id: int, limit: int = 50) -> list[ApplicationListOut]:
    applications = list(
        db.scalars(
            select(Application)
            .where(Application.contact_id == contact_id)
            .order_by(Application.created_at.desc())
            .limit(limit)
        ).all()
    )
    enriched = enrich_applications(db, applications, with_counts=False)
    return [ApplicationListOut.model_validate(item) for item in enriched]
