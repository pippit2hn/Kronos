@echo off
setlocal
cd /d "%~dp0webui"

if not exist "%~dp0.venv\Scripts\python.exe" (
    echo [ERROR] Khong tim thay .venv. Hay chay setup_windows.ps1 truoc.
    pause
    exit /b 1
)

set HOST=127.0.0.1
set PORT=7070
set FLASK_DEBUG=0
set PYTHONUNBUFFERED=1

echo Kronos Live Forecast
echo Server: http://127.0.0.1:%PORT%/forecast   (dong cua so nay de tat server)
echo.

rem Mo trinh duyet khi server da san sang (cho toi da 120 giay)
start "" /b powershell -NoProfile -Command "$u='http://127.0.0.1:%PORT%/forecast'; for($i=0;$i -lt 120;$i++){ try{ Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 $u | Out-Null; Start-Process $u; break }catch{ Start-Sleep 1 } }"

"%~dp0.venv\Scripts\python.exe" app.py

echo.
echo Server da dung. Neu co loi, hay gui noi dung o tren cho Claude.
pause
