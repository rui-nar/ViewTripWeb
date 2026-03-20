@echo off
echo Freeing ports 3000 and 8000...

for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":3000 " ^| findstr "LISTENING"') do (
    echo   Killing PID %%p on port 3000
    taskkill /PID %%p /F >nul 2>&1
)
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    echo   Killing PID %%p on port 8000
    taskkill /PID %%p /F >nul 2>&1
)

timeout /t 1 /nobreak >nul

call .venv\Scripts\activate
reflex run
pause
