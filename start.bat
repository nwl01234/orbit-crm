@echo off
setlocal
cd /d "%~dp0"

if not exist ".env" copy ".env.example" ".env" >nul

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv .venv
  if not exist ".venv\Scripts\python.exe" py -m venv .venv
)

if not exist ".venv\Scripts\python.exe" (
  echo ERROR: Python 3.11+ not found. Install Python and rerun.
  pause
  exit /b 1
)

echo Installing dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt

echo Starting Orbit CRM on http://127.0.0.1:8000 ...
start "Orbit CRM Web" /D "%~dp0" ".venv\Scripts\python.exe" run.py

timeout /t 3 /nobreak >nul

if not "%TELEGRAM_BOT_TOKEN%"=="" goto start_bot
for /f "tokens=1,* delims==" %%a in ('findstr /b "TELEGRAM_BOT_TOKEN=" .env 2^>nul') do set "TELEGRAM_BOT_TOKEN=%%b"
if "%TELEGRAM_BOT_TOKEN%"=="" goto skip_bot

:start_bot
echo Starting Telegram bot...
start "Orbit CRM Bot" /D "%~dp0" ".venv\Scripts\python.exe" -m app.bot.main

:skip_bot

timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:8000

echo.
echo Web window title: Orbit CRM Web
echo Login: admin / admin123
echo Manager: manager / manager123
echo Close the window to stop the web app.
pause
