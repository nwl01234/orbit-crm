STATUS_LABELS = {
    "new": "Новая",
    "in_progress": "В работе",
    "done": "Выполнена",
    "cancelled": "Отменена",
}

STATUS_HINTS = {
    "new": "Не взята в работу",
    "in_progress": "Активная работа",
    "done": "Успешно закрыта",
    "cancelled": "Закрыта без результата",
}

PRIORITY_LABELS = {
    "low": "Низкий",
    "medium": "Средний",
    "high": "Высокий",
    "urgent": "Срочный",
}

CATEGORY_LABELS = {
    "general": "Общее",
    "sales": "Продажи",
    "support": "Поддержка",
    "bug": "Баг",
    "feature": "Фича",
    "billing": "Биллинг",
    "other": "Другое",
}

SOURCE_LABELS = {
    "web": "Веб",
    "telegram": "Telegram",
    "api": "API",
    "bot": "Бот",
    "manual": "Вручную",
}

TASK_KIND_LABELS = {
    "task": "Задача",
    "call": "Звонок",
    "meeting": "Встреча",
    "email": "Письмо",
}

TASK_KIND_ICONS = {
    "task": "check",
    "call": "phone",
    "meeting": "calendar",
    "email": "mail",
}

ACTION_LABELS = {
    "create": "Создание",
    "update": "Обновление",
    "delete": "Удаление",
    "status_change": "Смена статуса",
    "login": "Вход",
    "logout": "Выход",
    "ai_analyze": "AI-анализ",
    "ai_reindex": "Переиндексация",
    "bind_telegram": "Telegram",
    "comment": "Комментарий",
    "create_task": "Задача",
    "update_task": "Задача",
    "delete_task": "Задача",
    "bulk_status": "Массовое обновление",
    "import": "Импорт",
    "export": "Экспорт",
    "profile_update": "Профиль",
    "password_change": "Пароль",
    "user_update": "Сотрудник",
    "company_create": "Компания",
    "company_update": "Компания",
    "company_delete": "Компания",
    "contact_create": "Контакт",
    "contact_update": "Контакт",
    "contact_delete": "Контакт",
}

ACTION_VERBS = {
    "create": "создал(а) заявку",
    "update": "обновил(а) поля",
    "delete": "удалил(а)",
    "status_change": "сменил(а) статус",
    "login": "вошёл(ла) в систему",
    "logout": "вышел(ла)",
    "ai_analyze": "запустил(а) AI-анализ",
    "ai_reindex": "переиндексировал(а) базу",
    "bind_telegram": "привязал(а) Telegram",
    "comment": "оставил(а) комментарий",
    "create_task": "создал(а) задачу",
    "update_task": "обновил(а) задачу",
    "delete_task": "удалил(а) задачу",
    "bulk_status": "массово сменил(а) статус",
    "import": "импортировал(а) заявки",
    "export": "экспортировал(а) заявки",
    "profile_update": "обновил(а) профиль",
    "password_change": "сменил(а) пароль",
    "user_update": "обновил(а) сотрудника",
    "company_create": "создал(а) компанию",
    "company_update": "обновил(а) компанию",
    "company_delete": "удалил(а) компанию",
    "contact_create": "создал(а) контакт",
    "contact_update": "обновил(а) контакт",
    "contact_delete": "удалил(а) контакт",
}

STATUS_CHIP = {
    "new": "status-new",
    "in_progress": "status-progress",
    "done": "status-done",
    "cancelled": "status-cancelled",
}

PRIORITY_CHIP = {
    "low": "priority-low",
    "medium": "priority-medium",
    "high": "priority-high",
    "urgent": "priority-urgent",
}

STATUSES = set(STATUS_LABELS)
PRIORITIES = set(PRIORITY_LABELS)
CATEGORIES = list(CATEGORY_LABELS)
SOURCES = list(SOURCE_LABELS)
TASK_KINDS = list(TASK_KIND_LABELS)


def status_label(value: str) -> str:
    return STATUS_LABELS.get(value, value)


def priority_label(value: str) -> str:
    return PRIORITY_LABELS.get(value, value)


def category_label(value: str) -> str:
    return CATEGORY_LABELS.get(value, value)


def source_label(value: str) -> str:
    return SOURCE_LABELS.get(value, value)


def task_kind_label(value: str) -> str:
    return TASK_KIND_LABELS.get(value, value)


def task_kind_icon(value: str) -> str:
    return TASK_KIND_ICONS.get(value, "check")


def action_verb(value: str) -> str:
    return ACTION_VERBS.get(value, value)


def action_label(value: str) -> str:
    return ACTION_LABELS.get(value, value)


def status_chip(value: str) -> str:
    return STATUS_CHIP.get(value, "status-cancelled")


def priority_chip(value: str) -> str:
    return PRIORITY_CHIP.get(value, "priority-low")


def status_hint(value: str) -> str:
    return STATUS_HINTS.get(value, "")
