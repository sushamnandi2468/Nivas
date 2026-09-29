# NivasOps Defect & Issue Tracker

This document records defects, UX regressions, integration hurdles, and operational issues identified during end-to-end testing of NivasOps.

---

## Summary of Defects

| Defect ID | Title | Component | Severity | Status | Discovered In |
|---|---|---|---|---|---|
| **DEF-001** | Unauthenticated `/app` renders `<SessionGate>` fallback instead of redirecting to `/` | Frontend (`AppShell`) | Medium | **Resolved & Verified** | Flow 1 Browser Test |
| **DEF-002** | API Base URL double `/api/v1` prefixing when configured with `/api/v1` | Frontend (`nivasops-api.ts`) | Medium | **Resolved & Verified** | Flow 1 Browser Test |
| **DEF-003** | Resident identifier naming discrepancy in test execution (`.palm` vs unit occupancy) | Test / Documentation | Low | **Resolved & Verified** | Flow 1 Browser Test |
| **DEF-004** | SMS / Quick OTP gateway unavailable without provisioned phone/gateway | Auth / SMS Gateway | Low | **Deferred** | Flow 1 Browser Test |
| **DEF-005** | Dispatch dialog shows technician as truncated UUID instead of name/email | Frontend (`operations/service/[id]/page.tsx`) | Low | **Resolved & Verified** | Flow 3 API Test |

---

## Detailed Defect Records

### DEF-001: Unauthenticated `/app` Direct Navigation Renders `<SessionGate>` Fallback Instead of Redirecting to Login

- **Severity:** Medium
- **Component:** `frontend/src/app/app/app-shell.tsx`, `frontend/src/app/app/session-context.tsx`
- **Status:** **Resolved & Verified**
- **Reported Date:** 2026-09-04
- **Resolved Date:** 2026-09-04
- **Discovered In:** Flow 1 (Authentication & Role-Based Routing)
- **Description:**
  When a user directly navigated to `http://localhost:3000/app` or `http://localhost:3000/app/operations` without an active session in `sessionStorage` (or after clicking "End session"), the layout rendered `<SessionGate />` ("Connect your workspace"). This developer-facing fallback prompted for `apiBaseUrl`, `societyId`, `accessToken`, and `displayName`. If invalid or placeholder values were submitted, the shell loaded but DRF requests failed with `401 Unauthorized: Given token not valid for any token type`.
- **Expected Behavior:**
  Unauthenticated access to any route under `/app` should automatically route the browser back to `/` (the public sign-in page) via `router.replace("/")`. Clicking "End session" must cleanly clear `sessionStorage` and navigate back to `/`.
- **Resolution:**
  Implemented a route guard `useEffect` in `frontend/src/app/app/app-shell.tsx` that detects `!session` and immediately calls `router.replace("/")`, showing a styled intermediate loading indicator. Updated "End session" handler to call `disconnect()` and `router.replace("/")`.
- **Verification Evidence:**
  1. Direct navigation to `http://localhost:3000/app` without session -> Automatically redirected to `http://localhost:3000/`. (Verified in browser retest step 1).
  2. Direct navigation to `http://localhost:3000/app/operations` without session -> Automatically redirected to `http://localhost:3000/`. (Verified in browser retest step 5).
  3. Clicking "End session" in FM and Resident sidebars -> Cleanly detached session and redirected to `http://localhost:3000/`.

---

### DEF-002: API Base URL Double `/api/v1` Prefixing

- **Severity:** Medium
- **Component:** `frontend/src/lib/nivasops-api.ts`, `frontend/src/app/page.tsx`
- **Status:** **Resolved & Verified**
- **Reported Date:** 2026-09-04
- **Resolved Date:** 2026-09-04
- **Discovered In:** Flow 1 (Authentication & Role-Based Routing)
- **Description:**
  `nivasops-api.ts` constructed endpoints via `${session.apiBaseUrl.replace(/\/$/, "")}${path}` and `${apiBaseUrl.replace(/\/+$/, "")}/api/v1/auth/...`. If the environment variable `NEXT_PUBLIC_API_BASE_URL` or user input included `/api/v1` (e.g. `http://127.0.0.1:8000/api/v1`), requests double-prefixed to `http://127.0.0.1:8000/api/v1/api/v1/...`, returning 404.
