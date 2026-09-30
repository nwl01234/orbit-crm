import csv
import io
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session, joinedload

from .config import settings
from .database import SessionLocal, init_db
from .deps import get_current_user, get_current_user_optional, get_db
from .labels import (
    ACTION_LABELS,
    CATEGORY_LABELS,
    PRIORITY_LABELS,
    SOURCE_LABELS,
    STATUS_LABELS,
    TASK_KIND_LABELS,
    action_label,
    action_verb,
    category_label,
    priority_chip,
    priority_label,
    source_label,
    status_chip,
    status_hint,
    status_label,
    task_kind_icon,
    task_kind_label,
)
from .models import ActionLog, Application, Comment, Company, Contact, Task, User
from .routers import ai as ai_router
from .routers import applications as applications_router
from .routers import auth as auth_router
from .routers import bot as bot_router
from .routers import companies as companies_router
from .routers import contacts as contacts_router
from .routers import dashboard as dashboard_router
from .routers import logs as logs_router
from .routers import profile as profile_router
from .routers import users as users_router
from .routers.applications import applications_count, applications_query
from .security import create_access_token, verify_password
from .services import rate_limit
from .services.ai_service import ai_service
from .services.crm import enrich_companies, enrich_contacts, enrich_application
from .services.logging_service import log_action
from .services.seed import seed_initial
from .services.stats import get_report, get_stats

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent


def _today_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def _is_overdue(due, status) -> bool:
    if not due:
        return False
    if status in ("done", "cancelled"):
        return False
    return due < _today_iso()


def _money(value) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return "—"
    if number == 0:
        return "0 ₽"
    return f"{number:,.0f}".replace(",", " ") + " ₽"


def _dt(value, fmt: str = "%d.%m.%Y %H:%M") -> str:
    if not value:
        return "—"
    if isinstance(value, str):
        return value
    return value.strftime(fmt)


def _relative(value) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        return value
    delta = datetime.utcnow() - value
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "только что"
    if seconds < 3600:
        return f"{seconds // 60} мин назад"
    if seconds < 86400:
        return f"{seconds // 3600} ч назад"
    if seconds < 86400 * 7:
        return f"{seconds // 86400} дн назад"
    return value.strftime("%d.%m.%Y")


def _initials(value) -> str:
    parts = [part for part in str(value or "?").split() if part]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:1].upper()
    return (parts[0][:1] + parts[1][:1]).upper()


def _plural(value, one: str, few: str, many: str) -> str:
    number = abs(int(value or 0)) % 100
    if 11 <= number <= 19:
        return many
    number = number % 10
    if number == 1:
        return one
    if 2 <= number <= 4:
        return few
    return many


def _day_label(value) -> str:
    if not value:
        return "—"
    if isinstance(value, str):
        try:
            value = datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return value
    today = datetime.utcnow().date()
    if value.date() == today:
        return "Сегодня"
    if value.date() == today + timedelta(days=1):
        return "Завтра"
    if value.date() == today - timedelta(days=1):
        return "Вчера"
    return value.strftime("%d.%m.%Y")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        seed_initial(db)
        if settings.ai_enabled and settings.AI_INDEX_ON_STARTUP:
            indexed = await ai_service.reindex_all(db)
            logger.info("AI index: %s applications", indexed)
        if settings.is_default_secret:
            logger.warning("SECRET_KEY is the default value. Set a strong secret in .env before deploying.")
    finally:
        db.close()
    yield


