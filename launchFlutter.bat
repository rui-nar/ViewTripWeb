@echo off
setlocal

:: Ports used:
::   3000  — Reflex frontend (Next.js)
::   8000  — Reflex / FastAPI backend
::   5500  — Flutter web client
set REFLEX_FRONTEND=3000
set REFLEX_BACKEND=8000
set FLUTTER_PORT=5500

:: ── Locate Flutter ────────────────────────────────────────────────────────────
:: Try PATH first, then common install locations.
set FLUTTER_BIN="E:\DevTools\flutter\bin\flutter.bat"
where flutter >nul 2>&1
if %errorlevel% neq 0 (
    for %%D in (
        "C:\flutter\bin\flutter.bat"
        "C:\src\flutter\bin\flutter.bat"
        "C:\tools\flutter\bin\flutter.bat"
        "%USERPROFILE%\flutter\bin\flutter.bat"
        "%USERPROFILE%\development\flutter\bin\flutter.bat"
        "%LOCALAPPDATA%\flutter\bin\flutter.bat"
        "E:\DevTools\flutter\bin\flutter.bat"
		
    ) do (
        if exist %%D (
            set "FLUTTER_BIN=%%~D"
            goto :flutter_found
        )
    )
    echo ERROR: Flutter not found in PATH or common locations.
    echo Please either:
    echo   1. Add Flutter to your PATH, or
    echo   2. Set FLUTTER_BIN at the top of this file to your flutter.bat path
    echo      e.g. set FLUTTER_BIN=C:\flutter\bin\flutter.bat
    pause
    exit /b 1
)
:flutter_found
echo Using Flutter: %FLUTTER_BIN%

:: ── Free ports ────────────────────────────────────────────────────────────────
echo Freeing ports %REFLEX_FRONTEND%, %REFLEX_BACKEND%, %FLUTTER_PORT%...

for %%P in (%REFLEX_FRONTEND% %REFLEX_BACKEND% %FLUTTER_PORT%) do (
    for /f "tokens=5" %%p in ('netstat -ano 2^>nul ^| findstr ":%%P " 2^>nul ^| findstr "LISTENING" 2^>nul') do (
        echo   Killing PID %%p on port %%P
        taskkill /PID %%p /F >nul 2>&1
    )
)

timeout /t 1 /nobreak >nul

:: ── Launch Reflex server (also serves the REST API for Flutter) ───────────────
echo Starting Reflex + API server...
start "ViewTrip - Server" /d "%~dp0" cmd /k "call .venv\Scripts\activate && reflex run"

echo Waiting for server to be ready...
timeout /t 8 /nobreak >nul

:: ── Launch Flutter web client ─────────────────────────────────────────────────
:: Check that flutter create . has been run (web/ directory must exist)
if not exist "%~dp0flutter_client\web\" (
    echo ERROR: flutter_client\web\ not found.
    echo Run this first inside flutter_client\:
    echo   flutter create .
    pause
    exit /b 1
)
echo Starting Flutter client...
:: Use start /d to set working directory — avoids nested-quote issues in cmd /k
start "ViewTrip - Flutter" /d "%~dp0flutter_client" cmd /k %FLUTTER_BIN%" run -d chrome --web-port %FLUTTER_PORT%"

echo.
echo Both processes are running in separate windows.
echo   Server:  http://localhost:%REFLEX_BACKEND%
echo   Web app: http://localhost:%REFLEX_FRONTEND%
echo   Flutter: http://localhost:%FLUTTER_PORT%
echo.
echo Close the terminal windows to stop each process.
endlocal
pause