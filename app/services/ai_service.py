import asyncio
import hashlib
import json
import logging
import math
import re
from datetime import datetime
from typing import Any, Optional

import httpx
from sqlalchemy import delete, desc, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Application, ApplicationVector, Task

logger = logging.getLogger(__name__)

PRIORITIES = ["low", "medium", "high", "urgent"]
CATEGORIES = ["general", "sales", "support", "bug", "feature", "billing", "other"]

URGENT_WORDS = ["срочно", "urgent", "критич", "авария", "лежит", "упал", "500", "не работает", "ошибка", "сбой", "потеря", "не проходит", "эскалация"]
HIGH_WORDS = ["клиент", "оплата", "счет", "счёт", "платеж", "интеграция", "дедлайн", "подписка", "тариф", "договор"]
LOW_WORDS = ["хочу", "предложение", "идея", "мелкий", "когда-нибудь", "тёмная", "темная"]

CATEGORY_KEYWORDS = {
    "bug": ["ошибка", "не работает", "баг", "500", "упал", "сбой", "не доходит", "лежит", "таймаут", "не приходит"],
    "feature": ["хочу", "добавить", "функция", "кнопка", "возможность", "сделать", "тёмная", "темная", "экспорт", "импорт", "интеграц", "шаблон", "i18n", "2fa", "отчёт", "отчет"],
    "support": ["помощь", "консультация", "настроить", "вопрос", "объясни", "как пользоваться", "письма", "sms", "отзыв", "договор", "gdpr", "удаление"],
    "billing": ["тариф", "оплата", "подписка", "счет", "счёт", "платеж", "платёж", "скидка", "деньги", "возврат", "отмена"],
    "sales": ["интеграция", "купить", "сделка", "коммерческое", "кп", "продать", "партнер", "1с", "erp", "лид", "конверсия"],
}

TAG_RULES = {
    "1c": ["1с", "1c"], "оплата": ["оплата", "платеж", "сбп", "карт"], "прод": ["прод", "продакшн", "боевой"],
    "security": ["2fa", "security", "rbac", "аудит прав"], "gdpr": ["gdpr", "удалить данные"],
    "perf": ["ускор", "грузится", "оптимизац"], "email": ["письм", "smtp", "email"],
    "sla": ["sla", "просроч", "срок", "эскалац"], "ux": ["ux", "тема", "интерфейс"],
    "бот": ["бот", "telegram", "уведомлен"],
}

SYNONYMS = {
    "деньги": ["оплата", "счёт", "счет", "платеж", "платёж", "тариф", "подписка", "billing", "возврат", "скидка"],
    "сломалось": ["ошибка", "не работает", "баг", "сбой", "упал", "bug", "500", "не приходит", "таймаут"],
    "срочно": ["urgent", "критично", "авария", "лежит", "эскалация"],
    "хотелка": ["feature", "добавить", "функция", "кнопка", "идея", "хочу"],
    "клиент": ["customer", "заказчик"],
    "просрочено": ["overdue", "дедлайн", "срок"],
}


def _normalize(v):
    n = math.sqrt(sum(x * x for x in v))
    return v if n == 0 else [x / n for x in v]

def _cosine(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))

def _tokens(t):
    return [x for x in re.findall(r"[a-zA-Zа-яА-ЯёЁ0-9]+", t.lower()) if len(x) > 2]

def _expand(tokens):
    out = list(tokens)
    for tok in tokens:
        for k, v in SYNONYMS.items():
            if tok == k or tok in v:
                out.append(k)
                out.extend(v)
    return list(dict.fromkeys(out))


