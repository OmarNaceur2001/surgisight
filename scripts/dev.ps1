# Start the SurgiSight development environment
$Root = Split-Path -Parent $PSScriptRoot

Write-Host "Starting SurgiSight dev environment..." -ForegroundColor Cyan

# API (with hot-reload)
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$Root'; .venv\Scripts\uvicorn.exe surgisight.api.main:app --reload --host 127.0.0.1 --port 8000"

# Database-backed analysis worker
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$Root'; .venv\Scripts\python.exe -m surgisight.worker"

# Frontend
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$Root\web'; npm run dev -- --host localhost"

Write-Host "API  -> http://127.0.0.1:8000/api/docs" -ForegroundColor Green
Write-Host "Web  -> http://localhost:5173" -ForegroundColor Green