- **Expected Behavior:**
  The API client should normalize the API base URL by stripping any trailing slashes and any trailing `/api/v1` or `/api` segments, ensuring endpoints are always formed cleanly as `${normalizedBase}/api/v1/...`.
- **Resolution:**
  Introduced exported helper function `normalizeApiBaseUrl(url?: string | null): string` in `nivasops-api.ts` which strips trailing slashes and `/api/v1` or `/api` suffixes. Applied this helper across all API endpoints, auth endpoints (`loginWithEmailPassword`, `activateInvitation`, `refreshAuthSession`, `logoutAuthSession`), and the sign-in form handler.
- **Verification Evidence:**
  Login and subsequent API calls (`listTickets`, operations queues) succeeded without route duplication errors. Type checks (`npx tsc --noEmit`) and linter (`eslint`) passed cleanly.

---

### DEF-003: Resident Identifier Discrepancy in Test Documentation and Execution

- **Severity:** Low
- **Component:** `docs/TESTING_AND_USER_FLOWS_GUIDE.md`
- **Status:** **Resolved & Verified**
- **Reported Date:** 2026-09-04
- **Resolved Date:** 2026-09-04
- **Discovered In:** Flow 1 (Authentication & Role-Based Routing)
- **Description:**
  In Flow 1 initial automated test execution, the agent attempted to use `resident.palm@nivas.local`. In the Nivas tenancy schema, administrative and staff accounts use society-scoped usernames (`fm.palm`, `helpdesk.palm`, `president.palm`), whereas resident accounts are unit-occupancy-bound (`resident.a101@nivas.local`, `resident.a102@nivas.local`, `resident.b201@nivas.local`).
- **Resolution:**
  Confirmed valid seeded accounts in `seed_test_data.py`. Updated testing flows and executed browser retest with `resident.a101@nivas.local`.
- **Verification Evidence:**
  `resident.a101@nivas.local` authenticated cleanly with `TestPass@123`. The Resident Desk at `http://localhost:3000/app` rendered Unit A-101's active requests (`Late Night Noise in Clubhouse`, `Leaking Kitchen Tap Draft`) without any authentication or authorization errors.

---

### DEF-004: Quick OTP Phone Sign-in Deferred in Development

- **Severity:** Low (Feature Deferred)
- **Component:** `frontend/src/app/page.tsx`
- **Status:** **Deferred**
- **Reported Date:** 2026-09-04
- **Discovered In:** Flow 1 (Authentication & Role-Based Routing)
- **Description:**
  The "Quick OTP" sign-in tab on the landing page is not backed by an active telephony provider in local development and shows a preview notification.
- **Status Comment:**
  Per user instruction, OTP is excluded for now as phone numbers and telephony are not yet configured. Password-based authentication remains the authoritative flow.

---

### DEF-005: Dispatch Dialog Shows Technician as Truncated UUID Instead of Email

- **Severity:** Low
- **Component:** `frontend/src/app/app/operations/service/[id]/page.tsx`, `backend/apps/tenancy/serializers.py`
- **Status:** **Resolved & Verified**
- **Reported Date:** 2026-09-04
- **Resolved Date:** 2026-09-04
- **Discovered In:** Flow 3 (Facility Manager Ticket Assignment)
- **Description:**
  The FM dispatch dialog's in-house technician dropdown displayed options as `Technician · {id.slice(0,8)} · (cap)` — showing only a truncated 8-character UUID prefix. The FM had no way to identify which UUID corresponds to which person (e.g., Suresh Patil vs. Ramesh Kumar).
- **Root Cause:**
  `TechnicianProfileSerializer` did not expose the linked user's email. The `user` field was a raw UUID PrimaryKeyRelatedField with no name annotation.
