# Contributing to NivasOps

Thank you for your interest in contributing to NivasOps! NivasOps is an open-source, multi-tenant helpdesk and facility operations platform for residential societies, licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**.

## Code of Conduct

All contributors are expected to uphold the [Contributor Covenant](CODE_OF_CONDUCT.md).

## Development Philosophy

- **Tenant Isolation**: Every database query affecting tenant data MUST respect PostgreSQL Row-Level Security (RLS) and set `set_local_society_id(society_id)`.
- **Auditability**: State-changing operations must generate immutable `TicketEvent` records with an authenticated actor persona.
- **Optimistic Concurrency**: Lifecycle transitions must check and increment `state_version`.
- **Fail-Closed Security**: Missing permissions, unverified memberships, or expired challenges must fail closed.

## Local Setup

### Prerequisites
- Python 3.13
- Node.js 20 or newer
- Docker & Docker Compose (for local PostgreSQL 16 & Redis 7)

### Getting Started

1. **Clone the repository:**
   ```bash
   git clone https://github.com/sushamnandi2468/Nivas.git
   cd Nivas
   ```

2. **Start backing services:**
   ```bash
   docker compose up -d db redis
   ```

3. **Backend setup:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   pip install -r backend/requirements/dev.txt
   cp .env.example .env
   python backend/manage.py migrate
   python backend/manage.py runserver
   ```

4. **Frontend setup:**
   ```bash
   npm install --prefix frontend
   npm run dev --prefix frontend
   ```

## Running Tests

Before submitting a pull request, run all test and lint suites:

```bash
# Backend lint and validation
ruff check backend
python backend/manage.py makemigrations --check --dry-run
python backend/manage.py check

# Backend tests (isolated test database)
TEST_PGDATABASE=test_nivasops pytest backend/tests/test_ticket_api.py -q

# Frontend lint and build
npm run lint --prefix frontend
npm run build --prefix frontend
```

## Pull Request Guidelines

1. Fork the repo and create a feature branch (`git checkout -b feature/my-feature`).
2. Make minimal, focused edits. Follow existing code formatting conventions.
3. Add unit and integration tests covering the new behavior, including tenant boundary assertions.
4. Ensure all CI checks pass.
5. Submit a pull request describing the change, testing steps, and relevant issue references.