app = FastAPI(title=settings.APP_NAME, version="7.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    return response


for router in (
    auth_router,
    applications_router,
    companies_router,
    contacts_router,
    users_router,
    profile_router,
    ai_router,
    dashboard_router,
    logs_router,
    bot_router,
):
    app.include_router(router.router)

app.include_router(applications_router.tasks_router)

static_dir = BASE_DIR / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.filters.update(
    {
        "money": _money,
        "dt": _dt,
        "relative": _relative,
        "initials": _initials,
        "plural": _plural,
        "day_label": _day_label,
        "statusLabel": status_label,
        "statusClass": status_chip,
        "statusHint": status_hint,
        "priorityLabel": priority_label,
        "priorityClass": priority_chip,
        "categoryLabel": category_label,
        "sourceLabel": source_label,
        "taskKindLabel": task_kind_label,
        "actionLabel": action_label,
        "actionVerb": action_verb,
    }
)
templates.env.globals.update(
    {
        "today_iso": _today_iso,
        "is_overdue": _is_overdue,
        "statusClass": status_chip,
        "statusLabel": status_label,
        "statusHint": status_hint,
        "priorityClass": priority_chip,
        "priorityLabel": priority_label,
        "categoryLabel": category_label,
        "sourceLabel": source_label,
        "taskKindLabel": task_kind_label,
        "taskKindIcon": task_kind_icon,
        "actionVerb": action_verb,
        "actionLabel": action_label,
        "ai_enabled": settings.ai_enabled,
        "app_name": settings.APP_NAME,
        "app_version": app.version,
        "app_tagline": settings.APP_TAGLINE,
        "status_labels": STATUS_LABELS,
        "priority_labels": PRIORITY_LABELS,
        "category_labels": CATEGORY_LABELS,
        "source_labels": SOURCE_LABELS,
        "task_kind_labels": TASK_KIND_LABELS,
        "action_labels": ACTION_LABELS,
    }
)


def _require(user):
    return None if user else RedirectResponse("/login", status_code=302)


def _require_admin(user):
    if not user:
        return RedirectResponse("/login", status_code=302)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    return None


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "version": app.version,
        "ai_enabled": settings.ai_enabled,
        "telegram_enabled": settings.telegram_enabled,
    }


@app.get("/api/search")
def search(
    q: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = q.strip()
    if not q or len(q) < 2:
        return []
    like = "%" + q + "%"
    results: list[dict] = []

    applications = list(
        db.scalars(
            select(Application)
            .where(
                or_(
                    Application.title.ilike(like),
                    Application.client_name.ilike(like),
                    Application.client_email.ilike(like),
                    Application.tags.ilike(like),
                )
            )
            .order_by(desc(Application.updated_at))
            .limit(6)
        ).all()
    )
    for application in applications:
        results.append(
            {
                "id": "a-" + str(application.id),
                "type": "application",
                "title": "#" + str(application.id) + " " + application.title,
                "sub": (application.client_name or "Без клиента") + " · " + status_label(application.status),
                "href": "/applications/" + str(application.id),
                "chip": status_label(application.status),
                "chipClass": status_chip(application.status),
            }
        )

    companies = list(
        db.scalars(
            select(Company)
            .where(or_(Company.name.ilike(like), Company.domain.ilike(like), Company.industry.ilike(like)))
            .order_by(Company.name)
            .limit(5)
        ).all()
    )
    for company in companies:
        results.append(
            {
                "id": "co-" + str(company.id),
                "type": "company",
                "title": company.name,
                "sub": " · ".join(part for part in [company.industry, company.domain] if part) or "Компания",
                "href": "/companies/" + str(company.id),
                "chip": "компания",
                "chipClass": "chip-neutral",
            }
        )

    contacts = list(
        db.scalars(
            select(Contact)
            .where(
                or_(
                    Contact.full_name.ilike(like),
                    Contact.email.ilike(like),
                    Contact.phone.ilike(like),
                )
            )
            .order_by(Contact.full_name)
            .limit(5)
        ).all()
    )
    for contact in contacts:
        results.append(
            {
                "id": "ct-" + str(contact.id),
                "type": "contact",
                "title": contact.full_name,
                "sub": " · ".join(part for part in [contact.position, contact.company.name if contact.company else ""] if part)
                or contact.email or "Контакт",
                "href": "/contacts/" + str(contact.id),
                "chip": "контакт",
                "chipClass": "chip-neutral",
            }
        )

    tasks = list(
        db.scalars(
            select(Task)
            .where(Task.title.ilike(like), Task.is_done.is_(False))
            .order_by(Task.due_date.asc().nullslast())
            .limit(4)
        ).all()
    )
    for task in tasks:
        results.append(
            {
                "id": "t-" + str(task.id),
                "type": "task",
                "title": task.title,
                "sub": "задача · " + (task.due_date or "без срока"),
                "href": "/tasks",
                "chip": task_kind_label(task.kind),
                "chipClass": "chip-neutral",
            }
        )

    if user.role == "admin":
        people = list(
            db.scalars(
                select(User)
                .where(or_(User.full_name.ilike(like), User.username.ilike(like)))
                .limit(3)
            ).all()
        )
        for person in people:
            results.append(
                {
                    "id": "u-" + str(person.id),
                    "type": "user",
                    "title": person.full_name,
                    "sub": "@" + person.username + " · " + person.role,
                    "href": "/users",
                    "chip": person.role,
                    "chipClass": "chip-neutral",
                }
            )

    return results[:16]


# ------------------------------------------------------------------------- auth


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, user: Optional[User] = Depends(get_current_user_optional)):
    if user:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login", response_class=HTMLResponse)
