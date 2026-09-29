# ADR-006: Defer User-Facing Login Workflows

- Status: Accepted
- Date: 2026-08-26
- Owners: NivasOps engineering

## Context

The application needs real authenticated principals to prove tenant authorization and PostgreSQL RLS, but implementing login now would couple core workflow development to unsettled OTP, password, recovery, provider, abuse-control, and public API contracts.

Moving all authentication to the end is unsafe because tenant APIs must be developed and tested with JWT validation, active membership checks, session revocation, and explicit society context from their first release.

## Decision

Keep the authentication enforcement foundation in every tenant API:

- JWT signature, issuer, audience, expiry, and token-type validation.
- Ten-minute access tokens.
- Session-version and revocation-time checks.
- Required `X-Society-ID` and active time-bounded membership resolution.
- Transaction-local PostgreSQL RLS context.
- Refresh-token rotation and persistent blacklist storage.

Defer these user-facing workflows until their OpenAPI contracts and provider choices are approved:

- OTP request, delivery, resend, verification, and abuse controls.
- Password login and password recovery.
- Refresh and logout HTTP endpoints.
- Session-management UI and AUTH-01 backend wiring.
- Production notification-provider integration.

## Development Access

Automated tests mint tokens directly through `SessionRefreshToken`. Manual integrated testing uses the `dev_session` Django management command, which creates or reuses an explicitly selected development identity and emits a real short-lived access token plus its society identifier.

The command is not an HTTP endpoint and is excluded from OpenAPI. It fails closed unless all of these conditions hold:

- Django `DEBUG` is enabled.
- `ALLOW_DEV_SESSION_BOOTSTRAP=true` is explicitly supplied for the process.
- A valid society registration code, E.164 phone number, and supported staff role are supplied.

Production deployment configuration must never enable this flag. No application code may weaken JWT, membership, object-policy, or RLS enforcement for development sessions.

## Consequences

- Core tenant workflows can be tested without waiting for login providers or OTP delivery.
- Manual sessions exercise the same JWT, membership, and RLS path as eventual login sessions.
- The final authentication slice must still define and approve request/response schemas, error codes, rate limits, refresh rotation behavior, reuse detection, logout semantics, and provider failure handling.
- Before production release, CI and deployment checks must prove the development-session flag is disabled.

## Revisit Trigger

Implement the deferred workflows after core society, membership, and ticket journeys stabilize and before external pilot users receive access. Remove the manual development-session dependency once the approved login and refresh endpoints are available.