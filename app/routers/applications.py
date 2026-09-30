import csv
import io
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import case, desc, func, or_, select
from sqlalchemy.orm import Session

from ..deps import get_current_user, get_db
from ..labels import PRIORITIES, STATUSES
from ..models import Application, Comment, Task, User
from ..schemas import (
    ActionResult,
    ApplicationCreate,
    ApplicationOut,
    ApplicationPage,
    ApplicationUpdate,
    BulkStatusUpdate,
    CommentCreate,
    CommentOut,
    StatusUpdate,
    TaskCreate,
    TaskOut,
    TaskUpdate,
)
from ..services.ai_service import ai_service
from ..services.crm import enrich_application, enrich_applications, require_user, resolve_client_links
from ..services.logging_service import log_action
from ..services.notification_service import notify_assignment, notify_new_application, notify_status_change

router = APIRouter(prefix="/api/applications", tags=["applications"])

OPEN_STATUSES = ("new", "in_progress")
STATUS_ORDER = case(
    (Application.status == "new", 0),
    (Application.status == "in_progress", 1),
    (Application.status == "done", 2),
    else_=3,
)
PRIORITY_ORDER = case(
    (Application.priority == "urgent", 0),
    (Application.priority == "high", 1),
    (Application.priority == "medium", 2),
    else_=3,
)
SORTS = {
    "created_at": Application.created_at,
    "updated_at": Application.updated_at,
    "due_date": Application.due_date,
    "amount": Application.amount,
    "title": Application.title,
    "status": STATUS_ORDER,
    "priority": PRIORITY_ORDER,
    "closed_at": Application.closed_at,
}


def _today() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def _get_application_or_404(db: Session, app_id: int) -> Application:
    application = db.get(Application, app_id)
    if not application:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    return application


def _validate_assigned_user(db: Session, assigned_to_id: Optional[int]) -> None:
    require_user(db, assigned_to_id)


def _conditions(
    *,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    category: Optional[str] = None,
    source: Optional[str] = None,
    q: Optional[str] = None,
    tag: Optional[str] = None,
    starred: Optional[bool] = None,
    overdue: Optional[bool] = None,
    assigned_to_id: Optional[int] = None,
    unassigned: Optional[bool] = None,
    client: Optional[str] = None,
    company_id: Optional[int] = None,
    contact_id: Optional[int] = None,
) -> list:
    conditions = []

    if status:
        if status not in STATUSES:
            raise HTTPException(status_code=400, detail="Некорректный статус")
        conditions.append(Application.status == status)
    if priority:
        if priority not in PRIORITIES:
            raise HTTPException(status_code=400, detail="Некорректный приоритет")
        conditions.append(Application.priority == priority)
    if category:
        conditions.append(Application.category == category)
    if source:
        conditions.append(Application.source == source)
    if starred is not None:
        conditions.append(Application.starred == starred)
    if assigned_to_id:
        conditions.append(Application.assigned_to_id == assigned_to_id)
    if unassigned:
        conditions.append(Application.assigned_to_id.is_(None))
    if company_id:
        conditions.append(Application.company_id == company_id)
    if contact_id:
        conditions.append(Application.contact_id == contact_id)
    if client:
        conditions.append(Application.client_name.ilike("%" + client.strip() + "%"))
    if tag:
        conditions.append(Application.tags.ilike("%" + tag.strip() + "%"))
    if q and q.strip():
        like = "%" + q.strip() + "%"
        conditions.append(
            or_(
                Application.title.ilike(like),
                Application.description.ilike(like),
                Application.client_name.ilike(like),
                Application.client_email.ilike(like),
                Application.client_phone.ilike(like),
                Application.client_contact.ilike(like),
                Application.tags.ilike(like),
            )
        )
    if overdue:
        conditions.append(Application.due_date.is_not(None))
        conditions.append(Application.due_date < _today())
        conditions.append(Application.status.notin_(["done", "cancelled"]))
    return conditions


def applications_query(
    db: Session,
    *,
    sort: str = "created_at",
    order: str = "desc",
    limit: int = 100,
    offset: int = 0,
    **filters,
):
    safe_limit = max(1, min(limit, 500))
    conditions = _conditions(**filters)
    column = SORTS.get(sort, Application.created_at)
    stmt = select(Application).where(*conditions)
    stmt = stmt.order_by(column.asc() if order.lower() == "asc" else column.desc(), Application.id.desc())
    return list(db.scalars(stmt.offset(max(0, offset)).limit(safe_limit)).all())


def applications_count(db: Session, **filters) -> int:
    conditions = _conditions(**filters)
    return db.scalar(select(func.count(Application.id)).where(*conditions)) or 0


