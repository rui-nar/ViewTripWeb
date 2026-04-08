@echo off
REM ── ViewTripWeb dev launcher ─────────────────────────────────────────────────
REM Opens Windows Terminal with two PowerShell 7 tabs:
REM   Tab 1 — FastAPI server  (http://localhost:8000)
REM   Tab 2 — Flutter client  (http://localhost:5500)

REM ── Kill any leftover processes on the dev ports ──────────────────────────────
for %%P in (8000 5500) do (
    for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":%%P "') do (
        taskkill /PID %%a /F >nul 2>&1
    )
)

REM ── Open Windows Terminal: two tabs, PowerShell 7 ─────────────────────────────
start "" wt new-tab --title "ViewTrip API"    pwsh.exe -NoExit -File "%~dp0dev-server.ps1" ^
        ; new-tab --title "ViewTrip Flutter" pwsh.exe -NoExit -File "%~dp0dev-client.ps1"
