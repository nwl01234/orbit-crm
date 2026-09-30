from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import ActionLog, Application, Comment, Company, Contact, Task, User
from ..security import hash_password


def _dt(days: int, hours: int = 0) -> datetime:
    return datetime.utcnow() - timedelta(days=days, hours=hours)


def _date(delta_days: int) -> str:
    return (datetime.utcnow() + timedelta(days=delta_days)).strftime("%Y-%m-%d")


# Client name -> CRM company + primary contact. Keeping this curated makes the
# demo look like a real book of business instead of generated noise.
COMPANY_SEEDS: dict[str, dict] = {
    "ООО Ромашка": {
        "industry": "Производство",
        "size": "200-500",
        "domain": "romashka.ru",
        "address": "Москва, Пресненская наб., 12",
        "contacts": [
            ("Алексей Морозов", "Руководитель закупок", "a.morozov@romashka.ru", "+7 900 111-22-10"),
            ("Дмитрий Лебедев", "Финансовый директор", "d.lebedev@romashka.ru", "+7 900 111-22-11"),
        ],
    },
    "ООО Лютик": {
        "industry": "Ритейл",
        "size": "50-200",
        "domain": "lutyk.ru",
        "address": "Санкт-Петербург, Лиговский пр., 74",
        "contacts": [("Елена Крылова", "Операционный директор", "e.krylova@lutyk.ru", "+7 921 200-10-10")],
    },
    "ИП Сидоров": {
        "industry": "Услуги",
        "size": "1-10",
        "domain": "sidorov.pro",
        "address": "Казань, ул. Баумана, 5",
        "contacts": [("Сидоров Пётр", "Владелец", "sidorov@mail.ru", "+7 917 300-20-20")],
    },
    "ООО Вектор": {
        "industry": "Логистика",
        "size": "200-500",
        "domain": "vector.io",
        "address": "Москва, ул. Складочная, 1",
        "contacts": [("Наталья Орлова", "Руководитель поддержки", "n.orlova@vector.io", "+7 495 600-30-30")],
    },
    "ООО Гамма": {
        "industry": "Финтех",
        "size": "500+",
        "domain": "gamma.ru",
        "address": "Москва, Ленинградский пр., 39",
        "contacts": [("Кирилл Соколов", "CTO", "k.sokolov@gamma.ru", "+7 495 700-40-40")],
    },
    "ООО Дельта": {
        "industry": "SaaS",
        "size": "50-200",
        "domain": "delta.io",
        "address": "Екатеринбург, ул. Малышева, 51",
        "contacts": [("Алина Ветрова", "Продуктовый менеджер", "a.vetrova@delta.io", "+7 343 800-50-50")],
    },
    "ООО Альфа": {
        "industry": "Дистрибуция",
        "size": "200-500",
        "domain": "alpha.ru",
        "address": "Новосибирск, Красный пр., 100",
        "contacts": [("Максим Зайцев", "IT-директор", "m.zaytsev@alpha.ru", "+7 383 900-60-60")],
    },
    "ООО Омега": {
        "industry": "Консалтинг",
        "size": "50-200",
        "domain": "omega.ru",
        "address": "Москва, Кутузовский пр., 36",
        "contacts": [("Юрий Белов", "Юридический директор", "y.belov@omega.ru", "+7 495 111-70-70")],
    },
    "Внутренний запрос": {
        "industry": "Внутренние проекты",
        "size": "1-10",
        "domain": "orbit.local",
        "address": "",
        "contacts": [("Ирина Соколова", "Операционный директор", "irina@orbit.local", "")],
    },
}

PERSON_SEEDS: dict[str, dict] = {
    "Иван Петров": {"position": "Технический директор", "company": "Example Labs", "industry": "SaaS", "domain": "example.com"},
    "Мария Иванова": {"position": "Основатель", "company": "", "industry": "Freelance", "domain": "example.com"},
    "Анна Смирнова": {"position": "Руководитель проектов", "company": "", "industry": "Консалтинг", "domain": "smirnova.com"},
    "Сергей Кузнецов": {"position": "Владелец", "company": "", "industry": "E-commerce", "domain": "mail.ru"},
    "Ирина Соколова": {"position": "Операционный директор", "company": "Orbit CRM", "industry": "Внутренние проекты", "domain": "orbit.local"},
    "Артём Волков": {"position": "Руководитель продаж", "company": "Orbit CRM", "industry": "Внутренние проекты", "domain": "orbit.local"},
    "Ольга Титова": {"position": "Руководитель поддержки", "company": "Orbit CRM", "industry": "Внутренние проекты", "domain": "orbit.local"},
    "Полина Юсупова": {"position": "Юрист", "company": "", "industry": "Юриспруденция", "domain": "example.com"},
}