- **Resolution:**
  1. Added `user_email = serializers.EmailField(source="user.email", read_only=True)` to `TechnicianProfileSerializer` and included it in the `fields` tuple.
  2. Updated the `TechnicianProfile` TypeScript type in `nivasops-api.ts` to include `user_email: string | null`.
  3. Updated the dispatch dropdown option label to show `{user_email} · ({cap})` with fallback to `{id.slice(0,8)}`.
- **Verification Evidence:**
  `GET /api/v1/directory/technicians/` now returns:
  ```json
  [
    {"user_email": "tech.ramesh@nivas.local", "current_active_tickets_count": 1, "max_active_tickets": 5, ...},
    {"user_email": "tech.suresh@nivas.local", "current_active_tickets_count": 1, "max_active_tickets": 4, ...}
  ]
  ```
  Dispatch dropdown shows `tech.suresh@nivas.local · (0/4 active)` before assignment. TypeScript check (`npx tsc --noEmit`) passed with exit code 0.

---

## Flow 3 Validation Record: FM In-House Assignment (2026-09-04)

**Ticket**: `PALM-MEADOWS-2026-000001` — Master Bedroom Switch Sparking (P2)
**Assigned To**: `tech.suresh@nivas.local` (Suresh Patil, cap 4)

| Step | Expected | Actual | Result |
|---|---|---|---|
| FM login | Redirect to `/app/operations` | ✅ Authenticated, token issued | **PASS** |
| Technician API | Returns `user_email` per technician | ✅ `tech.ramesh`, `tech.suresh` visible | **PASS** |
| Assign in-house | Status → `ASSIGNED`, assignment state → `OFFERED` | ✅ `status: ASSIGNED`, `state: OFFERED` | **PASS** |
| State version increment | `state_version` increments from 2 to 3 | ✅ `state_version: 3` | **PASS** |
| Capacity tracking | Suresh workload 0/4 → 1/4 after assignment | ✅ `tech.suresh: 1/4 active` | **PASS** |
| Ramesh workload unchanged | Stays at 1/5 | ✅ `tech.ramesh: 1/5 active` | **PASS** |
| Idempotency enforcement | Requires `Idempotency-Key` header | ✅ Enforced by backend | **PASS** |
| Audit event | `event_id` returned in response | ✅ Event UUID returned | **PASS** |

**Overall Flow 3 Result: ✅ PASSED** (API-level validation; browser UI validation pending rate limit reset)

---

## Flow 4 Validation Record: In-House Technician Workflow (2026-09-04)

**Ticket**: `PALM-MEADOWS-2026-000001` — Master Bedroom Switch Sparking (P2)  
**Technician**: `tech.suresh@nivas.local` (Suresh Patil)  
**Resident / Creator**: `resident.a102@nivas.local` (Divya Nair, Unit A-102)  

| Step | Action & Endpoint | Actor | Expected | Actual | Result |
|---|---|---|---|---|---|
| 1 | Authenticate Technician | `tech.suresh@nivas.local` | 200 OK, JWT issued | ✅ Authenticated with `TestPass@123` | **PASS** |
| 2 | Accept Assignment (`POST .../accept/`) | Suresh Patil | Status `ACCEPTED`, version 3 → 4, assignment state `ACCEPTED` | ✅ `status: ACCEPTED`, `state_version: 4`, event `21070ecf-...` | **PASS** |
| 3 | Start Work (`POST .../start/`) | Suresh Patil | Status `IN_PROGRESS`, version 4 → 5 | ✅ `status: IN_PROGRESS`, `state_version: 5`, event `c324e791-...` | **PASS** |
| 4 | Request Completion (`POST .../request-completion/`) | Suresh Patil | Status `PENDING_RESIDENT_CONFIRMATION`, version 5 → 6, challenge created | ✅ `status: PENDING_RESIDENT_CONFIRMATION`, `state_version: 6`, challenge `ceca3d92-...` | **PASS** |
| 5 | Anti-Fraud OTP Capsule Storage | Backend / Key Vault | 6-digit OTP stored in Key Vault capsule | ✅ Capsule `nivasops-completion-otp-ceca3d92...` stored & retrieved (`906486`) | **PASS** |
| 6 | Resident Verify Completion (`POST .../verify-completion/`) | `resident.a102@nivas.local` | Status `RESOLVED`, version 6 → 7 | ✅ `status: RESOLVED`, `state_version: 7`, event `6b2a60c9-...` | **PASS** |
| 7 | Capacity Release Verification (`GET .../directory/technicians/`) | Facility Manager | Suresh capacity decrements 1/4 → 0/4 | ✅ `tech.suresh: 0/4 active`, `tech.ramesh: 1/5 active` | **PASS** |
| 8 | Audit Timeline Verification | System | Immutable `TicketEvent` chain v2 → v7 | ✅ Complete unbroken audit log with actors and state transitions | **PASS** |