class AIService:
    def __init__(self):
        self._llm_ok: Optional[bool] = None

    def _headers(self):
        h = {"Content-Type": "application/json"}
        if settings.AI_API_KEY:
            h["Authorization"] = "Bearer " + settings.AI_API_KEY
        return h

    def _mark_down(self, exc):
        if self._llm_ok is not False:
            self._llm_ok = False
            logger.info("LLM недоступна (%s). Работаю в rule-based режиме.", exc)

    async def _post_json(self, url, payload):
        if self._llm_ok is False:
            return None
        try:
            async with httpx.AsyncClient(timeout=settings.AI_TIMEOUT) as client:
                r = await client.post(url, json=payload, headers=self._headers())
                r.raise_for_status()
                self._llm_ok = True
                return r.json()
        except Exception as e:
            self._mark_down(e)
            return None

    async def embed_text(self, text):
        if not settings.ai_enabled or self._llm_ok is False:
            return None
        data = await self._post_json(settings.AI_BASE_URL.rstrip("/") + "/embeddings",
                                      {"model": settings.AI_EMBED_MODEL, "input": text})
        if not data:
            return None
        items = data.get("data") or []
        if not items:
            return None
        emb = items[0].get("embedding")
        if not emb:
            return None
        try:
            return _normalize([float(v) for v in emb])
        except Exception:
            return None

    async def _chat(self, messages, temperature):
        if not settings.ai_enabled or self._llm_ok is False:
            return None
        data = await self._post_json(settings.AI_BASE_URL.rstrip("/") + "/chat/completions",
                                      {"model": settings.AI_MODEL, "messages": messages, "temperature": temperature})
        if not data:
            return None
        try:
            return data["choices"][0]["message"]["content"]
        except Exception:
            return None

    def _app_text(self, app):
        return "\n".join([p for p in [app.title or "", app.description or "", app.client_name or "",
                                       app.tags or "", app.category or "", app.status or "",
                                       app.priority or "", app.ai_summary or ""] if p])

    def _hash(self, t):
        return hashlib.sha256(t.encode()).hexdigest()

    async def index_application(self, db, app):
        text = self._app_text(app)
        vec = await self.embed_text(text)
        if vec is None:
            return False
        h = self._hash(text)
        row = db.get(ApplicationVector, app.id)
        if row and row.text_hash == h:
            return True
        if row:
            row.vector, row.text_hash = vec, h
        else:
            db.add(ApplicationVector(app_id=app.id, text_hash=h, vector=vec))
        db.commit()
        return True

    async def delete_application_vector(self, db, app_id):
        db.execute(delete(ApplicationVector).where(ApplicationVector.app_id == app_id))
        db.commit()

    async def reindex_all(self, db):
        if not settings.ai_enabled:
            return 0
        apps = list(db.scalars(select(Application).order_by(desc(Application.created_at))).all())
        results = []

        # Bounded concurrency keeps local Ollama responsive while avoiding a
        # 28 × timeout sequential crawl on a cold start.
        semaphore = asyncio.Semaphore(4)

        async def index_one(application):
            async with semaphore:
                return await self.index_application(db, application)

        for chunk_start in range(0, len(apps), 4):
            chunk = apps[chunk_start:chunk_start + 4]
            results.extend(await asyncio.gather(*(index_one(a) for a in chunk)))
            if self._llm_ok is False:
                break
        return sum(1 for value in results if value)

    def _lexical(self, q, app):
        tokens = _expand(_tokens(q))
        if not tokens:
            return 0
        title = (app.title or "").lower()
        desc = (app.description or "").lower()
        client = (app.client_name or "").lower()
        meta = " ".join([app.category or "", app.status or "", app.priority or "", app.tags or "", app.ai_summary or ""]).lower()
        s = 0
        for t in tokens:
            if t in title: s += 5
            if t in desc: s += 3
            if t in client: s += 3
            if t in meta: s += 2
        return s

    async def retrieve(self, db, q, limit=10):
        apps = list(db.scalars(select(Application).order_by(desc(Application.created_at)).limit(400)).all())
        if not apps:
            return []
        qv = await self.embed_text(q)
        ids = [a.id for a in apps]
        rows = db.scalars(select(ApplicationVector).where(ApplicationVector.app_id.in_(ids))).all()
        vmap = {r.app_id: r.vector for r in rows}
        scored = []
        for app in apps:
            lex = float(self._lexical(q, app))
            sem = None
            if qv:
                vec = vmap.get(app.id)
                if not vec:
                    if await self.index_application(db, app):
                        rr = db.get(ApplicationVector, app.id)
                        vec = rr.vector if rr else None
                if vec:
                    sem = _cosine(qv, vec)
            score = (sem * 12.0 + lex * 0.12) if sem is not None else lex
            if score > 0:
                scored.append((score, app))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [a for _, a in scored[:limit]]

    def _today(self):
        return datetime.utcnow().strftime("%Y-%m-%d")

    def _fmt_app(self, app):
        due = (" (срок " + app.due_date + ")") if app.due_date else ""
        return f"• #{app.id} «{app.title}» — {app.client_name or 'без клиента'}, {self._status_ru(app.status)}, {self._priority_ru(app.priority)}{due}"

    def _status_ru(self, s):
        return {"new": "новая", "in_progress": "в работе", "done": "выполнена", "cancelled": "отменена"}.get(s, s)

    def _priority_ru(self, p):
        return {"low": "низкий", "medium": "средний", "high": "высокий", "urgent": "срочный"}.get(p, p)

    def _count(self, apps, field, value):
        return sum(1 for a in apps if str(getattr(a, field, "") or "") == value)

    def _human_answer(self, q, apps, relevant, db=None):
        """Возвращает человеческий ответ на типичные вопросы."""
        ql = q.lower()
        open_apps = [a for a in apps if a.status in ("new", "in_progress")]

        def money(value):
            return f"{float(value or 0):,.0f}".replace(",", " ") + " ₽"

        # --- БЕЗ ОТВЕТСТВЕННОГО ---
        if any(w in ql for w in ["без ответ", "не назнач", "unassigned", "без менеджера"]):
            unassigned = [a for a in open_apps if not a.assigned_to_id]
            if not unassigned:
                return "Все открытые сделки назначены на сотрудников. ✅"
            lines = [f"Без ответственного {len(unassigned)} открытых сделок:"]
            for a in unassigned[:8]:
                lines.append(self._fmt_app(a))
            lines.append(f"Сумма: {money(sum(a.amount or 0 for a in unassigned))}.")
            return "\n".join(lines)

        # --- ТОП КЛИЕНТОВ ---
        if "топ клиент" in ql or ("клиент" in ql and any(w in ql for w in ["кто", "больше", "принос", "лучш"])):
            done = [a for a in apps if a.status == "done" and a.client_name and a.client_name != "Внутренний запрос"]
            source = done or [a for a in apps if a.client_name and a.client_name != "Внутренний запрос" and a.status != "cancelled"]
            totals = {}
            for a in source:
                item = totals.setdefault(a.client_name, {"amount": 0.0, "count": 0})
                item["amount"] += float(a.amount or 0)
                item["count"] += 1
            ranked = sorted(totals.items(), key=lambda item: item[1]["amount"], reverse=True)[:5]
            if not ranked:
                return "В сделках пока не заполнены клиенты — не из чего собрать рейтинг."
            title = "Топ клиентов по закрытым сделкам:" if done else "Топ клиентов по сумме сделок:"
            lines = [title]
            for name, item in ranked:
                lines.append(f"• {name} — {money(item['amount'])}, сделок: {item['count']}")
            return "\n".join(lines)

        # --- СРОЧНЫЕ ---
        if any(w in ql for w in ["срочн", "urgent", "горящ", "горит"]):
            urgent = [a for a in open_apps if a.priority == "urgent"]
            if not urgent:
                return "Срочных открытых заявок сейчас нет. 🎉"
            lines = [f"Сейчас {len(urgent)} срочных заявок, требующих внимания:"]
            for a in urgent[:7]:
                lines.append(self._fmt_app(a))
            if len(urgent) > 7:
                lines.append(f"...и ещё {len(urgent) - 7}.")
            return "\n".join(lines)

        # --- ПРОСРОЧЕНО ---
        if any(w in ql for w in ["просроч", "overdue", "дедлайн", "срок"]):
            today = self._today()
            overdue = [a for a in apps if a.due_date and a.due_date < today and a.status not in ("done", "cancelled")]
            tasks = []
            if db is not None:
                tasks = list(
                    db.scalars(
                        select(Task)
                        .where(Task.due_date.is_not(None), Task.due_date < today, Task.is_done.is_(False))
                        .order_by(Task.due_date)
                        .limit(6)
                    ).all()
                )
            if not overdue and not tasks:
                return "Просроченных заявок и задач нет — всё в порядке. ✅"
            lines = []
            if overdue:
                lines.append(f"⏰ Просрочено {len(overdue)} заявок:")
                for a in overdue[:8]:
                    lines.append(self._fmt_app(a))
            if tasks:
                lines.append(f"Просроченные задачи ({len(tasks)}):")
                for task in tasks:
                    lines.append(f"• «{task.title}» — срок {task.due_date}")
            return "\n".join(lines)

        # --- В РАБОТЕ ---
        if "работ" in ql or "in_progress" in ql or "активн" in ql:
            inw = [a for a in apps if a.status == "in_progress"]
            if not inw:
                return "Сейчас нет заявок в работе."
            total = sum(a.amount or 0 for a in inw)
            lines = [f"В работе {len(inw)} заявок на {money(total)}:"]
            for a in inw[:8]:
                lines.append(self._fmt_app(a))
            return "\n".join(lines)

        # --- НОВЫЕ ---
        if "нов" in ql and ("заяв" in ql or "new" in ql):
            nw = [a for a in apps if a.status == "new"]
            if not nw:
                return "Новых заявок нет."
            lines = [f"Новых заявок {len(nw)}:"]
            for a in nw[:8]:
                lines.append(self._fmt_app(a))
            return "\n".join(lines)

        # --- ВЫПОЛНЕНО / ЗАКРЫТО ---
        if "выполн" in ql or "закрыт" in ql or "done" in ql:
            dn = [a for a in apps if a.status == "done"]
            return f"Выполнено {len(dn)} заявок." if dn else "Пока нет выполненных заявок."

        # --- ОТМЕНЕНО ---
        if "отмен" in ql or "cancelled" in ql:
            cn = [a for a in apps if a.status == "cancelled"]
            return f"Отменено {len(cn)} заявок."

        # --- БАГИ ---
        if "баг" in ql or "bug" in ql or ("ошибк" in ql):
            bugs = [a for a in apps if a.category == "bug"]
            if not bugs:
                return "Заявок категории bug сейчас нет."
            lines = [f"Найдено {len(bugs)} заявок категории bug:"]
            for a in bugs[:8]:
                lines.append(self._fmt_app(a))
            return "\n".join(lines)

        # --- ДЕНЬГИ / ОПЛАТА ---
        if any(w in ql for w in ["деньг", "оплат", "платеж", "платёж", "тариф", "скидк", "billing"]):
            billing = [a for a in apps if a.category == "billing" or any(w in (a.title + " " + a.description).lower() for w in ["оплат", "платеж", "платёж", "счёт", "счет", "тариф", "скидк", "деньг"])]
            if not billing:
                return "Заявок про деньги/оплату не нашёл."
            lines = [f"По теме денег/оплаты {len(billing)} заявок:"]
            for a in billing[:8]:
                lines.append(self._fmt_app(a))
            return "\n".join(lines)

        # --- СЛОМАЛОСЬ ---
        if any(w in ql for w in ["сломал", "не работает", "падает", "упал", "ошибк"]):
            broken = [a for a in apps if a.category == "bug" or any(w in (a.title + " " + a.description).lower() for w in ["ошибк", "500", "не работает", "упал", "сбой"])]
            if not broken:
                return "Похоже, ничего не сломано — баг-заявок нет."
            lines = [f"Нашёл {len(broken)} заявок о проблемах:"]
            for a in broken[:8]:
                lines.append(self._fmt_app(a))
            return "\n".join(lines)

        # --- ХОТЕЛКИ / ФИЧИ ---
        if any(w in ql for w in ["хотел", "фич", "функци", "feature", "добавить"]):
            feats = [a for a in apps if a.category == "feature"]
            if not feats:
                return "Заявок с хотелками сейчас нет."
            lines = [f"Запросов на новые функции {len(feats)}:"]
            for a in feats[:8]:
                lines.append(self._fmt_app(a))
            return "\n".join(lines)

        # --- ВОРОНКА / СВОДКА ---
        if any(w in ql for w in ["воронк", "сводк", "конверси", "pipeline"]):
            from datetime import timedelta

            scope = apps
            label = "в базе"
            if "7" in ql or "недел" in ql:
                cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
                scope = [a for a in apps if a.created_at.isoformat() >= cutoff]
                label = "за 7 дней"
            elif "30" in ql or "месяц" in ql:
                cutoff = (datetime.utcnow() - timedelta(days=30)).isoformat()
                scope = [a for a in apps if a.created_at.isoformat() >= cutoff]
                label = "за 30 дней"
            pipeline = sum(a.amount or 0 for a in scope if a.status in ("new", "in_progress"))
            won = sum(a.amount or 0 for a in scope if a.status == "done")
            new_count = self._count(scope, "status", "new")
            work_count = self._count(scope, "status", "in_progress")
            done_count = self._count(scope, "status", "done")
            lost_count = self._count(scope, "status", "cancelled")
            return (
                f"Сводка {label}: всего {len(scope)} сделок — новых {new_count}, в работе {work_count}, "
                f"выполнено {done_count}, отменено {lost_count}. "
                f"Открытая воронка: {money(pipeline)}. Закрыто успешно: {money(won)}."
            )

        # --- ЗА НЕДЕЛЮ / МЕСЯЦ ---
        if ("недел" in ql or "7 дней" in ql or "week" in ql):
            from datetime import timedelta
            cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
            recent = [a for a in apps if a.created_at.isoformat() >= cutoff]
            return f"За последние 7 дней создано {len(recent)} заявок на {money(sum(a.amount or 0 for a in recent))}."
        if ("месяц" in ql or "30 дней" in ql):
            from datetime import timedelta
            cutoff = (datetime.utcnow() - timedelta(days=30)).isoformat()
            recent = [a for a in apps if a.created_at.isoformat() >= cutoff]
            return f"За последние 30 дней создано {len(recent)} заявок на {money(sum(a.amount or 0 for a in recent))}."

        # --- ВСЕГО ---
        if "всего" in ql or "сколько всего" in ql or "total" in ql:
            return f"Всего в базе {len(apps)} заявок: новых {self._count(apps,'status','new')}, в работе {self._count(apps,'status','in_progress')}, выполнено {self._count(apps,'status','done')}, отменено {self._count(apps,'status','cancelled')}."

        # --- ПО КЛИЕНТУ ---
        legal_prefixes = ("ооо", "оао", "зао", "пао", "ао", "ип", "llc", "ltd", "inc")
        for a in apps:
            raw = (a.client_name or "").strip()
            if not raw:
                continue
            key = raw.lower()
            words = [word for word in key.replace("«", " ").replace("»", " ").split() if word not in legal_prefixes]
            candidates = [key] + words
            if any(len(candidate) >= 3 and candidate in ql for candidate in candidates):
                matched = [x for x in apps if (x.client_name or "").lower().strip() == key]
                if not matched:
                    return f"По клиенту «{raw}» заявок не найдено."
                lines = [f"По клиенту «{raw}» {len(matched)} заявок:"]
                for x in matched[:10]:
                    lines.append(self._fmt_app(x))
                return "\n".join(lines)

        # --- ПО ТЕГУ / КАТЕГОРИИ (fallback через relevant) ---
        if relevant:
            lines = [f"Нашёл {len(relevant)} похожих заявок по вашему вопросу:"]
            for a in relevant[:8]:
                lines.append(self._fmt_app(a))
            return "\n".join(lines)

        return "Не нашёл заявок по вашему вопросу. Попробуйте спросить иначе: назовите клиента, статус («срочные», «в работе», «просроченные») или категорию («баги», «оплата», «фичи»)."

    async def rag_chat(self, db, q):
        apps = list(db.scalars(select(Application).order_by(desc(Application.created_at)).limit(500)).all())
        relevant = await self.retrieve(db, q, limit=10)

        if settings.ai_enabled and self._llm_ok is not False:
            ctx_lines = []
            for a in relevant:
                d = (a.description or "").strip().replace("\n", " ")
                if len(d) > 240:
                    d = d[:237] + "..."
                ctx_lines.append(f"#{a.id} status={a.status} priority={a.priority} category={a.category} client={a.client_name or '-'} title={a.title} desc={d}")
            ctx = "\n".join(ctx_lines) if ctx_lines else "Нет заявок."
            msgs = [
                {"role": "system", "content": "Ты аналитик CRM. Отвечай на русском, кратко и по делу. Указывай номера #id. Если ответа нет — скажи."},
                {"role": "user", "content": "Контекст заявок:\n" + ctx + "\n\nВопрос:\n" + q},
            ]
            ans = await self._chat(msgs, 0.25)
            if ans and ans.strip():
                return ans.strip()

        return self._human_answer(q, apps, relevant, db)

    def _parse_json(self, raw):
        if not raw:
            return {}
        i, j = raw.find("{"), raw.rfind("}")
        if i == -1 or j <= i:
            return {}
        try:
            return json.loads(raw[i:j + 1])
        except Exception:
            return {}

    def _rule_priority(self, *texts):
        t = " ".join(texts).lower()
        if any(w in t for w in URGENT_WORDS):
            return "urgent"
        if any(w in t for w in HIGH_WORDS):
            return "high"
        if any(w in t for w in LOW_WORDS):
            return "low"
        return "medium"

    def _rule_category(self, *texts):
        t = " ".join(texts).lower()
        best, bs = "general", 0
        for cat, words in CATEGORY_KEYWORDS.items():
            sc = sum(1 for w in words if w in t)
            if sc > bs:
                best, bs = cat, sc
        return best

    def suggest_tags(self, *texts):
        t = " ".join(texts).lower()
        tags = []
        for tag, words in TAG_RULES.items():
            if any(w in t for w in words):
                tags.append(tag)
        return ",".join(tags[:5])

    async def analyze_application(self, title, description, client_name=""):
        if settings.ai_enabled and self._llm_ok is not False:
            prompt = "\n".join([
                "Проанализируй заявку. Верни ТОЛЬКО JSON без markdown:",
                '{"summary": "2-3 предложения о сути заявки", "priority": "low|medium|high|urgent"}',
                f"Заголовок: {title}",
                f"Клиент: {client_name or 'не указан'}",
                f"Описание: {description}",
            ])
            raw = await self._chat([{"role": "system", "content": "Отвечай строго JSON."}, {"role": "user", "content": prompt}], 0.2)
            p = self._parse_json(raw or "")
            summary = str(p.get("summary") or "").strip()
            prio = str(p.get("priority") or "medium").lower()
            if summary and prio in PRIORITIES:
                return {"summary": summary, "priority": prio}

        cat = self._rule_category(title, description)
        prio = self._rule_priority(title, description, client_name)
        short = (description or "").strip().replace("\n", " ")
        if len(short) > 200:
            short = short[:197] + "..."
        summary = f"Анализ заявки «{title}». Категория: {cat}, приоритет: {prio}. "
        if client_name:
            summary += f"Клиент: {client_name}. "
        if short:
            summary += f"Суть: {short}"
        return {"summary": summary, "priority": prio}

    async def categorize(self, title, description):
        if settings.ai_enabled and self._llm_ok is not False:
            prompt = "\n".join([
                "Определи категорию. Допустимо: " + ", ".join(CATEGORIES) + ".",
                f"Заголовок: {title}",
                f"Описание: {description}",
                "Ответ: ОДНО слово.",
            ])
            raw = await self._chat([{"role": "system", "content": "Одно слово."}, {"role": "user", "content": prompt}], 0.0)
            c = (raw or "").strip().lower()
            for cat in CATEGORIES:
                if cat in c:
                    return cat
        return self._rule_category(title, description)


ai_service = AIService()
