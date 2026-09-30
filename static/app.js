const STATUS_LABELS = { new: "Новая", in_progress: "В работе", done: "Выполнена", cancelled: "Отменена" };
const PRIORITY_LABELS = { low: "Низкий", medium: "Средний", high: "Высокий", urgent: "Срочный" };
const CATEGORY_LABELS = {
  general: "Общее",
  sales: "Продажи",
  support: "Поддержка",
  bug: "Баг",
  feature: "Фича",
  billing: "Биллинг",
  other: "Другое",
};
const SOURCE_LABELS = { web: "Веб", telegram: "Telegram", api: "API", bot: "Бот", manual: "Вручную" };
const TASK_KIND_LABELS = { task: "Задача", call: "Звонок", meeting: "Встреча", email: "Письмо" };

const moneyFormatter = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });

function statusLabel(value) { return STATUS_LABELS[value] || value || ""; }
function priorityLabel(value) { return PRIORITY_LABELS[value] || value || ""; }
function categoryLabel(value) { return CATEGORY_LABELS[value] || value || ""; }
function sourceLabel(value) { return SOURCE_LABELS[value] || value || ""; }
function taskKindLabel(value) { return TASK_KIND_LABELS[value] || value || ""; }

function statusChip(value) {
  return { new: "status-new", in_progress: "status-progress", done: "status-done", cancelled: "status-cancelled" }[value] || "chip-neutral";
}
function priorityChip(value) {
  return { low: "priority-low", medium: "priority-medium", high: "priority-high", urgent: "priority-urgent" }[value] || "chip-neutral";
}

function todayIso() {
  const now = new Date();
  const offset = now.getTimezoneOffset() * 60000;
  return new Date(now.getTime() - offset).toISOString().slice(0, 10);
}

function isOverdue(app) {
  return !!(
    app &&
    app.due_date &&
    app.due_date < todayIso() &&
    app.status !== "done" &&
    app.status !== "cancelled"
  );
}

function formatMoney(value) {
  const number = Number(value || 0);
  if (!Number.isFinite(number)) return "—";
  return moneyFormatter.format(number) + " ₽";
}