def _seed_users(db: Session) -> list[User]:
    existing = list(db.scalars(select(User).order_by(User.id)).all())
    if existing:
        return existing

    people = [
        (settings.ADMIN_USERNAME, settings.ADMIN_EMAIL, "Александр Ветров", "admin", settings.ADMIN_PASSWORD, "Руководитель операций", "+7 900 000-00-01"),
        ("manager", "manager@example.com", "Ирина Соколова", "admin", "manager123", "Операционный директор", "+7 900 000-00-02"),
        ("dev1", "dev1@example.com", "Павел Громов", "employee", "emp12345", "Ведущий инженер", ""),
        ("support1", "support1@example.com", "Ольга Титова", "employee", "emp12345", "Руководитель поддержки", ""),
        ("sales1", "sales1@example.com", "Артём Волков", "employee", "emp12345", "Менеджер по продажам", "+7 900 000-00-05"),
    ]

    created: list[User] = []
    for username, email, full_name, role, password, job_title, phone in people:
        user = User(
            username=username,
            email=email,
            full_name=full_name,
            role=role,
            job_title=job_title,
            phone=phone,
            hashed_password=hash_password(password),
            is_active=True,
        )
        db.add(user)
        created.append(user)

    db.commit()
    for user in created:
        db.refresh(user)
    return created


