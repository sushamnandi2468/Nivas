## Description

Please provide a summary of the changes and the related issue/context.

Fixes # (issue)

## Type of Change

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update
- [ ] Performance or security hardening

## Security & Architecture Checklist

- [ ] All database queries respect composite tenant keys and PostgreSQL Row-Level Security (RLS).
- [ ] Any state-changing command creates an immutable `TicketEvent` with a verified actor and persona.
- [ ] Optimistic concurrency (`state_version`) and idempotency are preserved.
- [ ] No secrets, keys, or credentials are hardcoded or committed.

## Testing & Validation

Please describe the tests that you ran to verify your changes:
- [ ] Focused backend tests: `pytest ...`
- [ ] Django check: `python manage.py check`
- [ ] Ruff lint: `ruff check backend`
- [ ] Frontend build: `npm run build --prefix frontend`
- [ ] Frontend lint: `npm run lint --prefix frontend`
