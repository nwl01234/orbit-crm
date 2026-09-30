from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..deps import get_current_admin, get_current_user, get_db
from ..models import User
from ..schemas import TelegramBind, UserCreate, UserOut, UserUpdate
from ..security import hash_password
from ..services.logging_service import log_action

router = APIRouter(prefix="/api/users", tags=["users"])


def _get_user_or_404(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    return user


def _active_admins(db: Session, exclude_id: Optional[int] = None) -> int:
    stmt = select(func.count(User.id)).where(User.role == "admin", User.is_active.is_(True))
    if exclude_id:
        stmt = stmt.where(User.id != exclude_id)
    return db.scalar(stmt) or 0


@router.get("", response_model=list[UserOut])
def list_users(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = select(User).order_by(User.is_active.desc(), User.full_name)
    if not include_inactive:
        stmt = stmt.where(User.is_active.is_(True))
    return list(db.scalars(stmt).all())


@router.post("", response_model=UserOut, status_code=201)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    if db.scalar(select(User).where(func.lower(User.username) == payload.username.strip().lower())):
        raise HTTPException(status_code=400, detail="Логин уже занят")
    if db.scalar(select(User).where(func.lower(User.email) == str(payload.email).lower())):
        raise HTTPException(status_code=400, detail="Email уже используется")

    user = User(
        username=payload.username.strip(),
        email=str(payload.email).lower(),
        full_name=payload.full_name.strip(),
        role=payload.role,
        job_title=payload.job_title.strip(),
        phone=payload.phone.strip(),
        hashed_password=hash_password(payload.password),
        is_active=True,
    )
    db.add(user)
    db.flush()
    log_action(db, admin.id, "user_update", "user", user.id, "created " + user.username)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    user = _get_user_or_404(db, user_id)
    data = payload.model_dump(exclude_unset=True)

    if user.id == admin.id and data.get("is_active") is False:
        raise HTTPException(status_code=400, detail="Нельзя деактивировать собственный аккаунт")
    if user.id == admin.id and data.get("role") == "employee" and _active_admins(db, exclude_id=user.id) == 0:
        raise HTTPException(status_code=400, detail="В системе должен остаться хотя бы один администратор")
    if data.get("is_active") is False and user.role == "admin" and _active_admins(db, exclude_id=user.id) == 0:
        raise HTTPException(status_code=400, detail="Нельзя деактивировать последнего администратора")

    if "email" in data and data["email"]:
        email = str(data["email"]).lower()
        existing = db.scalar(select(User).where(func.lower(User.email) == email, User.id != user.id))
        if existing:
            raise HTTPException(status_code=400, detail="Email уже используется")
        user.email = email
    if data.get("role"):
        user.role = data["role"]
    if "full_name" in data and data["full_name"]:
        user.full_name = data["full_name"].strip()
    if "job_title" in data:
        user.job_title = (data["job_title"] or "").strip()
    if "phone" in data:
        user.phone = (data["phone"] or "").strip()
    if "is_active" in data and data["is_active"] is not None:
        user.is_active = data["is_active"]
    if data.get("password"):
        user.hashed_password = hash_password(data["password"])

    log_action(db, admin.id, "user_update", "user", user.id, ", ".join(sorted(data.keys())))
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}/telegram")
def bind_telegram_id(
    user_id: int,
    payload: Optional[TelegramBind] = None,
    telegram_id: Optional[str] = None,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    user = _get_user_or_404(db, user_id)

    raw = telegram_id
    if payload and payload.telegram_id is not None:
        raw = str(payload.telegram_id)
    if payload and payload.telegram_id is None and telegram_id is None:
        raw = ""

    value = str(raw or "").strip()
    if not value:
        user.telegram_id = None
        log_action(db, admin.id, "bind_telegram", "user", user.id, "unbound")
        db.commit()
        return {"ok": True, "user_id": user.id, "telegram_id": None}

    try:
        tg_id = int(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="Telegram ID должен быть числом")

    if tg_id <= 0:
        raise HTTPException(status_code=400, detail="Telegram ID должен быть положительным")

    existing = db.scalar(select(User).where(User.telegram_id == tg_id))
    if existing and existing.id != user.id:
        raise HTTPException(status_code=400, detail="Этот Telegram ID уже привязан к другому сотруднику")

    user.telegram_id = tg_id
    log_action(db, admin.id, "bind_telegram", "user", user.id, str(tg_id))
    db.commit()
    return {"ok": True, "user_id": user.id, "telegram_id": tg_id}
