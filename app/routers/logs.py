from typing import Optional

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from ..deps import get_current_admin, get_db
from ..models import ActionLog, User
from ..schemas import ActionLogOut

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("", response_model=list[ActionLogOut])
def list_logs(
    response: Response,
    action: Optional[str] = None,
    entity_type: Optional[str] = None,
    user_id: Optional[int] = None,
    q: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    safe_limit = max(1, min(limit, 500))
    stmt = select(ActionLog)
    count_stmt = select(func.count(ActionLog.id))

    if action:
        stmt = stmt.where(ActionLog.action == action)
        count_stmt = count_stmt.where(ActionLog.action == action)
    if entity_type:
        stmt = stmt.where(ActionLog.entity_type == entity_type)
        count_stmt = count_stmt.where(ActionLog.entity_type == entity_type)
    if user_id:
        stmt = stmt.where(ActionLog.user_id == user_id)
        count_stmt = count_stmt.where(ActionLog.user_id == user_id)
    if q and q.strip():
        like = "%" + q.strip() + "%"
        condition = or_(ActionLog.details.ilike(like), ActionLog.action.ilike(like))
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)

    response.headers["X-Total-Count"] = str(db.scalar(count_stmt) or 0)
    logs = list(
        db.scalars(
            stmt.options(joinedload(ActionLog.user))
            .order_by(ActionLog.created_at.desc())
            .offset(max(0, offset))
            .limit(safe_limit)
        ).all()
    )

    result = []
    for log in logs:
        data = ActionLogOut.model_validate(log).model_dump()
        data["username"] = log.user.username if log.user else None
        result.append(ActionLogOut(**data))
    return result
