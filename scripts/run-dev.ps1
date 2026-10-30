# Start the backend (serves the built frontend too) on http://127.0.0.1:8000
# Usage: .\scripts\run-dev.ps1 [-Port 8000]
param([int]$Port = 8000)
$root = Split-Path $PSScriptRoot -Parent
Set-Location "$root\backend"
& .\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port $Port