**Overall Flow 4 Result: ✅ PASSED** (Full lifecycle from assignment acceptance to completion verification and capacity release validated cleanly via API)

---

## Flow 5 Validation Record: Vendor Dispatcher & Field Worker Allocation (2026-09-04)

**Ticket**: `PALM-MEADOWS-2026-000005` — Kitchen Sink Clogged (P3)  
**Vendor Contract**: `b65a55b8-d17c-4612-b048-d73c6d5e7a86` (Apex Facility Management Pvt Ltd, capacity 10)  
**Vendor Dispatcher**: `dispatcher.apex@nivas.local`  
**Field Worker**: `worker.vikram@nivas.local` (Vikram Singh)  
**Resident / Creator**: `resident.a101@nivas.local` (Rohan Mehta, Unit A-101)  

| Step | Action & Endpoint | Actor | Expected | Actual | Result |
|---|---|---|---|---|---|
| 1 | FM Assigns to Vendor (`POST .../assign-vendor/`) | `fm.palm@nivas.local` | Status `ASSIGNED`, version 2 → 3, contract capacity increments 0/10 → 1/10 | ✅ `status: ASSIGNED`, `state_version: 3`, capacity `1/10`, event `5eb5692a-...` | **PASS** |
| 2 | Dispatcher Allocates Worker (`POST .../allocate-vendor-worker/`) | `dispatcher.apex@nivas.local` | Status `ASSIGNED`, version 3 → 4, worker allocation created in `ALLOCATED` state | ✅ `status: ASSIGNED`, `state_version: 4`, allocation `3fec1cb9-...` state `ALLOCATED`, event `4467eb08-...` | **PASS** |
| 3 | Worker Accepts Allocation (`POST .../accept-vendor-worker/`) | `worker.vikram@nivas.local` | Status `ACCEPTED`, version 4 → 5, assignment & allocation state `ACCEPTED` | ✅ `status: ACCEPTED`, `state_version: 5`, assignment & allocation `ACCEPTED`, event `e7a8c224-...` | **PASS** |
| 4 | Worker Starts Work (`POST .../start/`) | `worker.vikram@nivas.local` | Status `IN_PROGRESS`, version 5 → 6 | ✅ `status: IN_PROGRESS`, `state_version: 6`, event `c9681686-...` | **PASS** |
| 5 | Worker Requests Completion (`POST .../request-completion/`) | `worker.vikram@nivas.local` | Status `PENDING_RESIDENT_CONFIRMATION`, version 6 → 7, challenge created | ✅ `status: PENDING_RESIDENT_CONFIRMATION`, `state_version: 7`, challenge `70eb1c7d-...`, event `16376eb1-...` | **PASS** |
| 6 | Anti-Fraud OTP Capsule Storage | Backend / Key Vault | 6-digit OTP stored in Key Vault capsule | ✅ Capsule `nivasops-completion-otp-70eb1c7d...` stored & retrieved (`953623`) | **PASS** |
| 7 | Resident Verify Completion (`POST .../verify-completion/`) | `resident.a101@nivas.local` | Status `RESOLVED`, version 7 → 8 | ✅ `status: RESOLVED`, `state_version: 8`, event `57114940-...` | **PASS** |
| 8 | Contract Capacity & Allocation Release | Facility Manager / System | Contract capacity decrements 1/10 → 0/10, assignment & allocation state → `ENDED` | ✅ Contract capacity `0/10`, assignment & allocation state `ENDED` (`Completed by resident confirmation`) | **PASS** |
| 9 | Audit Timeline Verification | System | Immutable `TicketEvent` chain v2 → v8 | ✅ Complete unbroken audit log with actors, roles, and correlation IDs | **PASS** |