SAMPLES = [
    ("Интеграция с 1С: выгрузка заказов", "Нужна автоматическая выгрузка заказов из CRM в 1С по расписанию. Обсудить формат обмена (CSV/XML) и обработку коллизий.", "in_progress", "high", "sales", "web", "1c,интеграция,B2B", 6, "ООО Ромашка", "info@romashka.ru", "+7 900 111-22-33", "+7 900 111-22-33", 2, "Крупный B2B-запрос на интеграцию. Высокий чек, нужен техлид."),
    ("Ошибка оплаты через СБП — 500", "При оплате по QR СБП на бою возвращается 500. Воспроизводится на 2 из 3 карт.", "new", "urgent", "bug", "web", "оплата,прод,500", 0, "Иван Петров", "ivan@example.com", "+7 999 111-11-11", "ivan@example.com", 2, "Продакшн-инцидент. Влияет на выручку немедленно."),
    ("Экспорт списка заявок в Excel", "Добавить кнопку экспорта текущего отфильтрованного списка заявок в .xlsx.", "new", "medium", "feature", "web", "экспорт,ux", 14, "ООО Лютик", "info@lutyk.ru", "", "", 3, "Небольшая UX-фича, низкий риск."),
    ("Telegram-уведомления о новых заявках", "Интеграция с ботом: пуш админам при создании заявки и при смене статуса.", "done", "medium", "feature", "telegram", "бот,уведомления", None, "ИП Сидоров", "sidorov@mail.ru", "", "", 2, "Выполнено. Канал Telegram подключён."),
    ("Запрос скидки на годовой тариф", "Клиент просит 20% скидку при переходе на годовую предоплату.", "in_progress", "low", "billing", "web", "тариф,скидка,retention", 9, "Мария Иванова", "maria@example.com", "+7 921 555-44-33", "maria@example.com", 4, "Вопрос удержания. Скидка обоснована при годовом контракте."),
    ("Письма не доходят части клиентов", "SMTP настроен, но транзакционные письма теряются у доменов на Outlook.", "new", "high", "support", "web", "email,deliverability", 2, "ООО Вектор", "support@vector.io", "", "", 3, "Проблема доставляемости. Похоже на репутацию IP."),
    ("Консультация по API личного кабинета", "Клиенту нужна архитектура интеграции ЛК с внешней ERP.", "done", "low", "sales", "manual", "api,консалтинг", None, "Анна Смирнова", "anna@smirnova.com", "", "anna@smirnova.com", 4, "Закрыто. Консультация проведена."),
    ("Ускорить страницу списка заявок", "При 1000+ записей список грузится ~5 сек. Нужна пагинация.", "new", "medium", "bug", "web", "perf,база", 10, "ООО Гамма", "info@gamma.ru", "", "", 2, "Производительность. Отсутствие индексов."),
    ("Отмена подписки и возврат", "Клиент просит отменить подписку с середины периода.", "cancelled", "low", "billing", "web", "отмена,возврат", None, "Сергей Кузнецов", "s.kuznetsov@mail.ru", "", "", 4, "Отменено по политике возврата."),
    ("Тёмная тема в интерфейсе", "Пользователи просят dark mode.", "new", "low", "feature", "web", "ux,theme", 21, "ООО Дельта", "hello@delta.io", "", "", 3, "Низкий приоритет, высокий спрос."),
    ("Двухфакторная авторизация", "Включить 2FA (TOTP) для админ-ролей.", "in_progress", "high", "feature", "api", "security,2fa,compliance", 4, "Внутренний запрос", "", "", "", 2, "Compliance-требование."),
    ("Импорт контактов из CSV", "Массовый импорт клиентов из CSV с валидацией.", "new", "medium", "feature", "web", "импорт,csv", 12, "ООО Альфа", "office@alpha.ru", "", "", 3, "Полезно для онбординга крупных клиентов."),
    ("Ошибка 500 при смене статуса", "На канбане иногда 500 при перетаскивании.", "new", "urgent", "bug", "bot", "kanban,500,race", 1, "Ирина Соколова", "irina@example.com", "", "", 2, "Воспроизводится на конкурентных drag-drop."),
    ("Интеграция с почтой", "Автоматическое создание заявки из письма на support@.", "in_progress", "high", "feature", "api", "email,автоматизация", 8, "Внутренний запрос", "", "", "", 3, "Снизит ручную работу поддержки."),
    ("Отчёт по конверсии воронки", "Дашборд: конверсия между стадиями.", "new", "medium", "feature", "web", "аналитика,отчёт", 18, "Артём Волков", "artem@example.com", "", "", 4, "Нужен для управленческих решений."),
    ("Клиент ждёт договор 3 дня", "ОФЗ-клиент просит договор на подпись.", "new", "urgent", "support", "telegram", "договор,эскалация", 0, "ООО Омега", "legal@omega.ru", "+7 495 777-00-00", "legal@omega.ru", 4, "Просрочено обещание клиенту."),
    ("Бэкап базы раз в сутки", "Настроить ежедневный дамп SQLite.", "done", "high", "support", "manual", "backup,ops", None, "Внутренний запрос", "", "", "", 2, "Выполнено. Крон + ротация."),
    ("Не приходит SMS при регистрации", "Часть пользователей не получает SMS-код.", "new", "high", "bug", "web", "sms,провайдер", 3, "Иван Петров", "ivan@example.com", "+7 999 111-11-11", "ivan@example.com", 3, "Похоже на rate-limit провайдера."),
    ("Веб-форма обратной связи на сайт", "Сделать публичную форму, которая создаёт заявку.", "in_progress", "medium", "feature", "web", "форма,лид", 7, "Внутренний запрос", "", "", "", 3, "Канал лидогенерации."),
    ("Аудит прав доступа", "Проверить, что employee не видит админ-действия.", "done", "medium", "support", "api", "security,rbac", None, "Ирина Соколова", "irina@example.com", "", "", 2, "Выполнено. RBAC покрыт тестами."),
    ("Уведомление о просроченном SLA", "Если due_date прошёл — пуш в Telegram.", "new", "high", "feature", "bot", "sla,уведомления", 5, "Внутренний запрос", "", "", "", 2, "Замыкает SLA-контур."),
    ("Клиент просит удалить его данные", "GDPR/152-ФЗ: запрос на удаление персональных данных.", "in_progress", "urgent", "support", "web", "gdpr,удаление", 2, "Полина Юсупова", "p.yusupova@example.com", "+7 903 111-22-33", "p.yusupova@example.com", 4, "Юридический срок."),
    ("Оптимизация запросов дашборда", "Stats-эндпоинт делает 5 группировок подряд.", "new", "low", "bug", "api", "perf,dashboard", 20, "Внутренний запрос", "", "", "", 2, "Не критично на малых данных."),
    ("Шаблоны ответов в поддержке", "Библиотека макро-ответов для частых тикетов.", "new", "low", "feature", "manual", "поддержка,макро", 25, "Ольга Титова", "olga@example.com", "", "", 3, "Ускорит первую линию."),
    ("Сбой синхронизации с 1С ночью", "Ночной джоб упал на таймауте.", "new", "high", "bug", "telegram", "1c,джоб,таймаут", 1, "ООО Ромашка", "info@romashka.ru", "+7 900 111-22-33", "+7 900 111-22-33", 2, "Связано с задачей интеграции 1С."),
    ("Перевести интерфейс на i18n", "Подготовить локализацию ru/en.", "in_progress", "low", "feature", "web", "i18n,локализация", 30, "Внутренний запрос", "", "", "", 3, "Долгая задача."),
    ("Клиент оставил отзыв 1 звезда", "Негативный отзыв в каталоге.", "new", "medium", "support", "manual", "репутация,отзыв", 4, "Сергей Кузнецов", "s.kuznetsov@mail.ru", "", "", 4, "Репутационный риск."),
    ("Автотеги по тексту заявки", "Проставлять tags автоматически.", "done", "medium", "feature", "api", "ai,автотеги", None, "Внутренний запрос", "", "", "", 2, "Выполнено. Правило-based + LLM."),
]

