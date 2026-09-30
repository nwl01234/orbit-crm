from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..models import Application, Company, Contact, Task, User

STATUSES = ["new", "in_progress", "done", "cancelled"]
PRIORITIES = ["low", "medium", "high", "urgent"]
SOURCES = ["web", "telegram", "api", "bot", "manual"]
OPEN_STATUSES = ["new", "in_progress"]


def _today() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def get_stats(db: Session, user_id: Optional[int] = None) -> dict:
    total = db.scalar(select(func.count(Application.id))) or 0

    by_status = {status: 0 for status in STATUSES}
    for value, count in db.execute(
        select(Application.status, func.count(Application.id)).group_by(Application.status)
    ):
        by_status[value] = int(count)

    by_priority = {priority: 0 for priority in PRIORITIES}
    for value, count in db.execute(
        select(Application.priority, func.count(Application.id)).group_by(Application.priority)
    ):
        by_priority[value] = int(count)

    by_category: dict[str, int] = {}
    for value, count in db.execute(
        select(Application.category, func.count(Application.id)).group_by(Application.category)
    ):
        by_category[value] = int(count)

    by_source = {source: 0 for source in SOURCES}
    for value, count in db.execute(
        select(Application.source, func.count(Application.id)).group_by(Application.source)
    ):
        by_source[value] = int(count)

    today = _today()
    overdue = db.scalar(
        select(func.count(Application.id)).where(
            Application.due_date.is_not(None),
            Application.due_date < today,
            Application.status.notin_(["done", "cancelled"]),
        )
    ) or 0

    now = datetime.utcnow()
    last_7 = db.scalar(
        select(func.count(Application.id)).where(Application.created_at >= now - timedelta(days=7))
    ) or 0
    last_30 = db.scalar(
        select(func.count(Application.id)).where(Application.created_at >= now - timedelta(days=30))
    ) or 0

    top_clients_rows = list(
        db.execute(
            select(Application.client_name, func.count(Application.id).label("cnt"))
            .where(Application.client_name != "", Application.client_name != "Внутренний запрос")
            .group_by(Application.client_name)
            .order_by(func.count(Application.id).desc())
            .limit(10)
        )
    )
    top_clients = [{"name": name, "count": int(count)} for name, count in top_clients_rows]

    conversion = {
        "entered": total,
        "in_progress": by_status["in_progress"],
        "won": by_status["done"],
        "lost": by_status["cancelled"],
    }

    open_tasks = db.scalar(select(func.count(Task.id)).where(Task.is_done.is_(False))) or 0
    my_open_tasks = 0
    if user_id:
        my_open_tasks = db.scalar(
            select(func.count(Task.id)).where(Task.is_done.is_(False), Task.user_id == user_id)
        ) or 0

    unassigned = db.scalar(
        select(func.count(Application.id)).where(
            Application.assigned_to_id.is_(None),
            Application.status.in_(OPEN_STATUSES),
        )
    ) or 0

    pipeline_amount = db.scalar(
        select(func.coalesce(func.sum(Application.amount), 0)).where(Application.status.in_(OPEN_STATUSES))
    ) or 0
    won_amount = db.scalar(
        select(func.coalesce(func.sum(Application.amount), 0)).where(Application.status == "done")
    ) or 0
    avg_deal_amount = db.scalar(
        select(func.coalesce(func.avg(Application.amount), 0)).where(Application.amount > 0)
    ) or 0

    companies = db.scalar(select(func.count(Company.id))) or 0
    contacts = db.scalar(select(func.count(Contact.id))) or 0

    # 14-day activity trend.
    start = (now - timedelta(days=13)).replace(hour=0, minute=0, second=0, microsecond=0)
    created_rows = dict(
        db.execute(
            select(func.date(Application.created_at), func.count(Application.id))
            .where(Application.created_at >= start)
            .group_by(func.date(Application.created_at))
        ).all()
    )
    closed_rows = dict(
        db.execute(
            select(func.date(Application.closed_at), func.count(Application.id))
            .where(Application.closed_at.is_not(None), Application.closed_at >= start)
            .group_by(func.date(Application.closed_at))
        ).all()
    )
    trend = []
    for index in range(14):
        day = (start + timedelta(days=index)).date().isoformat()
        trend.append(
            {
                "date": day,
                "created": int(created_rows.get(day, 0)),
                "closed": int(closed_rows.get(day, 0)),
            }
        )

    # Team workload.
    workload_rows = list(
        db.execute(
            select(
                User.id,
                User.full_name,
                User.job_title,
                func.count(Application.id).label("open_count"),
            )
            .join(Application, Application.assigned_to_id == User.id)
            .where(Application.status.in_(OPEN_STATUSES))
            .group_by(User.id)
            .order_by(func.count(Application.id).desc())
        )
    )
    workload = [
        {
            "id": row.id,
            "name": row.full_name,
            "job_title": row.job_title or "",
            "initials": "".join(part[:1] for part in row.full_name.split()[:2]).upper(),
            "open": int(row.open_count),
        }
        for row in workload_rows
    ]

    sources = [
        {"key": key, "count": int(count)} for key, count in sorted(by_source.items(), key=lambda x: -x[1])
    ]
    categories = [
        {"key": key, "count": int(count)} for key, count in sorted(by_category.items(), key=lambda x: -x[1])
    ]

    return {
        "total": total,
        "by_status": by_status,
        "by_priority": by_priority,
        "by_category": by_category,
        "by_source": by_source,
        "overdue": int(overdue),
        "last_7_days": int(last_7),
        "last_30_days": int(last_30),
        "top_clients": top_clients,
        "conversion": conversion,
        "open_tasks": int(open_tasks),
        "my_open_tasks": int(my_open_tasks),
        "unassigned": int(unassigned),
        "pipeline_amount": float(pipeline_amount),
        "won_amount": float(won_amount),
        "avg_deal_amount": float(avg_deal_amount),
        "companies": int(companies),
        "contacts": int(contacts),
        "trend": trend,
        "workload": workload,
        "sources": sources,
        "categories": categories,
    }


