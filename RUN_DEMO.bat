@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [orbit-crm] запуск CRM на http://127.0.0.1:8000
if not exist ".env" copy ".env.example" ".env" >nul
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  .venv\Scripts\pip install -q -r requirements.txt
)
start "" http://127.0.0.1:8000
.venv\Scripts\python -m uvicorn app.main:app --port 8000
