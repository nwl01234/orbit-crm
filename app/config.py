import re
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "Orbit CRM"
    APP_TAGLINE: str = "Операционная CRM для команд"
    DEBUG: bool = False
    ENVIRONMENT: str = "demo"

    DATABASE_URL: str = "sqlite:///./crm.db"

    SECRET_KEY: str = "change-me-to-random-string"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    COOKIE_SECURE: bool = False
    LOGIN_MAX_ATTEMPTS: int = 8
    LOGIN_WINDOW_SECONDS: int = 300

    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "admin123"
    ADMIN_EMAIL: str = "admin@example.com"

    AI_BASE_URL: str = ""
    AI_API_KEY: str = ""
    AI_MODEL: str = "llama3.2:1b"
    AI_EMBED_MODEL: str = "nomic-embed-text"
    AI_TIMEOUT: int = 8
    AI_INDEX_ON_STARTUP: bool = False
    AI_MAX_CONTEXT_CHARS: int = 12000

    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_ADMIN_IDS: str = ""
    TELEGRAM_NOTIFY_ON_CREATE: bool = True

    CORS_ORIGINS: str = "http://localhost:8000,http://127.0.0.1:8000"

    @property
    def ai_enabled(self) -> bool:
        return bool(self.AI_BASE_URL.strip() and self.AI_API_KEY.strip())

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.TELEGRAM_BOT_TOKEN.strip())

    @property
    def is_default_secret(self) -> bool:
        return self.SECRET_KEY.strip() in {"", "change-me-to-random-string"}

    @property
    def telegram_admin_id_list(self) -> list[int]:
        result: list[int] = []
        for part in re.split(r"[,\s]+", self.TELEGRAM_ADMIN_IDS):
            part = part.strip()
            if not part:
                continue
            try:
                value = int(part)
            except ValueError:
                continue
            if value > 0 and value not in result:
                result.append(value)
        return result

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
