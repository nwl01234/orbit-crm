@echo off
taskkill /FI "WINDOWTITLE eq Orbit CRM Web*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Orbit CRM Bot*" /T /F >nul 2>&1
echo Orbit CRM stopped.
pause
