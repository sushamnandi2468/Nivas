# NivasOps

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/release/python-3130/)
[![Django 5.2](https://img.shields.io/badge/django-5.2-green.svg)](https://www.djangoproject.com/)
[![Next.js 16](https://img.shields.io/badge/next.js-16-black.svg)](https://nextjs.org/)
[![PostgreSQL 16](https://img.shields.io/badge/postgresql-16-336791.svg)](https://www.postgresql.org/)

NivasOps is an open-source, multi-tenant helpdesk and facility-operations platform for residential societies and gated communities. Built with Django 5.2, PostgreSQL Row-Level Security (RLS), and Next.js 16.

## Current Development Slice

- Next.js 16 frontend with the responsive `AUTH-01` experience plus a connected resident workspace for ticket overview, draft creation, and lifecycle tracking.
- Django 5.2 API foundation with PostgreSQL-only settings.
- UUID/E.164 custom user identity with normalized email, IANA timezone, and session-revocation metadata.
- Society/location plus date-bounded staff, resident occupancy, committee membership, and secure membership-invitation models with composite tenant constraints.
- Tenant-scoped ticket categories, subcategories, service/governance ticket records, versioned SLA snapshots/cycles, and versioned society business calendars with database-enforced workflow, location, numbering, version, archival, and tenant invariants.
- Forced PostgreSQL RLS with transaction-local society context and isolation regression tests.
- Issuer/audience-validated JWT authentication with 10-minute access tokens, session revocation,
  persistent refresh-token blacklisting, and deterministic staff, resident, or committee tenant resolution.
- Explicit tenant context for Celery tasks and society-prefixed cache keys.
- DRF OpenAPI endpoints and liveness/readiness probes.
- Celery bootstrap with synchronous local execution during Phase 0.
- Local PostgreSQL 16 and Redis 7 fallback through Docker Compose.

Migrations through `tenancy.0006`, `platform_access.0003`, and `tickets.0007` are applied to the Azure development database. Every tenant table includes forced RLS and tenant-equality constraints in the migration that creates it.

Tenant API views use `TenantJWTAuthentication` by default and require both a bearer access token and `X-Society-ID`. Login, OTP verification, and token-refresh routes are not published yet; their OpenAPI request/response and error contracts must be approved before implementation.

The rationale, guardrails, deferred scope, and revisit trigger are recorded in `docs/decisions/ADR-006-defer-login-workflows.md`.

## Prerequisites

- Python 3.13
- Node.js 20 or newer
- PostgreSQL 16, or Docker Desktop for the provided local services

## First-Time Setup

From PowerShell at the repository root:

```powershell
.\scripts\bootstrap-local.ps1
```

Docker Desktop must be running for the default path. To use an existing PostgreSQL installation instead:

```powershell
.\scripts\bootstrap-local.ps1 -SkipContainers
Copy-Item .env.example .env
```

Set `DATABASE_URL` in `.env` to the existing local database connection. The expected local database and role are both named `nivasops`; any names are valid when reflected in the URL.

### Azure PostgreSQL with Entra authentication

Azure CLI must be installed and signed in. On Windows, install it with `winget install -e --id Microsoft.AzureCLI`, open a new terminal, and run `az login`.

The Azure helper obtains a short-lived token in memory, requires TLS, and never writes the token to `.env`:

```powershell
.\scripts\run-api-azure.ps1 -Command check
.\scripts\run-api-azure.ps1 -Command migrate
.\scripts\run-api-azure.ps1 -Command showmigrations
.\scripts\run-api-azure.ps1 -Command runserver
.\scripts\run-tests-azure.ps1
```

The runner connects to your Azure PostgreSQL server (configured via `PGHOST` or `-DatabaseHost`) and database `nivasopsdb`. The database username is derived from the signed-in Entra user's UPN because Entra tokens cannot authenticate as a password-only PostgreSQL login. Override it with `-DatabaseUser` only when the server has provisioned a different Entra database principal. Restart the command to obtain a fresh token after a long development session.

The test helper creates Django's isolated test database and is required for the PostgreSQL RLS integration tests when local PostgreSQL is unavailable. Do not store `PGPASSWORD`, an Entra token, or a database password in `.env` or source control.

### Development sessions

Manual testing can use a real JWT and persisted staff membership without publishing a login bypass:

```powershell
.\scripts\run-api-azure.ps1 `
    -Command dev-session `
    -EnableDevSession `
    -Phone "+919876543299" `
    -SocietyCode "NIVASOPS-DEV" `
    -Role "FACILITY_MANAGER"
```

The command prints JSON containing a short-lived access token and `society_id`. Treat the token as a secret and send it only as `Authorization: Bearer <token>` together with `X-Society-ID`. The command refuses to run unless Django debug mode and the explicit PowerShell switch are both enabled. It is not an HTTP endpoint and does not appear in OpenAPI.

Automated tests use the in-process cache by default. Set `CACHE_URL` to the dedicated Redis database for integrated cache testing. The Azure-backed suite includes a real non-eager Celery worker and reused-connection RLS checks; it has passed the weeks 3-4 tenant-isolation evidence gate.

For Azure Cache for Redis, set `AZURE_REDIS_HOST`, `AZURE_REDIS_PORT`, and `AZURE_REDIS_ACCESS_KEY` only in the ignored local `.env`, then set `USE_AZURE_REDIS=true` after TLS connectivity is confirmed. The application URL-encodes the key and builds verified `rediss://` connections for the broker, result backend, and cache without logging the secret. Shared-Redis tests use unique keys with explicit cleanup and never call `cache.clear()` or `FLUSHDB`.

## Tenant Directory API

Phase 3 provides tenant-scoped society, location, and initial membership endpoints:

- `GET /api/v1/directory/society/`
- `GET|POST /api/v1/directory/blocks/`
- `GET|POST /api/v1/directory/units/`
- `GET|POST /api/v1/directory/common-areas/`
- `GET|POST /api/v1/directory/occupancies/`
- `GET|POST /api/v1/directory/committee-memberships/`
- `GET|POST /api/v1/directory/technicians/`
- `GET|POST /api/v1/directory/vendors/`
- `GET|POST /api/v1/directory/vendor-contracts/`
- `GET|POST /api/v1/directory/vendor-staff-memberships/`
- `GET|POST /api/v1/directory/membership-invitations/`
- `POST /api/v1/directory/membership-invitations/{invitation_id}/revoke/`

Every request requires a valid bearer token and `X-Society-ID`. Active tenant members can read location records; facility managers and estate supervisors can create them. Occupancy, committee-membership, technician-profile, vendor, contract, vendor-staff, and invitation administration is restricted to facility managers. Current technician profiles grant the technician tenant persona and carry configurable positive capacity with a server-managed active-ticket counter. A vendor staff membership grants the vendor persona only while the membership, vendor, society, user, and linked contract are all active and current. Vendor contract capacity is unlimited when `max_active_tickets` is null; otherwise it must be positive and cannot be lower than the server-managed `current_active_tickets_count`. Invitation creation returns a high-entropy raw token exactly once; only its SHA-256 digest is persisted, and list/revoke responses never expose either value. Invitations expire within seven days and use persona-specific resident, staff, or committee details. Anonymous acceptance and notification-provider delivery are intentionally deferred until their public identity and provider contracts are approved. PostgreSQL RLS and composite tenant constraints provide database-level enforcement in addition to API scoping.

## Platform Access API

Global platform-role administration uses separate platform authentication and policy classes:

- `GET|POST /api/v1/platform/role-grants/`
- `POST /api/v1/platform/role-grants/{grant_id}/approve/`
- `POST /api/v1/platform/role-grants/{grant_id}/revoke/`
- `POST /api/v1/platform/support-sessions/`
- `DELETE /api/v1/platform/support-sessions/{session_id}/`

Only a current `PLATFORM_ADMIN` can manage role grants. New grants remain pending until a different current platform administrator approves them; PostgreSQL also rejects self-approved active grants and duplicate open grants. Grants are time-bounded and revocable. `PLATFORM_SUPPORT`, `PLATFORM_AUDITOR`, and `PLATFORM_ADMIN` grants provide no implicit society membership or tenant API access. Initial platform-administrator grants must be provisioned through the controlled deployment process.

Current `PLATFORM_SUPPORT` and `PLATFORM_AUDITOR` grantees can request one five-to-30-minute, case-bound session when their JWT has an `auth_time` no older than five minutes and an `amr` value of `mfa`, `otp`, or `hwk`. Production identity-provider issuance of those claims is still pending, so production session creation remains fail-closed. A session must be presented as `X-Support-Session-ID` with the matching `X-Society-ID`. It enables read-only access only to society metadata, blocks, units, and common areas; all other tenant routes and every mutation remain denied even for a user who also holds tenant membership.

Support responses include persona, society, case, read-only, expiry, and correlation headers and use `Cache-Control: private, no-store`. Platform access events persist the actor, role grant and role snapshot, selected society, support-session identifier, case reference, reason, correlation identifier, event type, route or action, outcome, and safe metadata. Denied starts and tenant-access attempts are also recorded without token claims or request bodies. PostgreSQL rejects updates and deletes on this append-only table.

## Ticket Core

Phase 4 has started with tenant-scoped `TicketCategory`, `TicketSubCategory`, and `Ticket` models. The initial schema defines service and governance workflows, `P1`-`P4` priorities, canonical statuses including `SUPERVISOR_TRIAGE`, category location/cost/completion policy, exactly one location for service tickets, governance-optional locations, society-local ticket-number uniqueness, and `state_version` beginning at one.

Migration `tickets.0001` is applied to Azure PostgreSQL. Composite foreign keys prevent cross-society category, subcategory, unit, and common-area relationships; forced RLS denies missing or mismatched tenant context. Database triggers require the version to increase on every update, prevent allocated ticket numbers from changing, and reject hard deletion after submission.

Migration `tickets.0002` adds society/year-local number sequences, append-only ticket events, and principal/hash-scoped idempotency records with composite tenant constraints and forced RLS. The named draft-to-submitted service authorizes before claiming idempotency, locks the ticket and annual sequence, checks the expected version, requires an atomic SLA-cycle creator, allocates the number, increments the version, appends one immutable event, and stores a replayable response. Eight focused Azure-backed submission tests pass.

Migration `tickets.0003` adds immutable versioned SLA policy snapshots, active category/priority bindings, and retained per-ticket SLA cycles. Composite tenant foreign keys and forced RLS protect all three tables. `PersistInitialSLACycle` selects the active snapshot, verifies the society timezone, delegates deadline calculation through the explicit business-calendar contract, and persists cycle one inside the submission transaction.

Migration `tickets.0004` adds versioned, tenant-scoped business calendars with one active version per society, forced RLS, replacement-before-retirement enforcement, and mutation/deletion guards once a version is referenced by an SLA snapshot. The production calculator resolves the active society calendar, validates its timezone and local weekly intervals, skips holidays, handles DST boundaries, and supports emergency 24x7 elapsed-time targets. Submission fails closed with typed unavailable, timezone-mismatch, or invalid-calendar errors. Six pure calendar tests, six Azure-backed SLA tests, and ten Azure-backed ticket API tests pass. Calendar administration APIs/UI, pause/resume operations, reopen cycles, and L1-L3 scheduling remain Phase 6 work.

Migration `tickets.0005` adds immutable, tenant-scoped ticket comments with a composite society/ticket foreign key, forced RLS, a ticket-time index, and database rejection of updates and deletes. Public comment list/create routes require ticket visibility; creation additionally requires an idempotency key, the current ticket version, a submitted ticket, and explicit write authority. Residents can comment only on tickets they created, so same-unit read access does not imply write access. Separate internal comment routes are available only to facility-manager/helpdesk staff and, for governance tickets they can already access, committee members; residents cannot access or retrieve internal notes.

Migration `tickets.0006` publishes `TICKET_CANCELLED` as an immutable event type. The named cancellation service authorizes before claiming idempotency: submitted tickets remain creator-owned, while only a facility manager may cancel a governance ticket in `UNDER_REVIEW` or `IN_DISCUSSION`, before any action is recorded. It locks the ticket and active SLA cycle, checks the expected version, records the reason once, ends the SLA cycle with outcome `CANCELLED`, and stores the canonical response atomically. Same-unit read visibility grants no cancellation authority. Replay is deterministic, while stale versions and repeated or invalid transitions return conflicts.

Migration `tickets.0007` adds tenant-scoped governance-review assignments with a same-society ticket constraint, one active reviewer per ticket, forced RLS, and `GOVERNANCE_REVIEW_BEGUN` immutable evidence. `POST /api/v1/governance-tickets/{id}/begin-review/` is the first governance lifecycle transition: a facility manager may self-assign and move a submitted governance ticket to `UNDER_REVIEW` with idempotency and expected-version protection. Committee members fail closed because the current model has no committee-coordinator role. Assignment, broader committee routing, and service-ticket dispatch remain later work.

Migration `tickets.0008` adds tenant-scoped governance discussions and explicit participants with same-society composite foreign keys and forced RLS. `POST /api/v1/governance-tickets/{id}/open-discussion/` allows only the active assigned facility-manager reviewer to move a governance ticket from `UNDER_REVIEW` to `IN_DISCUSSION`. The transition requires a non-empty purpose, uses expected-version and idempotency protection, records the reporter and assigned reviewer as the initial participants, and appends `GOVERNANCE_DISCUSSION_OPENED` immutable evidence. Broader committee routing and notification delivery remain deferred until their model and outbox contracts exist.

Migration `tickets.0009` adds one tenant-scoped `GovernanceActionRecord` per ticket with a same-society ticket constraint and forced RLS, plus `GOVERNANCE_ACTION_RECORDED` immutable evidence. `POST /api/v1/governance-tickets/{id}/record-action/` permits the active assigned reviewer or any active facility manager to move a governance ticket from `UNDER_REVIEW` or `IN_DISCUSSION` to `ACTION_TAKEN`. The command requires an expected version, idempotency key, and non-empty action summary; it records the actor, summary, evidence policy, and transition event atomically. The current explicit evidence policy is `NO_EXTERNAL_EVIDENCE`: attachment-backed evidence references and enforcement remain Phase 7 work because no secure attachment domain exists yet. Reporter notification delivery remains deferred until the transactional outbox contract exists.

Initial ticket HTTP APIs are published for both workflows:

- `GET /api/v1/ticket-options/`
- `GET|POST /api/v1/service-tickets/`
- `GET /api/v1/service-tickets/{id}/`
- `POST /api/v1/service-tickets/{id}/submit/`
- `POST /api/v1/service-tickets/{id}/cancel/`
- `GET|POST /api/v1/governance-tickets/`
- `GET /api/v1/governance-tickets/{id}/`
- `POST /api/v1/governance-tickets/{id}/submit/`
- `POST /api/v1/governance-tickets/{id}/cancel/`
- `POST /api/v1/governance-tickets/{id}/begin-review/`
- `POST /api/v1/governance-tickets/{id}/open-discussion/`
- `POST /api/v1/governance-tickets/{id}/record-action/`
- `GET|POST /api/v1/tickets/service/{id}/comments/`
- `GET|POST /api/v1/tickets/service/{id}/internal-comments/`
- `GET|POST /api/v1/tickets/governance/{id}/comments/`
- `GET|POST /api/v1/tickets/governance/{id}/internal-comments/`

Every request requires a valid bearer token and `X-Society-ID`. The options endpoint returns active classifications and tenant-safe eligible locations; residents receive only their own active unit. Ticket, comment, submission, cancellation, governance-review, governance-discussion, and governance-action POST operations require `Idempotency-Key`; submit, comment creation, cancellation, beginning governance review, opening governance discussion, and recording governance action also require `expected_version`. Cancellation, opening governance discussion, and recording governance action additionally require non-empty reason, purpose, and summary values, respectively. Status, workflow, numbering, creator, version, and submission metadata are read-only. Residents can create and read their reported tickets and service tickets for their active unit; eligible staff have society-wide reads and facility-manager/helpdesk creation and submission; committee members can create and read their own governance tickets. Internal notes are deliberately separate from public threads and cannot be read by residents; assignment-dependent technician, vendor, and committee oversight visibility remains denied until those domain relationships exist. Submit resolves the active society business calendar, creates the initial SLA cycle atomically, and fails closed when a valid matching calendar is unavailable. Twenty-one focused Azure-backed ticket API tests and the full Azure-backed regression of 168 tests pass. Service-ticket assignment, governance resolution pending a threshold/approval policy, attachment-backed evidence, notification delivery, and duplicate detection are not published yet.

## Web Workspaces & Authentication

### Public Authentication & Onboarding
- `/` and `/login` provide the `AUTH-01` multi-tenant authentication page connected to `POST /api/v1/auth/login/` with JWT access/refresh token management and workspace persona destination selection.
- `/activate` provides the `AUTH-03` membership invitation activation portal, verifying one-time tokens and provisioning accounts via `POST /api/v1/auth/activate/`.
- `/forgot-password` and `/reset-password` provide the `AUTH-04` self-service password recovery flow via `POST /api/v1/auth/password-reset/` and `POST /api/v1/auth/password-reset/confirm/`.

### Operations & Resident Workspaces
The authenticated workspace is available under `/app`:

- `/app` provides the `RES-01` resident ticket overview using live service and governance ticket APIs.
- `/app/new` provides the `RES-02` service/civic creation studio and saves valid requests as idempotent drafts for review.
- `/app/tickets/{workflow}/{id}` provides the `RES-03` persisted lifecycle, classification, location, issue detail, material estimate decision banner (`PENDING_ESTIMATE_APPROVAL`), 6-digit completion OTP verification card (`PENDING_RESIDENT_CONFIRMATION`), and public conversation view.
- `/app/operations/service/{id}` provides the Facility Manager service dossier with in-house technician and vendor contract dispatch, supervisor overrides, estimate decisions, deduplication merge initiation, and restricted unmerge recovery.
- `/app/operations/governance/{id}` provides the Facility Manager civic matter review, discussion, action recording, and merge workflows.
- `/app/operations/directory` provides society block, unit, and common area inventory, multi-persona invitations (Residents, Staff, Committee Officers), executive governance committee officers roster, and in-house technician roster capacity management.
- `/app/operations/vendors` provides vendor profile management, contract capacity configuration, and vendor staff/worker enrollment.

For direct token entry during development, the session gate on `/app` supports inputting a development token generated via `dev_session`. Credentials are kept in `sessionStorage` for the current browser tab. Set `NEXT_PUBLIC_API_BASE_URL` to override the default `http://127.0.0.1:8000` API address.

The frontend does not simulate missing domain capabilities. Draft submission uses the production calendar-backed endpoint with idempotency and expected-version checks. Submitted tickets load chronological public comments and provide an accessible expected-version-protected composer. Their creators can cancel them through a reason-required confirmation dialog; success reloads the canonical stopped lifecycle, while transition conflicts remain localized to the dialog. Attachments, preferred scheduling, and notifications remain unavailable until their backend contracts exist.

## Run Locally

Start the API:

```powershell
.\.venv\Scripts\python.exe backend\manage.py runserver 127.0.0.1:8000
```

Start the web app in a second terminal:

```powershell
npm run dev --prefix frontend
```

Open:

- Web app: `http://localhost:3000`
- API docs: `http://localhost:8000/api/v1/docs/`
- Liveness: `http://localhost:8000/api/v1/health/live/`
- Readiness: `http://localhost:8000/api/v1/health/ready/`

## Validation

```powershell
npm run build --prefix frontend
npm run lint --prefix frontend
.\.venv\Scripts\python.exe backend\manage.py check
.\scripts\run-tests-azure.ps1 `
    -TestPath backend\tests\test_ticket_api.py `
    -TestDatabaseName nivasopstestdb `
    -PytestArguments --reuse-db
.\.venv\Scripts\ruff.exe check backend
```

Backend tests use `config.settings_test` and require `TEST_PGDATABASE`; the
Azure runner supplies it from `-TestDatabaseName`. The value must begin with
`test_` or use a NivasOps name containing `test`, and must be an isolated
database, never the development or production database. Use a focused test
path during iteration. Only add `--reuse-db` after that database is dedicated
to a single developer or CI worker.

Readiness returns HTTP `503` until PostgreSQL is running and `DATABASE_URL` is valid. That failure is intentional and prevents an unhealthy API instance from receiving traffic.

## Community & Contributing

We welcome community contributions, bug reports, and operational feedback!
- Read our [Contributing Guidelines](CONTRIBUTING.md) to get started with local development.
- Review our [Code of Conduct](CODE_OF_CONDUCT.md).
- Report security issues responsibly following our [Security Policy](SECURITY.md).

## License

NivasOps is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**. See the [LICENSE](LICENSE) file for complete license terms. Under Section 13 of the AGPL-3.0, any modified network service using this code must provide corresponding source code access to its network users.