function formatDate(value, withTime) {
  if (!value) return "—";
  const date = typeof value === "string" ? new Date(value.length <= 10 ? value + "T00:00:00" : value) : value;
  if (Number.isNaN(date.getTime())) return String(value);
  const formatted = date.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric" });
  if (!withTime) return formatted;
  return formatted + " " + date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

function relativeTime(value) {
  if (!value) return "";
  const date = typeof value === "string" ? new Date(value.endsWith("Z") ? value : value + "Z") : value;
  if (Number.isNaN(date.getTime())) return String(value);
  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return "только что";
  if (seconds < 3600) return Math.floor(seconds / 60) + " мин назад";
  if (seconds < 86400) return Math.floor(seconds / 3600) + " ч назад";
  if (seconds < 604800) return Math.floor(seconds / 86400) + " дн назад";
  return formatDate(date);
}

function initials(value) {
  const parts = String(value || "?").trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  return (parts[0][0] + (parts[1] ? parts[1][0] : "")).toUpperCase();
}

function daysUntil(value) {
  if (!value) return null;
  const target = new Date(value + "T00:00:00");
  const today = new Date(todayIso() + "T00:00:00");
  return Math.round((target - today) / 86400000);
}

function dueLabel(value) {
  if (!value) return "";
  const days = daysUntil(value);
  if (days === null) return value;
  if (days === 0) return "Сегодня";
  if (days === 1) return "Завтра";
  if (days === -1) return "Вчера";
  if (days < 0) return "Просрочено на " + Math.abs(days) + " дн";
  if (days <= 7) return "Через " + days + " дн";
  return formatDate(value);
}

window.statusLabel = statusLabel;
window.priorityLabel = priorityLabel;
window.categoryLabel = categoryLabel;
window.sourceLabel = sourceLabel;
window.taskKindLabel = taskKindLabel;
window.statusChip = statusChip;
window.priorityChip = priorityChip;
window.todayIso = todayIso;
window.isOverdue = isOverdue;
window.formatMoney = formatMoney;
window.formatDate = formatDate;
window.relativeTime = relativeTime;
function plural(value, one, few, many) {
  const number = Math.abs(Number(value) || 0) % 100;
  const tail = number % 10;
  if (number >= 11 && number <= 19) return many;
  if (tail === 1) return one;
  if (tail >= 2 && tail <= 4) return few;
  return many;
}

window.initials = initials;
window.plural = plural;
window.daysUntil = daysUntil;
window.dueLabel = dueLabel;

window.apiJson = async function (path, options) {
  const init = Object.assign({ credentials: "include", headers: {} }, options || {});
  if (init.body && typeof init.body === "string" && !init.headers["Content-Type"]) {
    init.headers["Content-Type"] = "application/json";
  }
  let response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new Error("Сервер недоступен. Проверьте соединение.");
  }

  if (response.status === 401) {
    window.location.href = "/login";
    throw new Error("Требуется авторизация");
  }

  const text = await response.text();
  let data = {};
  if (text) {
    try { data = JSON.parse(text); } catch { data = { detail: text }; }
  }
  if (!response.ok) {
    let detail = data.detail || data.message || "Ошибка запроса";
    if (Array.isArray(detail)) {
      detail = detail.map((item) => item.msg || JSON.stringify(item)).join("; ");
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
};

window.toast = function (message, type) {
  window.dispatchEvent(new CustomEvent("toast:push", { detail: { message, type: type || "success" } }));
};

window.confirmAction = function (options) {
  return new Promise((resolve) => {
    window.dispatchEvent(new CustomEvent("confirm:request", { detail: { ...options, resolve } }));
  });
};

window.copyText = async function (text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("Скопировано");
  } catch {
    toast("Не удалось скопировать", "error");
  }
};

function appShell() {
  return {
    mobileOpen: false,
    notifOpen: false,
    userMenuOpen: false,
    cmdkOpen: false,
    cmdkQuery: "",
    cmdkResults: [],
    cmdkIndex: 0,
    cmdkLoading: false,
    notifications: [],
    toasts: [],
    confirmOpen: false,
    confirmState: { title: "", text: "", confirmText: "Подтвердить", danger: false, resolve: null },

    init() {
      window.addEventListener("toast:push", (event) => {
        this.pushToast(event.detail.message, event.detail.type);
      });
      window.addEventListener("confirm:request", (event) => {
        this.confirmState = Object.assign(
          { title: "Подтвердите действие", text: "", confirmText: "Подтвердить", danger: false, resolve: null },
          event.detail
        );
        this.confirmOpen = true;
      });
      window.addEventListener("keydown", (event) => this.handleKey(event));

      const params = new URLSearchParams(window.location.search);
      if (params.get("msg")) this.pushToast(params.get("msg"), params.get("type") || "success");

      this.loadNotifications();
      window.setInterval(() => this.loadNotifications(), 120000);
    },

    handleKey(event) {
      const isTyping = ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement && document.activeElement.tagName);
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        this.openCommand();
        return;
      }
      if (event.key === "Escape") {
        this.cmdkOpen = false;
        this.notifOpen = false;
        this.userMenuOpen = false;
        this.mobileOpen = false;
        if (this.confirmOpen) this.answerConfirm(false);
        return;
      }
      if (!isTyping && event.key === "/" && !event.metaKey && !event.ctrlKey) {
        event.preventDefault();
        this.openCommand();
      }
    },

    openCommand() {
      this.cmdkOpen = true;
      this.cmdkQuery = "";
      this.cmdkResults = [];
      this.cmdkIndex = 0;
      this.$nextTick(() => {
        if (this.$refs.cmdkInput) this.$refs.cmdkInput.focus();
      });
    },

    async searchCommand() {
      const query = this.cmdkQuery.trim();
      if (!query) {
        this.cmdkResults = [];
        this.cmdkIndex = 0;
        return;
      }
      this.cmdkLoading = true;
      try {
        const response = await fetch("/api/search?q=" + encodeURIComponent(query), { credentials: "include" });
        if (response.ok) {
          this.cmdkResults = await response.json();
          this.cmdkIndex = 0;
        }
      } catch {
        this.cmdkResults = [];
      } finally {
        this.cmdkLoading = false;
      }
    },

    moveCommand(delta) {
      if (!this.cmdkResults.length) return;
      this.cmdkIndex = (this.cmdkIndex + delta + this.cmdkResults.length) % this.cmdkResults.length;
    },

    runCommand(index) {
      const item = this.cmdkResults[typeof index === "number" ? index : this.cmdkIndex];
      if (!item) return;
      window.location.href = item.href;
    },

    async loadNotifications() {
      try {
        this.notifications = await apiJson("/api/dashboard/notifications");
      } catch {
        this.notifications = [];
      }
    },

    pushToast(message, type) {
      const id = Date.now() + Math.random();
      this.toasts.push({ id, message, type: type || "success" });
      window.setTimeout(() => {
        this.toasts = this.toasts.filter((item) => item.id !== id);
      }, 3800);
    },

    answerConfirm(value) {
      if (this.confirmState.resolve) this.confirmState.resolve(value);
      this.confirmOpen = false;
      this.confirmState = { title: "", text: "", confirmText: "Подтвердить", danger: false, resolve: null };
    },
  };
}

window.appShell = appShell;
