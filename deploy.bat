@echo off
cd /d "C:\0. Apps\wedge-caliper-dashboard"
echo [1/4] Pulling from GitHub...
git pull
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Git pull FAILED!
    pause
    exit /b 1
)
echo       OK
echo [2/4] Stopping server (port 3021)...
set "KILLED=0"
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":3021 " ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F >nul 2>&1
    set "KILLED=1"
)
if "%KILLED%"=="1" ( ping -n 3 127.0.0.1 >nul )
echo       OK
echo [3/4] Starting Streamlit (port 3021)...
if not exist logs mkdir logs
powershell -Command "Start-Process -FilePath 'python' -ArgumentList '-m','streamlit','run','app.py' -WorkingDirectory 'C:\0. Apps\wedge-caliper-dashboard' -RedirectStandardError 'C:\0. Apps\wedge-caliper-dashboard\logs\error.log' -RedirectStandardOutput 'C:\0. Apps\wedge-caliper-dashboard\logs\output.log' -WindowStyle Hidden"
ping -n 6 127.0.0.1 >nul
echo [4/4] Checking...
netstat -ano | findstr ":3021 " | findstr "LISTENING" >nul 2>&1
if %errorlevel% equ 0 (
    echo       OK
    echo.
    echo ========================================
    echo   Deploy SUCCESS! http://192.168.107.6:3021
    echo ========================================
) else (
    echo       FAILED!
    echo.
    type "C:\0. Apps\wedge-caliper-dashboard\logs\error.log"
)
echo.
pause