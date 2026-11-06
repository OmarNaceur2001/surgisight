# Start the SurgiSight development environment
$Root = Split-Path -Parent $PSScriptRoot

Write-Host "Starting SurgiSight dev environment..." -ForegroundColor Cyan

# API (with hot-reload)
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$Root'; .venv\Scripts\uvicorn.exe surgisight.api.main:app --reload --host 127.0.0.1 --port 8000"

# Worker (placeholder -- WP5)
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$Root'; Write-Host 'Worker not yet implemented (WP5)' -ForegroundColor Yellow; pause"

# Frontend
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$Root\web'; npm run dev"

Write-Host "API  -> http://127.0.0.1:8000/api/docs" -ForegroundColor Green
Write-Host "Web  -> http://localhost:5173" -ForegroundColor Green
