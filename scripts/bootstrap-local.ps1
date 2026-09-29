[CmdletBinding()]
param(
    [switch]$SkipContainers
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example. Review local credentials before continuing."
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    python -m venv .venv
}

& ".venv\Scripts\python.exe" -m pip install --upgrade pip
& ".venv\Scripts\python.exe" -m pip install -r "backend\requirements\dev.txt"
npm install --prefix frontend

if (-not $SkipContainers) {
    docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Desktop is not running. Start it or rerun with -SkipContainers for an existing PostgreSQL installation."
    }
    docker compose up -d db redis
}

Write-Host "Local dependencies are ready. Database migrations are intentionally explicit."
Write-Host "Next: .\.venv\Scripts\python.exe backend\manage.py migrate"