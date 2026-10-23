# Orbit CRM

![Orbit CRM](.assets/banner.svg)

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-D71F00)
![aiogram](https://img.shields.io/badge/aiogram-3.x-2CA5E0)
![License](https://img.shields.io/badge/license-MIT-green)

Корпоративная CRM для отдела продаж и сервисных команд: клиенты, компании, контакты, заявки (applications), задачи, роли и аудит. Встроенный AI-ассистент с RAG по базе знаний и Telegram-бот для работы вне офиса. Эволюция проекта [mini-crm](https://github.com/nwl01234/mini-crm) — добавлены многопользовательский RBAC, коммерческая структура (компании/контакты), rate-limiting и уведомления.

## Возможности

- **Клиентская база** — компании, контакты, привязка заявок к клиентам
- **Заявки и задачи** — жизненный цикл заявки, назначение сотрудников, статусы
- **Роли и доступ (RBAC)** — admin / manager / employee с разграничением прав
- **AI-ассистент** — ответы на вопросы по базе знаний (RAG), подсказки по заявкам, OpenAI-совместимый API или локальная Ollama
- **Telegram-бот** — приём заявок от клиентов, уведомления сотрудникам, статус в реальном времени
- **Аудит** — журнал действий «кто / что / когда / почему»
- **Уведомления** — in-app + Telegram, сервис notification_service
- **Безопасность** — JWT (cookie + Bearer), passlib/bcrypt, rate limiting

## Архитектура

```mermaid
flowchart LR
    UI[Серверные шаблоны<br/>Jinja2 + Tailwind + Alpine.js] --> API[FastAPI routers]
    TG[Telegram-бот<br/>aiogram 3] --> API
    API --> SVC[Сервисы: CRM, AI, Stats,<br/>Notifications, RateLimit, Audit]
    SVC --> DB[(SQLite / SQLAlchemy 2.0)]
    SVC --> LLM[OpenAI-совместимый API / Ollama]
```

```
app/
├── main.py            # точка входа FastAPI
├── routers/           # auth, dashboard, companies, contacts,
│                      # applications, users, ai, bot, logs, profile
├── services/          # ai_service, crm, stats, notification_service,
│                      # rate_limit, logging_service, seed
├── bot/               # Telegram-бот (aiogram 3)
└── models.py / schemas.py / security.py / deps.py
```

## Быстрый старт

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
cp .env.example .env            # заполнить переменные
python run.py                   # http://localhost:8000
```

`.env.example` содержит все переменные: `BOT_TOKEN`, `OPENAI_API_KEY` / `OLLAMA_URL` и т.д.

**Демо-аккаунты** (создаются при первом запуске через seed):

| Логин | Пароль | Роль |
|---|---|---|
| `admin` | `admin123` | администратор |
| `manager` | `manager123` | менеджер |
| `dev1` | `emp12345` | сотрудник |

## Стек

| Слой | Технологии |
|---|---|
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2.0, SQLite, pydantic |
| Frontend | Jinja2, Tailwind CSS, Alpine.js (без сборки — статика отдаётся из `static/`) |
| Auth | JWT (HttpOnly cookie + Bearer), bcrypt |
| AI | OpenAI-совместимый API, Ollama, RAG-контекст из базы знаний |
| Бот | aiogram 3.x, FSM |
| Тесты | pytest |

## Roadmap

- [ ] PostgreSQL-профиль
- [ ] Файлы/вложения в заявках
- [ ] REST API для мобильных клиентов
- [ ] Воронка продаж (kanban)

## Скриншоты

| | |
|---|---|
| ![Вход](.assets/screens/01.png) | ![Дашборд](.assets/screens/02.png) |
| ![Заявки](.assets/screens/03.png) | ![Карточка заявки](.assets/screens/04.png) |
| ![Клиенты](.assets/screens/05.png) | ![AI-ассистент](.assets/screens/06.png) |
| ![Канбан](.assets/screens/07.png) | |

---
Часть портфолио: [mini-crm](https://github.com/nwl01234/mini-crm) → **orbit-crm** → [pulse-crm](https://github.com/nwl01234/pulse-crm) · [business-flow-automator](https://github.com/nwl01234/business-flow-automator)
