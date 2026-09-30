import os
from pathlib import Path

TEST_DB = Path(__file__).with_name("test_crm.db")

# Isolate the suite from the demo database before the application is imported.
if TEST_DB.exists():
    TEST_DB.unlink()
os.environ["DATABASE_URL"] = "sqlite:///" + TEST_DB.as_posix()
os.environ["AI_INDEX_ON_STARTUP"] = "false"
os.environ["SECRET_KEY"] = "test-secret-key"


def pytest_sessionfinish(session, exitstatus):
    try:
        from app.database import engine

        engine.dispose()
    except Exception:
        pass
    if TEST_DB.exists():
        try:
            TEST_DB.unlink()
        except PermissionError:
            pass
