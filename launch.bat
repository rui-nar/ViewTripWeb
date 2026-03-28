@echo off
REM ── ViewTripWeb development launcher ──────────────────────────────────────
REM Starts the FastAPI server (port 8000) and the Flutter web client (port 5500)
REM in separate terminal windows.

REM ── Kill any leftover processes on the dev ports ──────────────────────────
for %%P in (8000 5500) do (
    for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":%%P "') do (
        taskkill /PID %%a /F >nul 2>&1
    )
)

REM ── Activate Python venv ──────────────────────────────────────────────────
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
) else (
    echo WARNING: no venv found, using system Python
)

REM ── Start FastAPI server ──────────────────────────────────────────────────
echo Starting FastAPI server on port 8000...
start "ViewTrip API" cmd /k "uvicorn api.router:app --host 0.0.0.0 --port 8000 --reload"

REM ── Find Flutter SDK ──────────────────────────────────────────────────────
set FLUTTER_CMD=flutter
for %%D in (
    "%LOCALAPPDATA%\flutter\bin\flutter.bat"
    "C:\flutter\bin\flutter.bat"
    "C:\src\flutter\bin\flutter.bat"
) do (
    if exist %%D set FLUTTER_CMD=%%D
)

REM ── Start Flutter web client ──────────────────────────────────────────────
echo Starting Flutter web client on port 5500...
start "ViewTrip Flutter" cmd /k "cd flutter_client && %FLUTTER_CMD% run -d chrome --web-port 5500 --dart-define=API_BASE_URL=http://localhost:8000"

echo.
echo  API:     http://localhost:8000
echo  Flutter: http://localhost:5500
echo.