def login_action(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    host = request.client.host if request.client else "unknown"
    key = host + ":" + username.strip().lower()

    if rate_limit.is_limited(key, settings.LOGIN_MAX_ATTEMPTS, settings.LOGIN_WINDOW_SECONDS):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Слишком много попыток входа. Подождите несколько минут."},
            status_code=429,
        )

    user = db.scalar(
        select(User).where(
            or_(func.lower(User.username) == username.strip().lower(), func.lower(User.email) == username.strip().lower())
        )
    )
    if not user or not user.is_active or not verify_password(password, user.hashed_password):
        rate_limit.record_failure(key, settings.LOGIN_WINDOW_SECONDS)
        return templates.TemplateResponse(
            request, "login.html", {"error": "Неверный логин или пароль"}, status_code=400
        )

    rate_limit.reset(key)
    token = create_access_token(user.id)
    user.last_login_at = datetime.utcnow()
    log_action(db, user.id, "login", "user", user.id, "Web login")
    db.commit()

    response = RedirectResponse("/", status_code=302)
    response.set_cookie(
        "access_token",
        token,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        samesite="lax",
        secure=settings.COOKIE_SECURE,
    )
    return response


@app.post("/logout")
def logout(
    user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    if user:
        log_action(db, user.id, "logout", "user", user.id, "Web logout")
        db.commit()
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("access_token")
    return response


# --------------------------------------------------------------------- dashboard


@app.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    if response := _require(user):
        return response

    stats = get_stats(db, user.id)
    recent = list(
        db.scalars(
            select(Application)
            .options(joinedload(Application.company), joinedload(Application.assigned_to))
            .order_by(desc(Application.updated_at))
            .limit(7)
        ).all()
    )
    overdue = list(
        db.scalars(
            select(Application)
            .options(joinedload(Application.company))
            .where(
                Application.due_date.is_not(None),
                Application.due_date < _today_iso(),
                Application.status.notin_(["done", "cancelled"]),
            )
            .order_by(Application.due_date.asc())
            .limit(5)
        ).all()
    )
    my_tasks = list(
        db.scalars(
            select(Task)
            .where(Task.user_id == user.id, Task.is_done.is_(False))
            .order_by(Task.due_date.asc().nullslast(), Task.created_at.desc())
            .limit(7)
        ).all()
    )
    activity = list(
        db.scalars(
            select(ActionLog)
            .options(joinedload(ActionLog.user))
            .order_by(desc(ActionLog.created_at))
            .limit(8)
        ).all()
    )
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "stats": stats,
            "recent": recent,
            "overdue": overdue,
            "my_tasks": my_tasks,
            "activity": activity,
            "active": "dashboard",
        },
    )


