from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..deps import get_current_user, get_db
from ..models import User
from ..schemas import PasswordChange, ProfileUpdate, UserOut
from ..security import hash_password, verify_password
from ..services.logging_service import log_action

router = APIRouter(prefix="/api/me", tags=["profile"])


@router.get("", response_model=UserOut)
def read_profile(user: User = Depends(get_current_user)):
    return user


@router.patch("", response_model=UserOut)
def update_profile(
    payload: ProfileUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    data = payload.model_dump(exclude_unset=True)
    if "email" in data and data["email"]:
        email = str(data["email"]).lower()
        existing = db.scalar(select(User).where(func.lower(User.email) == email, User.id != user.id))
        if existing:
            raise HTTPException(status_code=400, detail="Email уже используется")
        user.email = email
    if "full_name" in data and data["full_name"]:
        user.full_name = data["full_name"].strip()
    if "job_title" in data:
        user.job_title = (data["job_title"] or "").strip()
    if "phone" in data:
        user.phone = (data["phone"] or "").strip()

    log_action(db, user.id, "profile_update", "user", user.id, ", ".join(sorted(data.keys())))
    db.commit()
    db.refresh(user)
    return user


@router.post("/password")
def change_password(
    payload: PasswordChange,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Текущий пароль неверен")
    if verify_password(payload.new_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Новый пароль должен отличаться от текущего")
    user.hashed_password = hash_password(payload.new_password)
    log_action(db, user.id, "password_change", "user", user.id, "self-service")
    db.commit()
    return {"ok": True}
