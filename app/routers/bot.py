from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..deps import get_current_admin, get_db
from ..models import User

router = APIRouter(prefix="/api/bot", tags=["bot"])


@router.get("/status")
def bot_status(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    linked_count = db.scalar(select(func.count(User.id)).where(User.telegram_id.is_not(None))) or 0
    return {
        "enabled": settings.telegram_enabled,
        "notify_on_create": settings.TELEGRAM_NOTIFY_ON_CREATE,
        "admin_ids_count": len(settings.telegram_admin_id_list),
        "linked_users": linked_count,
        "commands": [
            "/start",
            "/help",
            "/stats",
            "/list",
            "/detail <id>",
            "/status <id> <new|in_progress|done|cancelled>",
            "/new",
        ],
    }