_AMOUNT_BY_CATEGORY = {
    "sales": 320_000,
    "support": 45_000,
    "bug": 90_000,
    "feature": 140_000,
    "billing": 70_000,
    "general": 55_000,
    "other": 30_000,
}
_PRIORITY_MULTIPLIER = {"low": 0.5, "medium": 1.0, "high": 1.8, "urgent": 2.6}


def _amount_for(category: str, priority: str, index: int) -> float:
    base = _AMOUNT_BY_CATEGORY.get(category, 50_000)
    value = base * _PRIORITY_MULTIPLIER.get(priority, 1.0)
    # Deterministic spread so the demo does not look like round numbers.
    value = value * (0.85 + ((index * 37) % 31) / 100)
    return float(round(value, -2))


def _seed_applications(db: Session, users: list[User]) -> None:
    existing = db.scalar(select(func.count(Application.id))) or 0
    if existing >= len(SAMPLES):
        return

    admin = users[0]
    for index, row in enumerate(SAMPLES):
        (title, desc, status, priority, category, source, tags, due_delta, client, email, phone, contact, assign_index, ai) = row
        created = _dt(index % 40, index % 12)
        assigned = users[assign_index].id if assign_index < len(users) and status in ("in_progress", "done") else None
        closed_at = created + timedelta(days=2 + index % 5) if status in ("done", "cancelled") else None

        application = Application(
            title=title,
            description=desc,
            status=status,
            priority=priority,
            category=category,
            source=source,
            tags=tags,
            due_date=_date(due_delta) if due_delta is not None else None,
            amount=_amount_for(category, priority, index),
            ai_summary=ai if index % 2 == 0 else None,
            client_name=client,
            client_email=email,
            client_phone=phone,
            client_contact=contact,
            assigned_to_id=assigned,
            created_by_id=admin.id,
            created_at=created,
            updated_at=closed_at or created,
            closed_at=closed_at,
        )
        db.add(application)

    db.commit()

    applications = list(db.scalars(select(Application).order_by(Application.id).limit(10)).all())
    if applications and (db.scalar(select(func.count(Comment.id))) or 0) == 0:
        admin = users[0]
        dev = users[2] if len(users) > 2 else admin
        support = users[3] if len(users) > 3 else admin

        for index, application in enumerate(applications):
            db.add(
                Comment(
                    app_id=application.id,
                    user_id=admin.id,
                    text="Создал заявку, беру в работу.",
                    is_internal=False,
                    created_at=application.created_at,
                )
            )
            db.add(
                Comment(
                    app_id=application.id,
                    user_id=support.id,
                    text="Проверю со стороны поддержки, отпишусь.",
                    is_internal=True,
                    created_at=_dt(40 - index, 2),
                )
            )
            db.add(
                Task(
                    app_id=application.id,
                    user_id=dev.id,
                    title="Разобраться с заявкой: " + application.title[:60],
                    kind=["task", "call", "email", "meeting"][index % 4],
                    due_date=_date(3 + index),
                    is_done=(index % 3 == 0),
                )
            )
        db.commit()


def _get_or_create_company(db: Session, name: str, data: dict, owner_id: int) -> Company:
    company = db.scalar(select(Company).where(Company.name == name))
    if company:
        return company
    company = Company(
        name=name,
        domain=data.get("domain", ""),
        industry=data.get("industry", ""),
        size=data.get("size", ""),
        website=("https://" + data["domain"]) if data.get("domain") else "",
        address=data.get("address", ""),
        owner_id=owner_id,
    )
    db.add(company)
    db.flush()
    return company


def _get_or_create_contact(
    db: Session,
    full_name: str,
    email: str,
    phone: str,
    position: str,
    company_id: int | None,
    owner_id: int,
    is_primary: bool = True,
) -> Contact:
    existing = None
    if email:
        existing = db.scalar(select(Contact).where(Contact.email == email))
    if not existing:
        existing = db.scalar(select(Contact).where(Contact.full_name == full_name))
    if existing:
        if company_id and not existing.company_id:
            existing.company_id = company_id
        return existing

    contact = Contact(
        full_name=full_name,
        email=email,
        phone=phone,
        position=position,
        company_id=company_id,
        owner_id=owner_id,
        is_primary=is_primary,
    )
    db.add(contact)
    db.flush()
    return contact