# ------------------------------------------------------------------ applications


@app.get("/applications", response_class=HTMLResponse)
def apps_page(
    request: Request,
    user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    if response := _require(user):
        return response
    companies = list(db.scalars(select(Company).order_by(Company.name).limit(300)).all())
    contacts = list(
        db.scalars(
            select(Contact).options(joinedload(Contact.company)).order_by(Contact.full_name).limit(500)
        ).all()
    )
    users = list(db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.full_name)).all())
    prefill_company_id = request.query_params.get("company_id", "")
    prefill_contact_id = request.query_params.get("contact_id", "")
    return templates.TemplateResponse(
        request,
        "applications.html",
        {
            "user": user,
            "prefill_client": request.query_params.get("client", ""),
            "prefill_status": request.query_params.get("status", ""),
            "prefill_company_id": prefill_company_id,
            "prefill_contact_id": prefill_contact_id,
            "companies": companies,
            "contacts": contacts,
            "team": users,
            "active": "applications",
        },
    )


@app.get("/applications/export.csv")
def export_csv(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    category: Optional[str] = None,
    source: Optional[str] = None,
    q: Optional[str] = None,
    starred: Optional[bool] = None,
    overdue: Optional[bool] = None,
    assigned_to_id: Optional[int] = None,
    unassigned: Optional[bool] = None,
    client: Optional[str] = None,
    company_id: Optional[int] = None,
    contact_id: Optional[int] = None,
    sort: str = "created_at",
    order: str = "desc",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    applications = applications_query(
        db,
        status=status,
        priority=priority,
        category=category,
        source=source,
        q=q,
        starred=starred,
        overdue=overdue,
        assigned_to_id=assigned_to_id,
        unassigned=unassigned,
        client=client,
        company_id=company_id,
        contact_id=contact_id,
        sort=sort,
        order=order,
        limit=500,
    )
    log_action(db, user.id, "export", "application", None, "CSV export")
    db.commit()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "id",
            "title",
            "status",
            "priority",
            "category",
            "source",
            "company",
            "contact",
            "client_name",
            "client_email",
            "client_phone",
            "amount",
            "tags",
            "assigned_to",
            "due_date",
            "created_at",
            "closed_at",
        ]
    )
    for application in applications:
        writer.writerow(
            [
                application.id,
                application.title,
                application.status,
                application.priority,
                application.category,
                application.source,
                application.company.name if application.company else "",
                application.contact.full_name if application.contact else "",
                application.client_name,
                application.client_email,
                application.client_phone,
                application.amount or 0,
                application.tags,
                application.assigned_to.full_name if application.assigned_to else "",
                application.due_date or "",
                application.created_at.strftime("%Y-%m-%d %H:%M") if application.created_at else "",
                application.closed_at.strftime("%Y-%m-%d %H:%M") if application.closed_at else "",
            ]
        )
    payload = "\ufeff" + output.getvalue()
    filename = "applications-" + datetime.utcnow().strftime("%Y%m%d-%H%M") + ".csv"
    return StreamingResponse(
        iter([payload]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/applications/{app_id}", response_class=HTMLResponse)
def app_detail(
    request: Request,
    app_id: int,
    user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    if response := _require(user):
        return response
    application = db.scalar(
        select(Application)
        .options(
            joinedload(Application.assigned_to),
            joinedload(Application.created_by),
            joinedload(Application.company),
            joinedload(Application.contact),
        )
        .where(Application.id == app_id)
    )
    if not application:
        raise HTTPException(404, "Заявка не найдена")

    users = list(db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.full_name)).all())
    comments = list(
        db.scalars(
            select(Comment)
            .options(joinedload(Comment.user))
            .where(Comment.app_id == app_id)
            .order_by(Comment.created_at.asc())
        ).all()
    )
    tasks = list(db.scalars(select(Task).where(Task.app_id == app_id).order_by(Task.created_at.desc())).all())
    logs = list(
        db.scalars(
            select(ActionLog)
            .options(joinedload(ActionLog.user))
            .where(ActionLog.entity_type == "application", ActionLog.entity_id == app_id)
            .order_by(desc(ActionLog.created_at))
            .limit(20)
        ).all()
    )
    related = []
    if application.company_id or application.contact_id:
        condition = []
        if application.company_id:
            condition.append(Application.company_id == application.company_id)
        if application.contact_id:
            condition.append(Application.contact_id == application.contact_id)
        related = list(
            db.scalars(
                select(Application)
                .where(Application.id != app_id, or_(*condition))
                .order_by(desc(Application.created_at))
                .limit(5)
            ).all()
        )
    companies = list(db.scalars(select(Company).order_by(Company.name).limit(300)).all())
    contacts = list(db.scalars(select(Contact).order_by(Contact.full_name).limit(500)).all())
    payload = {
        "id": application.id,
        "title": application.title,
        "description": application.description or "",
        "status": application.status,
        "priority": application.priority,
        "category": application.category,
        "source": application.source,
        "tags": application.tags or "",
        "due_date": application.due_date or "",
        "amount": application.amount or 0,
        "lost_reason": application.lost_reason or "",
        "starred": bool(application.starred),
        "ai_summary": application.ai_summary or "",
        "client_name": application.client_name or "",
        "client_email": application.client_email or "",
        "client_phone": application.client_phone or "",
        "client_contact": application.client_contact or "",
        "company_id": application.company_id,
        "contact_id": application.contact_id,
        "assigned_to_id": application.assigned_to_id,
    }
    return templates.TemplateResponse(
        request,
        "application_detail.html",
        {
            "user": user,
            "app": application,
            "payload": payload,
            "users": users,
            "comments": comments,
            "tasks": tasks,
            "logs": logs,
            "related": related,
            "companies": companies,
            "contacts": contacts,
            "active": "applications",
        },
    )


@app.get("/kanban", response_class=HTMLResponse)
def kanban(
    request: Request,
    user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    if response := _require(user):
        return response
    users = list(db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.full_name)).all())
    return templates.TemplateResponse(
        request, "kanban.html", {"user": user, "team": users, "active": "kanban"}
    )


