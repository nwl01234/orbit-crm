import html
import logging
from typing import Optional

import httpx

from ..config import settings
from ..labels import priority_label, status_label
from ..models import Application, User

logger = logging.getLogger(__name__)


def _escape(value: object) -> str:
    return html.escape(str(value if value is not None else ""))


def _unique_chat_ids(*candidates: object) -> list[int]:
    result: list[int] = []
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            value = int(candidate)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if value > 0 and value not in result:
            result.append(value)
    return result


async def send_telegram_message(chat_id: int, text: str) -> bool:
    if not settings.telegram_enabled:
        return False

    url = "https://api.telegram.org/bot" + settings.TELEGRAM_BOT_TOKEN + "/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return True
    except Exception as exc:
        logger.warning("Telegram send failed for chat %s: %s", chat_id, exc)
        return False


async def notify_new_application(
    application: Application,
    created_by: Optional[User] = None,
    assigned_to: Optional[User] = None,
) -> None:
    if not settings.telegram_enabled or not settings.TELEGRAM_NOTIFY_ON_CREATE:
        return

    chat_ids = _unique_chat_ids(
        *(settings.telegram_admin_id_list
          + [
              user.telegram_id
              for user in (created_by, assigned_to)
              if user and user.telegram_id
          ])
    )
    if not chat_ids:
        return

    lines = [
        "<b>Новая заявка</b>",
        "#" + str(application.id) + " · " + _escape(application.title),
        "Статус: " + _escape(status_label(application.status)),
        "Приоритет: " + _escape(priority_label(application.priority)),
        "Клиент: " + _escape(application.client_name or "—"),
    ]
    if application.amount:
        lines.append("Бюджет: " + f"{application.amount:,.0f}".replace(",", " ") + " ₽")
    if application.due_date:
        lines.append("Срок: " + _escape(application.due_date))
    if created_by:
        lines.append("Автор: " + _escape(created_by.full_name))

    text = "\n".join(lines)
    for chat_id in chat_ids:
        await send_telegram_message(chat_id, text)


async def notify_status_change(
    application: Application,
    old_status: str,
    new_status: str,
    changed_by: Optional[User] = None,
    assigned_to: Optional[User] = None,
) -> None:
    if not settings.telegram_enabled:
        return

    chat_ids = _unique_chat_ids(
        *(settings.telegram_admin_id_list
          + [assigned_to.telegram_id if assigned_to and assigned_to.telegram_id else None])
    )
    if not chat_ids:
        return

    text = "\n".join(
        [
            "<b>Статус изменён</b>",
            "#" + str(application.id) + " · " + _escape(application.title),
            _escape(status_label(old_status)) + " → " + _escape(status_label(new_status)),
            "Изменил: " + _escape(changed_by.full_name if changed_by else "—"),
        ]
    )
    for chat_id in chat_ids:
        await send_telegram_message(chat_id, text)


async def notify_assignment(application: Application, assigned_to: Optional[User]) -> None:
    if not settings.telegram_enabled or not assigned_to or not assigned_to.telegram_id:
        return
    text = "\n".join(
        [
            "<b>Вам назначена заявка</b>",
            "#" + str(application.id) + " · " + _escape(application.title),
            "Приоритет: " + _escape(priority_label(application.priority)),
            "Клиент: " + _escape(application.client_name or "—"),
        ]
    )
    await send_telegram_message(assigned_to.telegram_id, text)
