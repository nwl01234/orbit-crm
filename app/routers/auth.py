from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..config import settings
from ..deps import get_current_user, get_db
from ..models import User
from ..schemas import Token, UserLogin, UserOut
from ..security import create_access_token, verify_password
from ..services import rate_limit
from ..services.logging_service import log_action

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _client_key(request: Request, username: str) -> str:
    host = request.client.host if request.client else "unknown"
    return host + ":" + username.strip().lower()


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        "access_token",
        token,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        samesite="lax",
        secure=settings.COOKIE_SECURE,
    )


@router.post("/login", response_model=Token)
def login(payload: UserLogin, request: Request, response: Response, db: Session = Depends(get_db)):
    username = payload.username.strip()
    key = _client_key(request, username)

    if rate_limit.is_limited(key, settings.LOGIN_MAX_ATTEMPTS, settings.LOGIN_WINDOW_SECONDS):
        wait = rate_limit.retry_after(key, settings.LOGIN_WINDOW_SECONDS)
        raise HTTPException(
            status_code=429,
            detail=f"Слишком много попыток. Повторите через {max(wait, 1)} сек.",
        )

    user = db.scalar(
        select(User).where(
            or_(func.lower(User.username) == username.lower(), func.lower(User.email) == username.lower())
        )
    )

    if not user or not user.is_active or not verify_password(payload.password, user.hashed_password):
        rate_limit.record_failure(key, settings.LOGIN_WINDOW_SECONDS)
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")

    rate_limit.reset(key)
    token = create_access_token(user.id)
    _set_cookie(response, token)

    user.last_login_at = datetime.utcnow()
    log_action(db, user.id, "login", "user", user.id, "API login")
    db.commit()

    return Token(access_token=token, user=UserOut.model_validate(user))


@router.post("/logout")
def logout(response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    log_action(db, user.id, "logout", "user", user.id, "API logout")
    db.commit()
    response.delete_cookie("access_token")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
