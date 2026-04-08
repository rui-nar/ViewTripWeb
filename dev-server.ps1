# Activate venv and start FastAPI dev server (port 8000)
Set-Location $PSScriptRoot
if (Test-Path '.venv\Scripts\Activate.ps1') {
    .\.venv\Scripts\Activate.ps1
} else {
    Write-Host 'No venv found — using system Python' -ForegroundColor Yellow
}
uvicorn api.router:app --host 0.0.0.0 --port 8000 --reload
