import logging
from typing import Optional

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from ..database import SessionLocal
from ..models import Application, User
from ..services.ai_service import ai_service
from ..services.logging_service import log_action
from ..services.notification_service import (
    notify_new_application,
    notify_status_change,
)
from ..services.stats import get_stats

logger = logging.getLogger(__name__)

router = Router()

STATUS_LABELS = {
    "new": "Новая",
    "in_progress": "В работе",
    "done": "Выполнена",
    "cancelled": "Отменена",
}

ALLOWED_STATUSES = set(STATUS_LABELS)


class CreateForm(StatesGroup):
    waiting_title = State()
    waiting_description = State()


def _get_bound_user(telegram_id: int) -> Optional[User]:
    db = SessionLocal()
    try:
        return db.scalar(select(User).where(User.telegram_id == telegram_id))
    finally:
        db.close()


def _status_keyboard(app_id: int, current_status: str) -> InlineKeyboardMarkup:
    rows = []

    for status in ["new", "in_progress", "done", "cancelled"]:
        if status == current_status:
            continue
        rows.append(
            [
                InlineKeyboardButton(
                    text=STATUS_LABELS[status],
                    callback_data="status:" + str(app_id) + ":" + status,
                )
            ]
        )

    return InlineKeyboardMarkup(inline_keyboard=rows)


def _application_text(app: Application) -> str:
    assigned = "не назначен"
    if app.assigned_to:
        assigned = app.assigned_to.full_name

    return "\n".join(
        [
            "Заявка #" + str(app.id),
            "Заголовок: " + app.title,
            "Статус: " + STATUS_LABELS.get(app.status, app.status),
            "Приоритет: " + app.priority,
            "Категория: " + app.category,
            "Клиент: " + (app.client_name or "-"),
            "Контакт: " + (app.client_contact or "-"),
            "Исполнитель: " + assigned,
            "Описание: " + (app.description or "-")[:500],
        ]
    )


async def _change_status(app_id: int, new_status: str, user: User) -> str:
    db = SessionLocal()
    try:
        app = db.get(Application, app_id)
        if not app:
            return "Заявка #" + str(app_id) + " не найдена."

        old_status = app.status
        if old_status == new_status:
            return "Статус заявки #" + str(app_id) + " уже: " + STATUS_LABELS[new_status] + "."

        app.status = new_status
        db.commit()
        db.refresh(app)

        log_action(
            db,
            user.id,
            "status_change",
            "application",
            app.id,
            old_status + " -> " + new_status + " via Telegram",
        )
        db.commit()
        await ai_service.index_application(db, app)

        assigned_user = db.get(User, app.assigned_to_id) if app.assigned_to_id else None
        await notify_status_change(
            app,
            old_status,
            new_status,
            changed_by=user,
            assigned_to=assigned_user,
        )

        return "Готово. Заявка #" + str(app_id) + ": " + STATUS_LABELS[old_status] + " -> " + STATUS_LABELS[new_status] + "."
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Telegram status change failed")
        return "Ошибка базы данных при смене статуса."
    finally:
        db.close()


@router.message(CommandStart())
async def cmd_start(message: Message):
    if not message.from_user:
        return

    user = _get_bound_user(message.from_user.id)

    if not user:
        await message.answer(
            "\n".join(
                [
                    "Привет! Я бот Mini CRM.",
                    "Ваш Telegram ID: " + str(message.from_user.id),
                    "",
                    "Этот ID ещё не привязан к сотруднику.",
                    "Попросите администратора привязать его в разделе Сотрудники или через API.",
                ]
            )
        )
        return

    await message.answer(
        "\n".join(
            [
                "Привет, " + user.full_name + "!",
                "",
                "Команды:",
                "/new - создать заявку",
                "/list - последние заявки",
                "/detail <id> - карточка заявки",
                "/status <id> <status> - сменить статус",
                "/stats - статистика",
                "/help - справка",
            ]
        )
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "\n".join(
            [
                "Доступные команды:",
                "/new - создать заявку диалогом",
                "/list - последние 10 заявок",
                "/detail <id> - посмотреть заявку и кнопки смены статуса",
                "/status <id> <new|in_progress|done|cancelled> - сменить статус",
                "/stats - краткая статистика",
            ]
        )
    )


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    if not message.from_user:
        return

    user = _get_bound_user(message.from_user.id)
    if not user:
        await message.answer("Вы не привязаны к сотруднику. Обратитесь к администратору.")
        return

    db = SessionLocal()
    try:
        stats = get_stats(db)
        text = "\n".join(
            [
                "Статистика",
                "Всего заявок: " + str(stats["total"]),
                "Новые: " + str(stats["by_status"].get("new", 0)),
                "В работе: " + str(stats["by_status"].get("in_progress", 0)),
                "Выполнено: " + str(stats["by_status"].get("done", 0)),
                "Отменено: " + str(stats["by_status"].get("cancelled", 0)),
                "За 7 дней: " + str(stats["last_7_days"]),
                "За 30 дней: " + str(stats["last_30_days"]),
            ]
        )
        await message.answer(text)
    finally:
        db.close()


