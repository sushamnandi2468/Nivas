# Controlled Platform Support Session Contract

- Status: Implemented; production identity-provider activation pending
- Date: 2026-08-26
- Owners: NivasOps engineering and security
- Source: NivasOps Architecture Specification, sections 5.1, 5.4, 13.3, 14.3, and 17.1

## Context

Platform roles are global authorization grants, not tenant memberships. A role grant must never provide implicit access to a society. Support and audit users need narrowly scoped tenant access for a documented operational or compliance case, while platform administrators must not silently impersonate tenant personas.

The application does not yet issue production step-up claims. The support-session endpoint is implemented and fails closed unless a JWT contains the accepted claims; production use remains unavailable until identity-provider claim issuance satisfies this contract.

## Decision

### Eligibility

- `PLATFORM_SUPPORT` may request a read-only session for one active society.
- `PLATFORM_AUDITOR` may request a read-only session for one active society when an audit case exists.
- `PLATFORM_ADMIN` receives no tenant-session capability from the administrator role.
- The selected platform-role grant, user account, JWT session version, and support session must remain active and current for every request.
- A platform session sets a distinct `platform_support` or `platform_auditor` persona. It never impersonates staff, resident, committee, technician, or vendor personas.

### Step-Up Authentication

- Session creation requires a JWT `auth_time` no older than five minutes.
- The JWT `amr` claim must contain at least one approved phishing-resistant or second-factor method. The initial accepted values are `mfa`, `otp`, and `hwk`; the identity-provider contract may narrow this set.
- Missing, malformed, future-dated, or stale claims fail closed with `403`.
- Recovery actions require a fresh step-up check at action time and cannot rely only on the session-creation check.
- Test-only token construction may supply these claims directly. Production issuance remains blocked by the deferred public-authentication decision until the identity provider and claim mapping are approved.

### Session Scope And Lifetime

- `POST /api/v1/platform/support-sessions` requires `society`, `case_reference`, `reason`, and requested duration.
- `case_reference` is 8-128 characters; `reason` is 20-1000 characters. Both are stored with the session and its immutable events.
- Duration is between five and 30 minutes. The server computes expiry and never accepts an absolute client-controlled expiry.
- Only one active support session per user is permitted. Starting a new session requires ending the previous one; expired sessions are closed before a replacement is created.
- The caller sends the returned session identifier in `X-Support-Session-ID` together with the normal bearer token and `X-Society-ID`.
- The session identifier, authenticated user, role grant, and society header must all match. A guessed identifier cannot transfer access between users or societies.
- `DELETE /api/v1/platform/support-sessions/{id}` ends the caller's session early. Role revocation, role expiry, user deactivation, JWT session revocation, and session expiry invalidate access immediately.

### Read And Mutation Policies

- Initial sessions are read-only. The first allowlist is current-society metadata plus blocks, units, and common areas. Membership, invitation, attachment, export, notification, and resident-contact data are denied.
- Safe HTTP methods are not sufficient by themselves; every tenant view must explicitly opt into platform-session reads.
- Tenant create/update/delete routes reject platform-session personas even when the same user has a global platform role.
- Recovery mutations never pass through ordinary tenant serializers. They use named `POST /api/v1/platform/recovery-actions/{action}` services with an explicit action allowlist, object authorization, fresh step-up, case reference, reason/proof, idempotency key, state-version precondition, row locking, and an atomic audit event.
- No recovery action is enabled before its ticket-domain service and immutable audit event exist. Bulk cross-tenant queries, role grants, audit mutation, and unrestricted attachment access remain prohibited.

### Immutable Events

- The session feature adds an append-only platform-access event table before enabling session creation.
- Events include session requested/started, tenant route accessed, access denied, session ended, session expired, and recovery action attempted/completed/denied.
- Every event stores timestamp, actor, platform role, society, support-session identifier, case reference, reason, correlation ID, event type, route/action, outcome, and safe metadata.
- The application can insert and select events but cannot update or delete them. PostgreSQL constraints or triggers reject mutation by the normal application path.
- Request bodies, bearer tokens, OTP values, attachment contents, secrets, and unnecessary personal data are never stored in event metadata.

### Client And Operational Controls

- Every response made through a platform session identifies the platform persona, selected society, case reference, read-only mode, and expiry so the client can render a persistent warning banner.
- Platform-session data is excluded from offline storage and shared caches.
- Logs and metrics include a safe session/correlation identifier but not the reason text or sensitive case content.
- Alerts cover repeated denied starts, cross-society header mismatches, stale step-up attempts, expired-session use, and recovery-action denials.

## Accepted Controls

Implementation proceeds with these controls:

1. The five-minute step-up freshness window and accepted `amr` values.
2. The five-to-30-minute session duration range.
3. The initial non-personal directory read allowlist.
4. The rule that recovery actions remain unavailable until their Phase 4 domain and immutable-audit services exist.
5. The append-only event fields and database mutation protections.

The event foundation is delivered by `platform_access.0002`, and the constrained session lifecycle is delivered by `platform_access.0003`. Session creation remains fail-closed until the production identity provider supplies the accepted step-up claims.

## Consequences

- Platform-role grants remain useful for platform administration while tenant support access stays fail-closed.
- Support-session runtime delivery is complete; production activation remains sequenced after step-up claim issuance.
- Initial support access is intentionally narrow; additional read resources and every recovery action require explicit policy and tests.