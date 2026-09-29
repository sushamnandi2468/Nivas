#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "=== Bootstrapping NivasOps Local Environment ==="

if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "Created .env from .env.example. Review local credentials as needed."
fi

if [ ! -d ".venv" ]; then
    echo "Creating Python virtual environment in .venv..."
    python3 -m venv .venv
fi

echo "Installing backend dependencies..."
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r backend/requirements/dev.txt

echo "Installing frontend dependencies..."
npm install --prefix frontend

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    echo "Starting local PostgreSQL and Redis containers..."
    docker compose up -d db redis
else
    echo "Docker is not running. Start Docker Compose manually if needed: docker compose up -d db redis"
fi

echo ""
echo "=== Local environment setup complete! ==="
echo "Run database migrations: .venv/bin/python backend/manage.py migrate"
echo "Start API server:        .venv/bin/python backend/manage.py runserver"
echo "Start Web client:        npm run dev --prefix frontend"