def get_report(db: Session, days: int = 30) -> dict:
    """Aggregates for the analytics page."""
    now = datetime.utcnow()
    start = now - timedelta(days=days)

    total = db.scalar(select(func.count(Application.id))) or 0
    in_period = db.scalar(
        select(func.count(Application.id)).where(Application.created_at >= start)
    ) or 0
    closed_in_period = db.scalar(
        select(func.count(Application.id)).where(
            Application.closed_at.is_not(None), Application.closed_at >= start
        )
    ) or 0

    won = db.scalar(
        select(func.count(Application.id)).where(
            Application.status == "done", Application.closed_at >= start
        )
    ) or 0
    lost = db.scalar(
        select(func.count(Application.id)).where(
            Application.status == "cancelled", Application.closed_at >= start
        )
    ) or 0
    win_rate = round((won / (won + lost)) * 100) if (won + lost) else 0

    # Cycle time for closed deals (SQLite julianday).
    avg_cycle = db.scalar(
        select(
            func.avg(
                func.julianday(Application.closed_at) - func.julianday(Application.created_at)
            )
        ).where(Application.closed_at.is_not(None), Application.closed_at >= start)
    )

    status_rows = dict(
        db.execute(
            select(Application.status, func.count(Application.id)).group_by(Application.status)
        ).all()
    )
    funnel = [
        {"key": status, "count": int(status_rows.get(status, 0))}
        for status in STATUSES
    ]

    category_rows = list(
        db.execute(
            select(
                Application.category,
                func.count(Application.id),
                func.coalesce(func.sum(Application.amount), 0),
            )
            .group_by(Application.category)
            .order_by(func.count(Application.id).desc())
        )
    )
    categories = [
        {"key": key, "count": int(count), "amount": float(amount)}
        for key, count, amount in category_rows
    ]

    source_rows = list(
        db.execute(
            select(Application.source, func.count(Application.id))
            .where(Application.created_at >= start)
            .group_by(Application.source)
            .order_by(func.count(Application.id).desc())
        )
    )
    sources = [{"key": key, "count": int(count)} for key, count in source_rows]

    team_rows = list(
        db.execute(
            select(
                User.id,
                User.full_name,
                func.count(Application.id).label("total"),
                func.sum(case((Application.status == "done", 1), else_=0)).label("won"),
                func.coalesce(func.sum(Application.amount), 0).label("amount"),
            )
            .join(Application, Application.assigned_to_id == User.id)
            .where(Application.created_at >= start)
            .group_by(User.id)
            .order_by(func.count(Application.id).desc())
        )
    )
    team = [
        {
            "id": row.id,
            "name": row.full_name,
            "total": int(row.total),
            "won": int(row.won or 0),
            "amount": float(row.amount or 0),
            "initials": "".join(part[:1] for part in row.full_name.split()[:2]).upper(),
        }
        for row in team_rows
    ]

    lost_rows = list(
        db.execute(
            select(Application.lost_reason, func.count(Application.id))
            .where(Application.status == "cancelled", Application.lost_reason != "")
            .group_by(Application.lost_reason)
            .order_by(func.count(Application.id).desc())
            .limit(6)
        )
    )
    lost_reasons = [{"reason": reason, "count": int(count)} for reason, count in lost_rows]

    # Six months of created/won volume (calendar months, not 30-day steps).
    months = []
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    for _ in range(6):
        months.append(month_start)
        if month_start.month == 1:
            month_start = month_start.replace(year=month_start.year - 1, month=12)
        else:
            month_start = month_start.replace(month=month_start.month - 1)
    months.reverse()
    month_rows = []
    for month_start in months:
        if month_start.month == 12:
            next_month = month_start.replace(year=month_start.year + 1, month=1)
        else:
            next_month = month_start.replace(month=month_start.month + 1)
        created = db.scalar(
            select(func.count(Application.id)).where(
                Application.created_at >= month_start, Application.created_at < next_month
            )
        ) or 0
        won_month = db.scalar(
            select(func.count(Application.id)).where(
                Application.status == "done",
                Application.closed_at >= month_start,
                Application.closed_at < next_month,
            )
        ) or 0
        month_rows.append(
            {
                "label": month_start.strftime("%m.%y"),
                "created": int(created),
                "won": int(won_month),
            }
        )

    overdue = db.scalar(
        select(func.count(Application.id)).where(
            Application.due_date.is_not(None),
            Application.due_date < _today(),
            Application.status.notin_(["done", "cancelled"]),
        )
    ) or 0

    return {
        "days": days,
        "total": int(total),
        "in_period": int(in_period),
        "closed_in_period": int(closed_in_period),
        "won": int(won),
        "lost": int(lost),
        "win_rate": win_rate,
        "avg_cycle": round(float(avg_cycle or 0), 1),
        "funnel": funnel,
        "categories": categories,
        "sources": sources,
        "team": team,
        "lost_reasons": lost_reasons,
        "months": month_rows,
        "overdue": int(overdue),
    }
