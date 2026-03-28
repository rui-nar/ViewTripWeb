@echo off
:: Wrapper — runs deploy.ps1 via PowerShell from any terminal.
powershell -ExecutionPolicy Bypass -File "%~dp0deploy.ps1" %*
