from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

Role = Literal["admin", "employee"]
ApplicationStatus = Literal["new", "in_progress", "done", "cancelled"]
Priority = Literal["low", "medium", "high", "urgent"]
TaskKind = Literal["task", "call", "meeting", "email"]


def _validate_iso_date(value: Optional[str]) -> Optional[str]:
    if value in (None, ""):
        return None
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError) as exc:
        raise ValueError("Дата должна быть в формате YYYY-MM-DD") from exc
    return value


class CamelModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- users


class UserBase(CamelModel):
    username: str = Field(min_length=2, max_length=64)
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)
    role: Role = "employee"
    job_title: str = ""
    phone: str = ""


class UserCreate(UserBase):
    password: str = Field(min_length=6, max_length=128)


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    email: Optional[EmailStr] = None
    role: Optional[Role] = None
    job_title: Optional[str] = None
    phone: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=6, max_length=128)


class UserOut(UserBase):
    id: int
    is_active: bool
    telegram_id: Optional[int] = None
    last_login_at: Optional[datetime] = None
    created_at: datetime
    initials: str = ""


class UserLogin(BaseModel):
    username: str
    password: str


class ProfileUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    email: Optional[EmailStr] = None
    job_title: Optional[str] = None
    phone: Optional[str] = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6, max_length=128)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ------------------------------------------------------------------------- companies


class CompanyBase(CamelModel):
    name: str = Field(min_length=1, max_length=255)
    domain: str = ""
    industry: str = ""
    size: str = ""
    website: str = ""
    email: str = ""
    phone: str = ""
    address: str = ""
    notes: str = ""
    owner_id: Optional[int] = None


class CompanyCreate(CompanyBase):
    pass


class CompanyUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    domain: Optional[str] = None
    industry: Optional[str] = None
    size: Optional[str] = None
    website: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None
    owner_id: Optional[int] = None


class CompanyOut(CompanyBase):
    id: int
    owner_name: Optional[str] = None
    contacts_count: int = 0
    deals_count: int = 0
    open_deals_count: int = 0
    pipeline_amount: float = 0
    created_at: datetime
    updated_at: datetime


class CompanyDetail(CompanyOut):
    contacts: list["ContactOut"] = []
    deals: list["ApplicationListOut"] = []


# -------------------------------------------------------------------------- contacts


class ContactBase(CamelModel):
    full_name: str = Field(min_length=1, max_length=255)
    email: str = ""
    phone: str = ""
    position: str = ""
    company_id: Optional[int] = None
    owner_id: Optional[int] = None
    notes: str = ""
    is_primary: bool = False


class ContactCreate(ContactBase):
    pass


class ContactUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    email: Optional[str] = None
    phone: Optional[str] = None
    position: Optional[str] = None
    company_id: Optional[int] = None
    owner_id: Optional[int] = None
    notes: Optional[str] = None
    is_primary: Optional[bool] = None


class ContactOut(ContactBase):
    id: int
    company_name: Optional[str] = None
    owner_name: Optional[str] = None
    deals_count: int = 0
    open_deals_count: int = 0
    last_deal_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    initials: str = ""


class ContactDetail(ContactOut):
    deals: list["ApplicationListOut"] = []


# ---------------------------------------------------------------------- applications


class ApplicationBase(CamelModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    status: ApplicationStatus = "new"
    priority: Priority = "medium"
    category: str = "general"
    source: str = "web"
    tags: str = ""
    due_date: Optional[str] = None
    amount: float = Field(default=0, ge=0, le=1_000_000_000_000)
    lost_reason: str = ""
    starred: bool = False
    client_name: str = ""
    client_email: str = ""
    client_phone: str = ""
    client_contact: str = ""
    company_id: Optional[int] = None
    contact_id: Optional[int] = None
    assigned_to_id: Optional[int] = None

    _due = field_validator("due_date")(_validate_iso_date)


class ApplicationCreate(ApplicationBase):
    pass


class ApplicationUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    status: Optional[ApplicationStatus] = None
    priority: Optional[Priority] = None
    category: Optional[str] = None
    source: Optional[str] = None
    tags: Optional[str] = None
    due_date: Optional[str] = None
    amount: Optional[float] = Field(default=None, ge=0, le=1_000_000_000_000)
    lost_reason: Optional[str] = None
    starred: Optional[bool] = None
    client_name: Optional[str] = None
    client_email: Optional[str] = None
    client_phone: Optional[str] = None
    client_contact: Optional[str] = None
    company_id: Optional[int] = None
    contact_id: Optional[int] = None
    assigned_to_id: Optional[int] = None

    _due = field_validator("due_date")(_validate_iso_date)


class StatusUpdate(BaseModel):
    status: ApplicationStatus


class ApplicationListOut(ApplicationBase):
    id: int
    ai_summary: Optional[str] = None
    created_by_id: Optional[int] = None
    assigned_to_name: Optional[str] = None
    company_name: Optional[str] = None
    contact_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    closed_at: Optional[datetime] = None


class ApplicationOut(ApplicationListOut):
    comments_count: int = 0
    open_tasks_count: int = 0


class ApplicationPage(BaseModel):
    items: list[ApplicationOut]
    total: int
    limit: int
    offset: int


class CommentCreate(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    is_internal: bool = False


class CommentOut(CamelModel):
    id: int
    app_id: int
    user_id: int
    text: str
    is_internal: bool
    created_at: datetime
    user_name: Optional[str] = None


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    due_date: Optional[str] = None
    app_id: Optional[int] = None
    kind: TaskKind = "task"
    user_id: Optional[int] = None

    _due = field_validator("due_date")(_validate_iso_date)


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    due_date: Optional[str] = None
    is_done: Optional[bool] = None
    kind: Optional[TaskKind] = None
    user_id: Optional[int] = None

    _due = field_validator("due_date")(_validate_iso_date)


class TaskOut(CamelModel):
    id: int
    app_id: Optional[int] = None
    user_id: int
    title: str
    kind: TaskKind = "task"
    due_date: Optional[str] = None
    is_done: bool
    created_at: datetime
    completed_at: Optional[datetime] = None
    user_name: Optional[str] = None
    application_title: Optional[str] = None


class ActionResult(BaseModel):
    updated: int


class BulkStatusUpdate(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)
    status: ApplicationStatus


class ActionLogOut(CamelModel):
    id: int
    user_id: Optional[int] = None
    action: str
    entity_type: str
    entity_id: Optional[int] = None
    details: str
    created_at: datetime
    username: Optional[str] = None


class AIChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class AIChatRequest(BaseModel):
    messages: list[AIChatMessage] = Field(min_length=1)


class AIAnalysisOut(BaseModel):
    summary: str
    priority: Priority


class StatsOut(BaseModel):
    total: int
    by_status: dict[str, int]
    by_priority: dict[str, int]
    by_category: dict[str, int]
    by_source: dict[str, int]
    overdue: int
    last_7_days: int
    last_30_days: int
    top_clients: list[dict]
    conversion: dict[str, int]
    open_tasks: int
    my_open_tasks: int = 0
    unassigned: int = 0
    pipeline_amount: float = 0
    won_amount: float = 0
    avg_deal_amount: float = 0
    companies: int = 0
    contacts: int = 0
    trend: list[dict] = []
    workload: list[dict] = []
    sources: list[dict] = []
    categories: list[dict] = []


class TelegramBind(BaseModel):
    telegram_id: Optional[int] = None


CompanyDetail.model_rebuild()
ContactDetail.model_rebuild()
