@echo off
:: Wrapper — runs bump_version_and_release.ps1 via PowerShell from any terminal.
powershell -ExecutionPolicy Bypass -File "%~dp0bump_version_and_release.ps1" %*
pause
