from typing import Optional

from sqlalchemy.orm import Session

from ..models import ActionLog


def log_action(
    db: Session,
    user_id: Optional[int],
    action: str,
    entity_type: str,
    entity_id: Optional[int] = None,
    details: str = "",
) -> ActionLog:
    """Stage an audit entry on the caller's transaction.

    The caller owns the commit so business data and its audit trail are written
    atomically. Flushing makes ``entry.id`` available immediately.
    """
    entry = ActionLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
    )
    db.add(entry)
    db.flush()
    return entry