# ---------------------------------------------------------------------- companies


@app.get("/companies", response_class=HTMLResponse)
def companies_page(
    request: Request,
    q: str = "",
    industry: str = "",
    page: int = 1,
    user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    if response := _require(user):
        return response
    page = max(1, page)
    limit = 30
    stmt = select(Company).options(joinedload(Company.owner))
    if q.strip():
        like = "%" + q.strip() + "%"
        stmt = stmt.where(
            or_(Company.name.ilike(like), Company.domain.ilike(like), Company.industry.ilike(like))
        )
    if industry:
        stmt = stmt.where(Company.industry == industry)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    companies = list(
        db.scalars(stmt.order_by(Company.updated_at.desc()).offset((page - 1) * limit).limit(limit)).all()
    )
    industries = [
        row[0]
        for row in db.execute(
            select(Company.industry)
            .where(Company.industry != "")
            .group_by(Company.industry)
            .order_by(Company.industry)
        ).all()
    ]
    team = list(db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.full_name)).all())
    return templates.TemplateResponse(
        request,
        "companies.html",
        {
            "user": user,
            "companies": enrich_companies(db, companies),
            "industries": industries,
            "team": team,
            "q": q,
            "industry": industry,
            "page": page,
            "pages": max(1, (total + limit - 1) // limit),
            "total": total,
            "active": "companies",
        },
    )


@app.get("/companies/{company_id}", response_class=HTMLResponse)
def company_detail(
    request: Request,
    company_id: int,
    user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    if response := _require(user):
        return response
    company = db.scalar(
        select(Company)
        .options(joinedload(Company.owner), joinedload(Company.contacts))
        .where(Company.id == company_id)
    )
    if not company:
        raise HTTPException(404, "Компания не найдена")
    enriched = enrich_companies(db, [company])[0]
    deals = list(
        db.scalars(
            select(Application)
            .where(Application.company_id == company.id)
            .order_by(desc(Application.created_at))
            .limit(50)
        ).all()
    )
    team = list(db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.full_name)).all())
    return templates.TemplateResponse(
        request,
        "company_detail.html",
        {
            "user": user,
            "company": company,
            "meta": enriched,
            "contacts": enrich_contacts(db, list(company.contacts)),
            "deals": deals,
            "team": team,
            "active": "companies",
        },
    )


