from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..deps import get_current_user, get_db
from ..labels import priority_label, status_label
from ..models import Application, Task, User
from ..schemas import StatsOut
from ..services.stats import get_stats

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=StatsOut)
def dashboard_stats(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return get_stats(db, user.id)


@router.get("/notifications")
def dashboard_notifications(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    items: list[dict] = []

    overdue = list(
        db.scalars(
            select(Application)
            .where(
                Application.due_date.is_not(None),
                Application.due_date < today,
                Application.status.notin_(["done", "cancelled"]),
            )
            .order_by(Application.due_date.asc())
            .limit(6)
        ).all()
    )
    for application in overdue:
        items.append(
            {
                "id": "overdue-" + str(application.id),
                "text": "Просрочена заявка #" + str(application.id) + ": " + application.title,
                "href": "/applications/" + str(application.id),
                "time": "срок " + (application.due_date or ""),
                "kind": "overdue",
            }
        )

    mine = list(
        db.scalars(
            select(Application)
            .where(
                Application.assigned_to_id == user.id,
                Application.status.in_(["new", "in_progress"]),
            )
            .order_by(desc(Application.priority), desc(Application.created_at))
            .limit(5)
        ).all()
    )
    seen = {application.id for application in overdue}
    for application in mine:
        if application.id in seen:
            continue
        items.append(
            {
                "id": "mine-" + str(application.id),
                "text": "На вас: #" + str(application.id) + " " + application.title,
                "href": "/applications/" + str(application.id),
                "time": priority_label(application.priority) + " · " + status_label(application.status),
                "kind": "assigned",
            }
        )

    urgent = list(
        db.scalars(
            select(Application)
            .where(
                Application.priority == "urgent",
                Application.status.in_(["new", "in_progress"]),
            )
            .order_by(desc(Application.created_at))
            .limit(4)
        ).all()
    )
    seen |= {application.id for application in mine}
    for application in urgent:
        if application.id in seen:
            continue
        items.append(
            {
                "id": "urgent-" + str(application.id),
                "text": "Срочная заявка #" + str(application.id) + ": " + application.title,
                "href": "/applications/" + str(application.id),
                "time": "приоритет · срочный",
                "kind": "urgent",
            }
        )

    tasks = list(
        db.scalars(
            select(Task)
            .where(
                Task.user_id == user.id,
                Task.is_done.is_(False),
                Task.due_date.is_not(None),
                Task.due_date <= (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d"),
            )
            .order_by(Task.due_date.asc())
            .limit(4)
        ).all()
    )
    for task in tasks:
        items.append(
            {
                "id": "task-" + str(task.id),
                "text": "Задача: " + task.title,
                "href": "/tasks",
                "time": "срок " + (task.due_date or ""),
                "kind": "task",
            }
        )

    return items[:12]