**Overall Flow 5 Result: ✅ PASSED** (Full vendor dispatch lifecycle: contract capacity accounting, dispatcher allocation, worker self-acceptance, execution, completion verification, and capacity release cleanly validated via API)

---

## Flow 6 Validation Record: Governance Issue Review & Action Record (2026-09-04)

**Ticket**: `PALM-MEADOWS-2026-000004` — Late Night Noise in Clubhouse (P3, Civic/Governance)  
**Facility Manager / Reviewer**: `fm.palm@nivas.local`  
**Resident / Creator**: `resident.a101@nivas.local` (Rohan Mehta, Unit A-101)  

| Step | Action & Endpoint | Actor | Expected | Actual | Result |
|---|---|---|---|---|---|
| 1 | FM Authenticates | `fm.palm@nivas.local` | 200 OK, JWT issued | ✅ Authenticated with `TestPass@123` | **PASS** |
| 2 | Begin Governance Review (`POST .../begin-review/`) | `fm.palm@nivas.local` | Status `UNDER_REVIEW`, version 2 → 3, reviewer assigned | ✅ `status: UNDER_REVIEW`, `state_version: 3`, review assignment `01ff8b5e-...`, event `eca0f084-...` | **PASS** |
| 3 | Record Governance Action (`POST .../record-action/`) | `fm.palm@nivas.local` | Status `ACTION_TAKEN`, version 3 → 4, action record created | ✅ `status: ACTION_TAKEN`, `state_version: 4`, action record `d6b70cee-...`, event `90baf0d6-...` | **PASS** |
| 4 | Resident Visibility Check (`GET .../governance-tickets/{id}/`) | `resident.a101@nivas.local` | Ticket visible with `status: ACTION_TAKEN`, no OTP required | ✅ Resident sees `status: ACTION_TAKEN`, `version: 4` cleanly | **PASS** |
| 5 | Audit Timeline Verification | System | Immutable `TicketEvent` chain v2 → v4 | ✅ Complete unbroken audit log with actor identities, personas, and resolution reasons | **PASS** |

**Overall Flow 6 Result: ✅ PASSED** (Civic/governance lifecycle from submission to formal review and recorded resolution action validated cleanly via API with complete audit evidence)

---

## Flow 7 Validation Record: Deduplication & Ticket Merging / Unmerging (2026-09-04)

**Primary Ticket**: `PALM-MEADOWS-2026-000006` — Leaking Kitchen Tap (P3, Unit A-101)  
**Secondary Ticket**: `PALM-MEADOWS-2026-000007` — Kitchen Tap Dripping Continuously (P3 Duplicate, Unit A-101)  
**Facility Manager**: `fm.palm@nivas.local`  
**Resident / Creator**: `resident.a101@nivas.local` (Rohan Mehta, Unit A-101)  