# ----------------------------------------------------------------------- contacts


@app.get("/contacts", response_class=HTMLResponse)
def contacts_page(
    request: Request,
    q: str = "",
    company_id: Optional[int] = None,
    page: int = 1,
    user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    if response := _require(user):
        return response
    page = max(1, page)
    limit = 30
    stmt = select(Contact).options(joinedload(Contact.company), joinedload(Contact.owner))
    if q.strip():
        like = "%" + q.strip() + "%"
        stmt = stmt.where(
            or_(Contact.full_name.ilike(like), Contact.email.ilike(like), Contact.phone.ilike(like))
        )
    if company_id:
        stmt = stmt.where(Contact.company_id == company_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    contacts = list(
        db.scalars(stmt.order_by(Contact.updated_at.desc()).offset((page - 1) * limit).limit(limit)).all()
    )
    company_options = list(db.scalars(select(Company).order_by(Company.name).limit(300)).all())
    team = list(db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.full_name)).all())
    return templates.TemplateResponse(
        request,
        "contacts.html",
        {
            "user": user,
            "contacts": enrich_contacts(db, contacts),
            "companies": company_options,
            "team": team,
            "q": q,
            "company_id": company_id,
            "page": page,
            "pages": max(1, (total + limit - 1) // limit),
            "total": total,
            "active": "contacts",
        },
    )


@app.get("/contacts/{contact_id}", response_class=HTMLResponse)
def contact_detail(
    request: Request,
    contact_id: int,
    user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    if response := _require(user):
        return response
    contact = db.scalar(
        select(Contact)
        .options(joinedload(Contact.company), joinedload(Contact.owner))
        .where(Contact.id == contact_id)
    )
    if not contact:
        raise HTTPException(404, "Контакт не найден")
    meta = enrich_contacts(db, [contact])[0]
    deals = list(
        db.scalars(
            select(Application)
            .where(Application.contact_id == contact.id)
            .order_by(desc(Application.created_at))
            .limit(50)
        ).all()
    )
    companies = list(db.scalars(select(Company).order_by(Company.name).limit(300)).all())
    team = list(db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.full_name)).all())
    return templates.TemplateResponse(
        request,
        "contact_detail.html",
        {
            "user": user,
            "contact": contact,
            "meta": meta,
            "deals": deals,
            "companies": companies,
            "team": team,
            "active": "contacts",
        },
    )


# -------------------------------------------------------------------------- tasks


@app.get("/tasks", response_class=HTMLResponse)
def tasks_page(
    request: Request,
    user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    if response := _require(user):
        return response
    team = list(db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.full_name)).all())
    applications = list(
        db.scalars(select(Application).order_by(desc(Application.created_at)).limit(200)).all()
    )
    return templates.TemplateResponse(
        request,
        "tasks.html",
        {"user": user, "team": team, "applications": applications, "active": "tasks"},
    )


# ------------------------------------------------------------------------ reports


