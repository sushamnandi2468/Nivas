# NivasOps Development Instructions

These instructions apply to every change in this repository. Treat
`docs/NIVASOPS_DELIVERY_TRACKER.md` as the current delivery record and
architecture roadmap. Update the tracker only after the relevant validation has passed.

## Working Style

- Start from the concrete request, failing test, route, model, or tracker item.
  Read only enough nearby code and one relevant test to form a falsifiable
  hypothesis, then make the smallest grounded edit.
- Preserve existing conventions. Do not perform broad refactors, reformatting,
  or cleanup unrelated to the requested slice.
- Before the first substantive edit, identify the cheapest focused test,
  migration check, type check, lint, or build that can disprove the hypothesis.
  Run that check immediately after the edit before expanding the scope.
- Finish with focused validation. Run the broader suite when the change affects
  shared domain contracts, migrations, authorization, or public API behavior.
- Never discard, revert, or overwrite unrelated working-tree changes. Do not
  create commits or branches unless explicitly asked.
- Record a blocker rather than inventing a policy, actor, approval, identity,
  or external integration contract.

## Current Delivery Context

- Phase 5 dispatch work is in progress. The current validated backend contract
  includes vendor assignment, dispatcher allocation of a named worker, worker
  self-acceptance, dispatcher acceptance on behalf with a required reason, and
  pre-acceptance worker replacement with preserved allocation history.
- Replacement is deliberately limited to an `ALLOCATED` worker on an offered
  vendor assignment. Do not implement post-acceptance reassignment as an
  allocation swap; it requires separate ticket, SLA, capacity, and cancellation
  semantics.
- Acceptance-timeout automation is blocked on a durable, per-society scheduler
  principal. Do not impersonate a dispatcher, ticket creator, or facility
  manager to make an automated event appear legitimate.
- Governance resolution remains blocked on an approved tenant-scoped threshold
  and approval policy. Do not create a guessed approval workflow.
- See the delivery tracker for all other deferred and blocked items before
  beginning a new feature.

## Backend Rules

The backend is Django 5.2, Django REST Framework, Celery, Azure PostgreSQL,
and Azure Redis. The local interpreter is:

```powershell
C:\Users\snandi\Documents\Projects\NivasOps\.venv\Scripts\python.exe
```

- All tenant-scoped database access must run inside `transaction.atomic()` and
  set `set_local_society_id(society_id)` before ORM or raw SQL work. Retain
  composite society constraints and PostgreSQL RLS protections.
- Implement state-changing ticket behavior as a transactional command service
  in `backend/apps/tickets/services.py`. Lock the ticket and every active row
  whose state or capacity is being decided. Use `state_version` optimistic
  concurrency checks and increment the version for audit-only mutations too.
- Create immutable `TicketEvent` evidence for every business transition or
  significant dispatch mutation. Events require a real `User` actor and an
  actor persona; record a reason and structured metadata when accountability is
  material.
- Preserve user-principal-scoped idempotency. Claim/replay records using the
  authenticated actor, canonical request hash, route template, and idempotency
  key. Ensure a successful replay remains reachable after a state transition
  while new commands remain protected by locked state checks.
- Keep generic ticket visibility separate from assignment-specific vendor
  access. Do not broaden `CanAccessTickets` to allow vendors. Dispatcher and
  worker endpoints must be contract/allocation scoped and use their dedicated
  permissions.
- Avoid `select_related` through nullable relations in a `select_for_update()`
  query on PostgreSQL; it can attempt to lock the nullable side of an outer
  join. Lock the owning row first and load nullable relations separately.
- For new schema changes, create a Django migration. Do not edit historical
  migrations, especially `tickets.0010_ticket_assignment.py`. Run:

```powershell
Set-Location backend
& "..\.venv\Scripts\python.exe" manage.py makemigrations --check --dry-run
```

- Do not apply migrations to Azure, provision Azure resources, deploy, or alter
  production settings without explicit user authorization. Migrations
  `tickets.0011` through `tickets.0014` are local-only until separately
  authorized for Azure application.

## Backend Validation

Use focused tests first. Development environments currently use Azure
PostgreSQL rather than local Docker or PostgreSQL, so do not make a full suite
the default after every small edit.

- For an iterative change, run the closest named test or workflow subset first:

```powershell
Set-Location backend
& "..\.venv\Scripts\python.exe" -m pytest tests/test_ticket_api.py -k "test_name" -q
```

- A reusable test database may be used with `--reuse-db` only after dedicated
  test settings require an explicitly named, isolated per-developer or per-CI
  Azure test database. It must never resolve to a development or production
  database.
  Pytest uses `config.settings_test` and refuses to start unless
  `TEST_PGDATABASE` is supplied, uses a dedicated test name, and differs from
  `PGDATABASE`. Use `scripts/run-tests-azure.ps1 -TestDatabaseName
  nivasopstestdb -PytestArguments --reuse-db` to set it
  for the process.
- Do not run test suites concurrently against the same Azure test database.
  Serialize them or give each developer, agent, and CI worker an isolated test
  database to prevent database-creation, migration, and data-contamination
  collisions.
- After a workflow slice passes its focused tests, run its affected test file
  or marker group with `--reuse-db` when the isolated test-database prerequisite
  is met. Record the slowest tests with `--durations=20` on a planned broader
  run before attempting test-structure optimizations.
- Before updating the delivery tracker, merging shared-contract work, accepting
  a migration, or preparing a release, run the relevant broader suite against
  a clean database without `--reuse-db`, including PostgreSQL RLS, composite
  constraint, and migration validation where applicable.
- Keep PostgreSQL and real migrations for authoritative tests. Do not replace
  them with SQLite, disable migrations, or broadly remove `transaction=True`.
  Audit `transaction=True` only test-by-test; retain it for RLS, locking,
  `on_commit`, and multi-connection behaviour.

For ticket changes, begin with the relevant test in
`backend/tests/test_ticket_api.py`, then run the complete ticket API suite when
the focused test passes and the change affects the shared ticket contract:

```powershell
Set-Location backend
& "..\.venv\Scripts\python.exe" -m pytest tests/test_ticket_api.py --reuse-db -q
```

Run editor diagnostics on every touched Python file. Use Django migration-drift
checking after model or migration changes. Do not claim an Azure validation or
deployment unless it actually occurred.

## Frontend Rules

- The frontend uses Next.js 16, React 19, and TypeScript. Read
  `frontend/AGENTS.md` before changing frontend code; it requires consulting
  the installed Next.js documentation for version-specific APIs.
- Build only against delivered backend contracts. Do not surface controls for
  unimplemented assignment, lifecycle, SLA, estimate, attachment, or approval
  behavior.
- Preserve persona boundaries, typed API clients, bearer and `X-Society-ID`
  headers, idempotency keys, expected-version protections, and canonical
  refreshes after mutations.
- Follow existing visual language and responsive patterns. Validate lint and
  production build, then use browser checks at desktop and 390x844 mobile
  sizes for changed user workflows, including no horizontal overflow.

## Documentation And Handoff

- Keep `docs/NIVASOPS_DELIVERY_TRACKER.md` truthful: mark work complete only
  after its exit evidence exists; list unresolved external decisions in the
  blocked register; do not convert blocked scope into completed work.
- `docs/AZURE_CLOUD_ARCHITECTURE.md` is an architecture and indicative cost
  proposal, not evidence of provisioned resources or an approved deployment.
- In each final handoff, state: what changed, validation actually run and its
  result, intentional deferrals, and any blocker that prevented completion.