| Step | Action & Endpoint | Actor | Expected | Actual | Result |
|---|---|---|---|---|---|
| 1 | Resident Submits Drafts | `resident.a101@nivas.local` | Both tickets submitted into `SUBMITTED` state (v2) | ✅ `000006` and `000007` in `SUBMITTED` state | **PASS** |
| 2 | FM Merges Secondary into Primary (`POST .../merge/`) | `fm.palm@nivas.local` | Secondary status `MERGED` (v3), primary version incremented (v3), active `TicketMergeRecord` created | ✅ Primary `SUBMITTED` (v3), Secondary `MERGED` (v3), merge record `df508352-...` active | **PASS** |
| 3 | SLA Cycle Termination on Merge | System | Secondary ticket SLA cycle ends with outcome `MERGED` | ✅ Cycle 1 ended with outcome `MERGED` | **PASS** |
| 4 | Audit Evidence on Merge | System | `TICKET_MERGE_ATTACHED` on primary, `TICKET_MERGED` on secondary | ✅ Immutable events recorded on both tickets with duplicate audit reason | **PASS** |
| 5 | FM Unmerges within 24h Window (`POST .../unmerge/`) | `fm.palm@nivas.local` (Step-Up Authenticated) | Secondary restored to `SUPERVISOR_TRIAGE` (v4), primary version incremented (v4), merge record `is_active=False` | ✅ Secondary restored to `SUPERVISOR_TRIAGE` (v4), primary `SUBMITTED` (v4), record deactivated | **PASS** |
| 6 | Fresh SLA Cycle Renewal upon Unmerge | System | New uncompleted SLA cycle initiated for restored secondary ticket | ✅ Cycle 2 created with active state (`outcome=""`, `ended_at=None`) | **PASS** |
| 7 | Audit Evidence on Unmerge | System | `TICKET_UNMERGED` emitted on both primary and secondary tickets | ✅ Immutable events recorded on both tickets with unmerge audit reason | **PASS** |

**Overall Flow 7 Result: ✅ PASSED** (Atomic deduplication merge, SLA outcome termination, step-up authorized 24-hour recovery unmerge, and fresh SLA renewal validated cleanly via API with full audit trails)

---

## Flow 8 Validation Record: Multi-Tenant & RLS Cross-Society Isolation (2026-09-05)

**Societies**:  
- `PALM-MEADOWS` (`11111111-1111-1111-1111-111111111111`)  
- `GREEN-VALLEY` (`22222222-2222-2222-2222-222222222222`)  
**Target Probe Ticket**: `PALM-MEADOWS-2026-000001` (`c14d868b-4c53-47cb-9ade-44cac83b5915`)  
**Actors Tested**:  
- `fm.green@nivas.local` (Facility Manager, Green Valley)  
- `resident.green@nivas.local` (Preeti Joshi, Resident Unit 101, Green Valley)  

| Step | Action & Probe | Actor | Expected | Actual | Result |
|---|---|---|---|---|---|
| 1 | Authenticate in Green Valley | `fm.green@nivas.local` | 200 OK with `X-Society-ID: 2222...` | ✅ Authenticated with `TestPass@123`, JWT issued | **PASS** |
| 2 | Query Service Tickets in Green Valley | `fm.green@nivas.local` | 200 OK, returns only Green Valley tickets (0 Palm tickets) | ✅ 0 tickets returned, zero cross-tenant contamination | **PASS** |
| 3 | Direct Fetch Palm Ticket under Green Context | `fm.green@nivas.local` | 404 Not Found (PostgreSQL RLS block) | ✅ `404 Not Found` (`No Ticket matches the given query`) | **PASS** |
| 4 | Switch `X-Society-ID` to Palm Meadows | `fm.green@nivas.local` | 403 Forbidden (Tenancy middleware check) | ✅ `403 Forbidden` (`No active membership in this society`) | **PASS** |
| 5 | Cross-Direct Fetch with Palm Header | `fm.green@nivas.local` | 403 Forbidden | ✅ `403 Forbidden` (`No active membership in this society`) | **PASS** |
| 6 | Resident Cross-Tenant Fetch Probe | `resident.green@nivas.local` | 404 Not Found under Green context | ✅ `404 Not Found` | **PASS** |
| 7 | Resident Cross-Tenant Header Switch Probe | `resident.green@nivas.local` | 403 Forbidden under Palm header | ✅ `403 Forbidden` (`No active membership in this society`) | **PASS** |

**Overall Flow 8 Result: ✅ PASSED** (Zero cross-tenant data leakage: Row-Level Security at PostgreSQL database layer and Tenancy Middleware at Django layer strictly enforce multi-tenant isolation across all personas)