@router.get("", response_model=ApplicationPage)
def list_applications(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    category: Optional[str] = None,
    source: Optional[str] = None,
    q: Optional[str] = None,
    tag: Optional[str] = None,
    starred: Optional[bool] = None,
    overdue: Optional[bool] = None,
    assigned_to_id: Optional[int] = None,
    unassigned: Optional[bool] = None,
    client: Optional[str] = None,
    company_id: Optional[int] = None,
    contact_id: Optional[int] = None,
    sort: str = "created_at",
    order: str = "desc",
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    filters = {
        "status": status,
        "priority": priority,
        "category": category,
        "source": source,
        "q": q,
        "tag": tag,
        "starred": starred,
        "overdue": overdue,
        "assigned_to_id": assigned_to_id,
        "unassigned": unassigned,
        "client": client,
        "company_id": company_id,
        "contact_id": contact_id,
    }
    applications = applications_query(
        db, sort=sort, order=order, limit=limit, offset=offset, **filters
    )
    total = applications_count(db, **filters)
    return ApplicationPage(
        items=enrich_applications(db, applications),
        total=total,
        limit=max(1, min(limit, 500)),
        offset=max(0, offset),
    )


@router.post("/bulk-status", response_model=ActionResult)
async def bulk_status(
    payload: BulkStatusUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if payload.status not in STATUSES:
        raise HTTPException(status_code=400, detail="Некорректный статус")

    updated = 0
    now = datetime.utcnow()
    for app_id in payload.ids:
        application = db.get(Application, app_id)
        if not application or application.status == payload.status:
            continue
        old_status = application.status
        application.status = payload.status
        _apply_closed_at(application, payload.status, now)
        log_action(db, user.id, "bulk_status", "application", application.id, old_status + " -> " + payload.status)
        updated += 1
    db.commit()
    return ActionResult(updated=updated)


def _apply_closed_at(application: Application, status: str, now: Optional[datetime] = None) -> None:
    if status in ("done", "cancelled"):
        if not application.closed_at:
            application.closed_at = now or datetime.utcnow()
    else:
        application.closed_at = None


@router.post("", response_model=ApplicationOut, status_code=201)
async def create_application(
    payload: ApplicationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _validate_assigned_user(db, payload.assigned_to_id)

    data = payload.model_dump()
    links = resolve_client_links(
        db,
        company_id=data.pop("company_id", None),
        contact_id=data.pop("contact_id", None),
        client_name=data.get("client_name", ""),
        client_email=data.get("client_email", ""),
        client_phone=data.get("client_phone", ""),
        client_contact=data.get("client_contact", ""),
        owner_id=user.id,
    )
    data.update(links)

    application = Application(**data, created_by_id=user.id)
    _apply_closed_at(application, application.status)

    if not application.tags:
        application.tags = ai_service.suggest_tags(
            application.title, application.description, application.category
        )
    if not application.category or application.category == "general":
        application.category = await ai_service.categorize(application.title, application.description)

    db.add(application)
    db.flush()
    log_action(db, user.id, "create", "application", application.id, application.title)
    db.commit()
    db.refresh(application)

    await ai_service.index_application(db, application)

    assigned_user = db.get(User, application.assigned_to_id) if application.assigned_to_id else None
    await notify_new_application(application, created_by=user, assigned_to=assigned_user)

    return enrich_application(db, application)


@router.post("/import")
async def import_applications(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Нужен CSV-файл")

    raw = await file.read()
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Файл больше 5 МБ")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1251", errors="replace")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "title" not in [name.strip().lower() for name in reader.fieldnames]:
        raise HTTPException(status_code=400, detail="В CSV нужна колонка title")

    imported = 0
    skipped = 0
    errors: list[str] = []
    now = datetime.utcnow()

    for line_number, row in enumerate(reader, start=2):
        if line_number > 5002:
            break
        normalized = {(key or "").strip().lower(): (value or "").strip() for key, value in row.items()}
        title = normalized.get("title", "")
        if not title:
            skipped += 1
            continue

        status = normalized.get("status", "new") or "new"
        priority = normalized.get("priority", "medium") or "medium"
        if status not in STATUSES or priority not in PRIORITIES:
            errors.append(f"Строка {line_number}: неверный статус или приоритет")
            skipped += 1
            continue

        due_date = normalized.get("due_date") or None
        if due_date:
            try:
                datetime.strptime(due_date, "%Y-%m-%d")
            except ValueError:
                errors.append(f"Строка {line_number}: дата должна быть YYYY-MM-DD")
                skipped += 1
                continue

        try:
            amount = float(normalized.get("amount") or 0)
        except ValueError:
            amount = 0

        links = resolve_client_links(
            db,
            company_id=None,
            contact_id=None,
            client_name=normalized.get("client_name") or normalized.get("company") or "",
            client_email=normalized.get("client_email", ""),
            client_phone=normalized.get("client_phone", ""),
            client_contact=normalized.get("client_contact", ""),
            owner_id=user.id,
        )
        application = Application(
            title=title[:255],
            description=normalized.get("description", ""),
            status=status,
            priority=priority,
            category=normalized.get("category", "general") or "general",
            source=normalized.get("source", "manual") or "manual",
            tags=normalized.get("tags", ""),
            due_date=due_date,
            amount=max(0, amount),
            client_name=links["client_name"],
            client_email=links["client_email"],
            client_phone=links["client_phone"],
            client_contact=links["client_contact"],
            company_id=links["company_id"],
            contact_id=links["contact_id"],
            created_by_id=user.id,
        )
        _apply_closed_at(application, status, now)
        db.add(application)
        imported += 1

    log_action(db, user.id, "import", "application", None, f"imported={imported} skipped={skipped}")
    db.commit()

    return {"imported": imported, "skipped": skipped, "errors": errors[:10]}


@router.get("/{app_id}", response_model=ApplicationOut)
def get_application(
    app_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return enrich_application(db, _get_application_or_404(db, app_id))


@router.patch("/{app_id}", response_model=ApplicationOut)
async def update_application(
    app_id: int,
    payload: ApplicationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    application = _get_application_or_404(db, app_id)
    data = payload.model_dump(exclude_unset=True)

    if "status" in data and data["status"] not in STATUSES:
        raise HTTPException(status_code=400, detail="Некорректный статус")
    if "priority" in data and data["priority"] not in PRIORITIES:
        raise HTTPException(status_code=400, detail="Некорректный приоритет")
    if "assigned_to_id" in data:
        _validate_assigned_user(db, data["assigned_to_id"])

    old_status = application.status
    old_assignee = application.assigned_to_id

    client_fields = {"company_id", "contact_id", "client_name", "client_email", "client_phone", "client_contact"}
    touches_client = bool(client_fields & data.keys())

    simple_fields = {key: value for key, value in data.items() if key not in client_fields and key != "status"}
    for field, value in simple_fields.items():
        setattr(application, field, value)

    if "status" in data and data["status"] != old_status:
        application.status = data["status"]
        _apply_closed_at(application, data["status"])
        if data["status"] != "cancelled":
            application.lost_reason = ""

    if touches_client:
        links = resolve_client_links(
            db,
            company_id=data.get("company_id", application.company_id),
            contact_id=data.get("contact_id", application.contact_id),
            client_name=data.get("client_name", application.client_name),
            client_email=data.get("client_email", application.client_email),
            client_phone=data.get("client_phone", application.client_phone),
            client_contact=data.get("client_contact", application.client_contact),
            owner_id=application.created_by_id or user.id,
        )
        for field, value in links.items():
            setattr(application, field, value)

    log_action(
        db,
        user.id,
        "update",
        "application",
        application.id,
        ", ".join(sorted(data.keys())) or "noop",
    )
    db.commit()
    db.refresh(application)

    await ai_service.index_application(db, application)

    if "status" in data and application.status != old_status:
        assigned_user = db.get(User, application.assigned_to_id) if application.assigned_to_id else None
        await notify_status_change(
            application, old_status, application.status, changed_by=user, assigned_to=assigned_user
        )
    if "assigned_to_id" in data and application.assigned_to_id != old_assignee:
        newly_assigned = db.get(User, application.assigned_to_id) if application.assigned_to_id else None
        await notify_assignment(application, newly_assigned)

    return enrich_application(db, application)


@router.patch("/{app_id}/status", response_model=ApplicationOut)
async def change_application_status(
    app_id: int,
    payload: StatusUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if payload.status not in STATUSES:
        raise HTTPException(status_code=400, detail="Некорректный статус")

    application = _get_application_or_404(db, app_id)
    old_status = application.status
    if old_status == payload.status:
        return enrich_application(db, application)

    application.status = payload.status
    _apply_closed_at(application, payload.status)
    log_action(db, user.id, "status_change", "application", application.id, old_status + " -> " + payload.status)
    db.commit()
    db.refresh(application)

    await ai_service.index_application(db, application)

    assigned_user = db.get(User, application.assigned_to_id) if application.assigned_to_id else None
    await notify_status_change(
        application, old_status, application.status, changed_by=user, assigned_to=assigned_user
    )
    return enrich_application(db, application)


@router.post("/{app_id}/star")
def toggle_star(
    app_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    application = _get_application_or_404(db, app_id)
    application.starred = not application.starred
    db.commit()
    return {"starred": application.starred}


@router.post("/{app_id}/comments", response_model=CommentOut)
def add_comment(
    app_id: int,
    payload: CommentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _get_application_or_404(db, app_id)
    comment = Comment(
        app_id=app_id,
        user_id=user.id,
        text=payload.text.strip(),
        is_internal=payload.is_internal,
    )
    db.add(comment)
    log_action(db, user.id, "comment", "application", app_id, payload.text.strip()[:120])
    db.commit()
    db.refresh(comment)
    return CommentOut(
        id=comment.id,
        app_id=comment.app_id,
        user_id=comment.user_id,
        text=comment.text,
        is_internal=comment.is_internal,
        created_at=comment.created_at,
        user_name=user.full_name,
    )


@router.delete("/comments/{comment_id}", status_code=204)
def delete_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    comment = db.get(Comment, comment_id)
    if not comment:
        raise HTTPException(status_code=404, detail="Комментарий не найден")
    if comment.user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Можно удалять только свои комментарии")
    db.delete(comment)
    db.commit()
    return None


@router.post("/{app_id}/tasks", response_model=TaskOut)
def add_task(
    app_id: int,
    payload: TaskCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _get_application_or_404(db, app_id)
    assignee_id = payload.user_id or user.id
    require_user(db, assignee_id)
    task = Task(
        app_id=app_id,
        user_id=assignee_id,
        title=payload.title.strip(),
        kind=payload.kind,
        due_date=payload.due_date,
    )
    db.add(task)
    log_action(db, user.id, "create_task", "application", app_id, payload.title.strip()[:120])
    db.commit()
    db.refresh(task)
    return _task_out(db, task)


@router.delete("/{app_id}", status_code=204)
async def delete_application(
    app_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    application = _get_application_or_404(db, app_id)
    title = application.title
    await ai_service.delete_application_vector(db, app_id)
    db.delete(application)
    log_action(db, user.id, "delete", "application", app_id, title)
    db.commit()
    return None


# ----------------------------------------------------------------------- tasks

tasks_router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _task_out(db: Session, task: Task) -> TaskOut:
    data = TaskOut.model_validate(task).model_dump()
    data["user_name"] = task.user.full_name if task.user else None
    data["application_title"] = task.application.title if task.application else None
    return TaskOut(**data)


@tasks_router.get("", response_model=list[TaskOut])
def list_tasks(
    is_done: Optional[bool] = None,
    user_id: Optional[int] = None,
    app_id: Optional[int] = None,
    kind: Optional[str] = None,
    q: Optional[str] = None,
    overdue: Optional[bool] = None,
    limit: int = 200,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    limit = max(1, min(limit, 500))
    stmt = select(Task)
    if is_done is not None:
        stmt = stmt.where(Task.is_done == is_done)
    if user_id:
        stmt = stmt.where(Task.user_id == user_id)
    if app_id:
        stmt = stmt.where(Task.app_id == app_id)
    if kind:
        stmt = stmt.where(Task.kind == kind)
    if q and q.strip():
        stmt = stmt.where(Task.title.ilike("%" + q.strip() + "%"))
    if overdue:
        stmt = stmt.where(Task.due_date.is_not(None), Task.due_date < _today(), Task.is_done.is_(False))
    stmt = stmt.order_by(Task.is_done.asc(), Task.due_date.asc().nullslast(), Task.created_at.desc()).limit(limit)
    return [_task_out(db, task) for task in db.scalars(stmt).all()]


@tasks_router.post("", response_model=TaskOut, status_code=201)
def create_standalone_task(
    payload: TaskCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if payload.app_id:
        _get_application_or_404(db, payload.app_id)
    assignee_id = payload.user_id or user.id
    require_user(db, assignee_id)
    task = Task(
        app_id=payload.app_id,
        user_id=assignee_id,
        title=payload.title.strip(),
        kind=payload.kind,
        due_date=payload.due_date,
    )
    db.add(task)
    log_action(db, user.id, "create_task", "task", None, payload.title.strip()[:120])
    db.commit()
    db.refresh(task)
    return _task_out(db, task)


@tasks_router.patch("/{task_id}", response_model=TaskOut)
def update_task(
    task_id: int,
    payload: TaskUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    data = payload.model_dump(exclude_unset=True)
    if "title" in data and data["title"]:
        task.title = data["title"].strip()
    if "due_date" in data:
        task.due_date = data["due_date"] or None
    if "kind" in data and data["kind"]:
        task.kind = data["kind"]
    if "user_id" in data:
        require_user(db, data["user_id"])
        task.user_id = data["user_id"]
    if "is_done" in data and data["is_done"] is not None:
        task.is_done = data["is_done"]
        if task.is_done:
            task.completed_at = datetime.utcnow()
        else:
            task.completed_at = None

    log_action(db, user.id, "update_task", "task", task.id, task.title[:120])
    db.commit()
    db.refresh(task)
    return _task_out(db, task)


@tasks_router.delete("/{task_id}")
def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    title = task.title
    db.delete(task)
    log_action(db, user.id, "delete_task", "task", task_id, title[:120])
    db.commit()
    return {"ok": True}