@app.get("/reports", response_class=HTMLResponse)
def reports_page(
    request: Request,
    days: int = 30,
    user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    if response := _require(user):
        return response
    days = days if days in (7, 30, 90) else 30
    report = get_report(db, days)
    return templates.TemplateResponse(
        request, "reports.html", {"user": user, "report": report, "days": days, "active": "reports"}
    )


# ------------------------------------------------------------------ users, audit


@app.get("/users", response_class=HTMLResponse)
def users_page(
    request: Request,
    user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    if response := _require_admin(user):
        return response
    users = list(db.scalars(select(User).order_by(User.is_active.desc(), User.full_name)).all())
    return templates.TemplateResponse(
        request, "users.html", {"user": user, "users": users, "active": "users"}
    )


@app.get("/logs", response_class=HTMLResponse)
def logs_page(
    request: Request,
    action: str = "",
    user_id: Optional[int] = None,
    q: str = "",
    page: int = 1,
    user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    if response := _require_admin(user):
        return response
    page = max(1, page)
    limit = 50
    stmt = select(ActionLog).options(joinedload(ActionLog.user))
    if action:
        stmt = stmt.where(ActionLog.action == action)
    if user_id:
        stmt = stmt.where(ActionLog.user_id == user_id)
    if q.strip():
        stmt = stmt.where(ActionLog.details.ilike("%" + q.strip() + "%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    entries = list(
        db.scalars(stmt.order_by(desc(ActionLog.created_at)).offset((page - 1) * limit).limit(limit)).all()
    )
    team = list(db.scalars(select(User).order_by(User.full_name)).all())
    return templates.TemplateResponse(
        request,
        "logs.html",
        {
            "user": user,
            "logs": entries,
            "team": team,
            "actions": sorted(ACTION_LABELS.items()),
            "action": action,
            "user_id": user_id,
            "q": q,
            "page": page,
            "pages": max(1, (total + limit - 1) // limit),
            "total": total,
            "active": "logs",
        },
    )


# --------------------------------------------------------------- ai, bot, account


@app.get("/chat", response_class=HTMLResponse)
def chat_page(
    request: Request,
    user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    if response := _require(user):
        return response
    return templates.TemplateResponse(request, "chat.html", {"user": user, "active": "chat"})


@app.get("/bot", response_class=HTMLResponse)
def bot_page(
    request: Request,
    user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    if response := _require_admin(user):
        return response
    linked = list(db.scalars(select(User).where(User.telegram_id.is_not(None)).order_by(User.full_name)).all())
    return templates.TemplateResponse(
        request,
        "bot.html",
        {"user": user, "settings": settings, "linked_users": linked, "active": "bot"},
    )


@app.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    if response := _require(user):
        return response
    return templates.TemplateResponse(
        request, "settings.html", {"user": user, "settings": settings, "active": "settings"}
    )


# ------------------------------------------------------------------------ errors


@app.exception_handler(404)
async def not_found(request: Request, exc: HTTPException):
    if request.url.path.startswith("/api/"):
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": exc.detail}, status_code=404)
    return templates.TemplateResponse(
        request, "error.html", {"code": 404, "message": exc.detail or "Страница не найдена"}, status_code=404
    )


@app.exception_handler(403)
async def forbidden(request: Request, exc: HTTPException):
    if request.url.path.startswith("/api/"):
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": exc.detail}, status_code=403)
    return templates.TemplateResponse(
        request, "error.html", {"code": 403, "message": exc.detail or "Доступ запрещён"}, status_code=403
    )


@app.exception_handler(Exception)
async def server_error(request: Request, exc: Exception):
    logger.error("Unhandled error on %s", request.url.path, exc_info=exc)
    if request.url.path.startswith("/api/"):
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": "Внутренняя ошибка сервера"}, status_code=500)
    try:
        return templates.TemplateResponse(
            request,
            "error.html",
            {"code": 500, "message": "Внутренняя ошибка сервера"},
            status_code=500,
        )
    except Exception:
        from fastapi.responses import PlainTextResponse

        return PlainTextResponse("Internal Server Error", status_code=500)