def _seed_crm_entities(db: Session, users: list[User]) -> None:
    """Create companies/contacts from the client names and link every deal."""
    owner_id = users[0].id
    applications = list(db.scalars(select(Application).order_by(Application.id)).all())
    if not applications:
        return

    for application in applications:
        client = (application.client_name or "").strip()
        if not client:
            continue

        company_id = application.company_id
        contact_id = application.contact_id
        company_data = COMPANY_SEEDS.get(client)
        person_data = PERSON_SEEDS.get(client)

        if company_data:
            if not company_id:
                company = _get_or_create_company(db, client, company_data, owner_id)
                company_id = company.id
            if not contact_id:
                first = company_data.get("contacts", [])
                if first:
                    full_name, position, email, phone = first[0]
                    contact = _get_or_create_contact(
                        db, full_name, email or application.client_email, phone or application.client_phone,
                        position, company_id, owner_id,
                    )
                    contact_id = contact.id
                else:
                    fallback_name = application.client_contact or client
                    if "@" not in fallback_name and fallback_name:
                        contact = _get_or_create_contact(
                            db, fallback_name, application.client_email, application.client_phone,
                            "", company_id, owner_id,
                        )
                        contact_id = contact.id
        elif person_data:
            if not company_id and person_data.get("company"):
                company = _get_or_create_company(db, person_data["company"], person_data, owner_id)
                company_id = company.id
            if not contact_id:
                contact = _get_or_create_contact(
                    db, client, application.client_email or application.client_contact,
                    application.client_phone, person_data.get("position", ""), company_id, owner_id,
                )
                contact_id = contact.id
        else:
            if not company_id:
                company = _get_or_create_company(
                    db,
                    client,
                    {"domain": (application.client_email or "").split("@")[-1] if "@" in (application.client_email or "") else ""},
                    owner_id,
                )
                company_id = company.id
            if not contact_id:
                contact = _get_or_create_contact(
                    db, application.client_contact or client, application.client_email,
                    application.client_phone, "", company_id, owner_id,
                )
                contact_id = contact.id

        application.company_id = company_id
        application.contact_id = contact_id
        if not application.amount:
            application.amount = _amount_for(application.category, application.priority, application.id)
        if application.status in ("done", "cancelled") and not application.closed_at:
            application.closed_at = application.updated_at or application.created_at

    db.commit()


def _seed_logs(db: Session, users: list[User]) -> None:
    existing = db.scalar(select(func.count(ActionLog.id))) or 0
    if existing > 0:
        return

    admin = users[0]
    applications = list(db.scalars(select(Application).order_by(Application.id)).all())
    logs = []
    for application in applications[:24]:
        logs.append(
            ActionLog(
                user_id=admin.id,
                action="create",
                entity_type="application",
                entity_id=application.id,
                details=application.title,
                created_at=application.created_at,
            )
        )
        if application.status in ("in_progress", "done", "cancelled"):
            logs.append(
                ActionLog(
                    user_id=admin.id,
                    action="status_change",
                    entity_type="application",
                    entity_id=application.id,
                    details="new -> " + application.status,
                    created_at=application.updated_at,
                )
            )
        if application.ai_summary:
            logs.append(
                ActionLog(
                    user_id=admin.id,
                    action="ai_analyze",
                    entity_type="application",
                    entity_id=application.id,
                    details="AI analysis",
                    created_at=application.updated_at,
                )
            )

    db.add_all(logs)
    db.commit()


def seed_initial(db: Session) -> None:
    users = _seed_users(db)
    before = db.scalar(select(func.count(Application.id))) or 0
    _seed_applications(db, users)
    _seed_crm_entities(db, users)
    _seed_logs(db, users)
    after = db.scalar(select(func.count(Application.id))) or 0
    comments = db.scalar(select(func.count(Comment.id))) or 0
    tasks = db.scalar(select(func.count(Task.id))) or 0
    companies = db.scalar(select(func.count(Company.id))) or 0
    contacts = db.scalar(select(func.count(Contact.id))) or 0
    if after > before:
        print(
            "Seed: users=" + str(len(users)) + " apps=" + str(after)
            + " companies=" + str(companies) + " contacts=" + str(contacts)
            + " comments=" + str(comments) + " tasks=" + str(tasks)
        )
    else:
        print(
            "Seed: готово apps=" + str(after) + " companies=" + str(companies)
            + " contacts=" + str(contacts) + " comments=" + str(comments) + " tasks=" + str(tasks)
        )
