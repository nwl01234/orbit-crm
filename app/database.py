from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    future=True,
    pool_pre_ping=True,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, _connection_record):
    if not settings.DATABASE_URL.startswith("sqlite"):
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        if ":memory:" not in settings.DATABASE_URL:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    future=True,
)


# Lightweight, idempotent migrations for SQLite demo deployments. For a real
# production rollout this project would use Alembic; the shape below keeps the
# zero-setup demo intact while never destroying existing data.
_ADDED_COLUMNS = {
    "users": [
        ("job_title", "VARCHAR(120) NOT NULL DEFAULT ''"),
        ("phone", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("last_login_at", "DATETIME"),
    ],
    "applications": [
        ("amount", "FLOAT NOT NULL DEFAULT 0"),
        ("lost_reason", "VARCHAR(255) NOT NULL DEFAULT ''"),
        ("company_id", "INTEGER REFERENCES companies(id) ON DELETE SET NULL"),
        ("contact_id", "INTEGER REFERENCES contacts(id) ON DELETE SET NULL"),
        ("closed_at", "DATETIME"),
    ],
    "tasks": [
        ("kind", "VARCHAR(24) NOT NULL DEFAULT 'task'"),
        ("completed_at", "DATETIME"),
    ],
}

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_applications_company_id ON applications (company_id)",
    "CREATE INDEX IF NOT EXISTS ix_applications_contact_id ON applications (contact_id)",
    "CREATE INDEX IF NOT EXISTS ix_applications_closed_at ON applications (closed_at)",
    "CREATE INDEX IF NOT EXISTS ix_companies_owner_id ON companies (owner_id)",
    "CREATE INDEX IF NOT EXISTS ix_contacts_company_id ON contacts (company_id)",
    "CREATE INDEX IF NOT EXISTS ix_contacts_owner_id ON contacts (owner_id)",
    "CREATE INDEX IF NOT EXISTS ix_tasks_kind ON tasks (kind)",
]


def _migrate_sqlite() -> None:
    if not settings.DATABASE_URL.startswith("sqlite"):
        return
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        for table, columns in _ADDED_COLUMNS.items():
            if table not in tables:
                continue
            existing = {column["name"] for column in inspector.get_columns(table)}
            for name, ddl in columns:
                if name in existing:
                    continue
                try:
                    connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
                except Exception:
                    # Very old SQLite builds can reject REFERENCES in ADD COLUMN.
                    connection.exec_driver_sql(
                        f"ALTER TABLE {table} ADD COLUMN {name} {ddl.split(' REFERENCES')[0]}"
                    )
        for statement in _INDEXES:
            try:
                connection.exec_driver_sql(statement)
            except Exception:
                pass


def init_db() -> None:
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _migrate_sqlite()
