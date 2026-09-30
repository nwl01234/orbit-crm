from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..deps import get_current_user, get_db
from ..models import Application, ApplicationVector, User
from ..schemas import AIAnalysisOut, AIChatRequest
from ..services.ai_service import ai_service
from ..services.logging_service import log_action

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.get("/status")
def ai_status(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    indexed = db.scalar(select(func.count(ApplicationVector.app_id))) or 0
    total = db.scalar(select(func.count(Application.id))) or 0
    return {
        "enabled": settings.ai_enabled,
        "available": settings.ai_enabled and ai_service._llm_ok is not False,
        "model": settings.AI_MODEL if settings.ai_enabled else None,
        "embed_model": settings.AI_EMBED_MODEL if settings.ai_enabled else None,
        "indexed": int(indexed),
        "total": int(total),
        "mode": "semantic" if settings.ai_enabled else "rule-based",
    }


@router.post("/analyze/{app_id}", response_model=AIAnalysisOut)
async def analyze_application(
    app_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    application = db.get(Application, app_id)
    if not application:
        raise HTTPException(status_code=404, detail="Заявка не найдена")

    result = await ai_service.analyze_application(
        title=application.title,
        description=application.description,
        client_name=application.client_name,
    )

    application.ai_summary = result["summary"]
    if result["priority"] in {"low", "medium", "high", "urgent"}:
        application.priority = result["priority"]

    log_action(db, user.id, "ai_analyze", "application", application.id, "AI analysis requested")
    db.commit()
    db.refresh(application)
    await ai_service.index_application(db, application)

    return AIAnalysisOut(summary=result["summary"], priority=result["priority"])


@router.post("/chat")
async def chat_with_applications(
    payload: AIChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not payload.messages:
        raise HTTPException(status_code=400, detail="Нужен хотя бы один вопрос")

    question = payload.messages[-1].content.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Вопрос пустой")
    if len(question) > 2000:
        raise HTTPException(status_code=400, detail="Вопрос слишком длинный")

    answer = await ai_service.rag_chat(db, question)
    log_action(db, user.id, "ai_chat", "system", None, question[:120])
    db.commit()
    return {"answer": answer, "mode": "semantic" if settings.ai_enabled else "rule-based"}


@router.post("/categorize")
async def categorize_application(
    payload: dict,
    _: User = Depends(get_current_user),
):
    title = str((payload or {}).get("title", "")).strip()
    description = str((payload or {}).get("description", "")).strip()
    if not title:
        raise HTTPException(status_code=400, detail="Нужен заголовок")

    category = await ai_service.categorize(title, description)
    tags = ai_service.suggest_tags(title, description, category)
    return {"category": category, "tags": tags}


@router.post("/reindex")
async def reindex_ai_index(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    count = await ai_service.reindex_all(db)
    log_action(db, user.id, "ai_reindex", "system", None, "Reindexed " + str(count) + " applications")
    db.commit()
    return {"indexed": count, "ai_enabled": settings.ai_enabled}