@router.message(Command("list"))
async def cmd_list(message: Message):
    if not message.from_user:
        return

    user = _get_bound_user(message.from_user.id)
    if not user:
        await message.answer("Вы не привязаны к сотруднику. Обратитесь к администратору.")
        return

    db = SessionLocal()
    try:
        apps = list(
            db.scalars(
                select(Application)
                .order_by(Application.created_at.desc())
                .limit(10)
            ).all()
        )

        if not apps:
            await message.answer("Заявок пока нет.")
            return

        lines = ["Последние заявки:"]
        for app in apps:
            lines.append(
                "#" + str(app.id)
                + " [" + STATUS_LABELS.get(app.status, app.status) + "] "
                + app.title + " - " + (app.client_name or "-")
            )

        lines.append("")
        lines.append("Открыть карточку: /detail <id>")
        await message.answer("\n".join(lines))
    finally:
        db.close()


@router.message(Command("detail"))
async def cmd_detail(message: Message):
    if not message.from_user:
        return

    user = _get_bound_user(message.from_user.id)
    if not user:
        await message.answer("Вы не привязаны к сотруднику. Обратитесь к администратору.")
        return

    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer("Использование: /detail <id>")
        return

    try:
        app_id = int(parts[1])
    except ValueError:
        await message.answer("ID должен быть числом. Пример: /detail 5")
        return

    db = SessionLocal()
    try:
        app = db.get(Application, app_id)
        if not app:
            await message.answer("Заявка #" + str(app_id) + " не найдена.")
            return

        await message.answer(
            _application_text(app),
            reply_markup=_status_keyboard(app.id, app.status),
        )
    finally:
        db.close()


@router.message(Command("status"))
async def cmd_status(message: Message):
    if not message.from_user:
        return

    user = _get_bound_user(message.from_user.id)
    if not user:
        await message.answer("Вы не привязаны к сотруднику. Обратитесь к администратору.")
        return

    parts = (message.text or "").split()
    if len(parts) < 3:
        await message.answer("Использование: /status <id> <new|in_progress|done|cancelled>")
        return

    try:
        app_id = int(parts[1])
    except ValueError:
        await message.answer("ID должен быть числом. Пример: /status 5 done")
        return

    new_status = parts[2].lower()
    if new_status not in ALLOWED_STATUSES:
        await message.answer("Допустимые статусы: new, in_progress, done, cancelled.")
        return

    result = await _change_status(app_id, new_status, user)
    await message.answer(result)


@router.message(Command("new"))
async def cmd_new(message: Message, state: FSMContext):
    if not message.from_user:
        return

    user = _get_bound_user(message.from_user.id)
    if not user:
        await message.answer("Вы не привязаны к сотруднику. Обратитесь к администратору.")
        return

    await state.set_state(CreateForm.waiting_title)
    await message.answer("Введите заголовок заявки:")


@router.message(CreateForm.waiting_title)
async def process_new_title(message: Message, state: FSMContext):
    title = (message.text or "").strip()
    if not title:
        await message.answer("Заголовок не может быть пустым. Попробуйте ещё раз.")
        return

    await state.update_data(title=title)
    await state.set_state(CreateForm.waiting_description)
    await message.answer("Теперь введите описание заявки:")


@router.message(CreateForm.waiting_description)
async def process_new_description(message: Message, state: FSMContext):
    if not message.from_user:
        await state.clear()
        return

    user = _get_bound_user(message.from_user.id)
    if not user:
        await state.clear()
        await message.answer("Вы не привязаны к сотруднику. Обратитесь к администратору.")
        return

    description = (message.text or "").strip()
    data = await state.get_data()
    title = data.get("title", "").strip()

    if not title:
        await state.clear()
        await message.answer("Не удалось сохранить заголовок. Начните заново: /new")
        return

    db = SessionLocal()
    try:
        category = await ai_service.categorize(title, description)

        app = Application(
            title=title,
            description=description,
            status="new",
            priority="medium",
            category=category,
            created_by_id=user.id,
        )

        db.add(app)
        db.commit()
        db.refresh(app)

        log_action(db, user.id, "create", "application", app.id, "Created via Telegram")
        db.commit()
        await ai_service.index_application(db, app)
        await notify_new_application(app, created_by=user, assigned_to=None)

        await state.clear()
        await message.answer(
            "\n".join(
                [
                    "Заявка #" + str(app.id) + " создана.",
                    "Заголовок: " + app.title,
                    "Категория: " + app.category,
                    "",
                    "Детали: /detail " + str(app.id),
                ]
            )
        )
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Telegram application creation failed")
        await state.clear()
        await message.answer("Не удалось создать заявку. Попробуйте позже.")
    finally:
        db.close()


@router.callback_query(lambda callback: callback.data and callback.data.startswith("status:"))
async def callback_change_status(callback: CallbackQuery):
    if not callback.from_user:
        await callback.answer("Неизвестный пользователь", show_alert=True)
        return

    user = _get_bound_user(callback.from_user.id)
    if not user:
        await callback.answer("Вы не привязаны к сотруднику", show_alert=True)
        return

    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer("Некорректная кнопка", show_alert=True)
        return

    try:
        app_id = int(parts[1])
    except ValueError:
        await callback.answer("Некорректный ID", show_alert=True)
        return

    new_status = parts[2]
    if new_status not in ALLOWED_STATUSES:
        await callback.answer("Некорректный статус", show_alert=True)
        return

    result = await _change_status(app_id, new_status, user)
    await callback.answer(result, show_alert=False)

    if callback.message:
        db = SessionLocal()
        try:
            app = db.get(Application, app_id)
            if app:
                await callback.message.edit_reply_markup(
                    reply_markup=_status_keyboard(app.id, app.status)
                )
        finally:
            db.close()
