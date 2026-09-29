# NivasOps Testing and User Flows Guide

This document is the authoritative test matrix and operational test manual for NivasOps. It details all seeded test data, user accounts across distinct roles, society UUIDs, and executable test flows covering the full lifecycle of the platform.

---

## 1. Test Societies & Infrastructure

| Society Name | Society UUID | Registration Code | Timezone | Structure |
|---|---|---|---|---|
| **Palm Meadows Residency** | `11111111-1111-1111-1111-111111111111` | `PALM-MEADOWS` | `Asia/Kolkata` | • Tower A (`BLK-A`): A-101, A-102, A-201, A-202<br>• Tower B (`BLK-B`): B-101, B-102, B-201, B-202<br>• Common Areas: Clubhouse, Pool Deck, Main Lobby |
| **Green Valley Enclave** | `22222222-2222-2222-2222-222222222222` | `GREEN-VALLEY` | `Asia/Kolkata` | • Block 1 (`BLK-1`): Unit 101, Unit 102<br>• Common Areas: Central Garden |

---

## 2. Test Personas & Credentials

All seeded accounts share the default test password:
> **Password for all users**: `TestPass@123`

### Palm Meadows Residency (`11111111-1111-1111-1111-111111111111`)

| Role / Persona | Name | Email | Mobile Phone | Unit / Association | Workspace Route |
|---|---|---|---|---|---|
| **Facility Manager** | Priya Sharma | `fm.palm@nivas.local` | `+919800000001` | Society Staff (FM) | `/app/operations` |
| **Helpdesk Operator** | Neha Gupta | `helpdesk.palm@nivas.local` | `+919800000010` | Society Staff (Helpdesk) | `/app/operations` |
| **Resident (Owner)** | Rohan Mehta | `resident.a101@nivas.local` | `+919800000002` | Unit `A-101` (Primary Owner) | `/app` |
| **Resident (Tenant)** | Divya Nair | `resident.a102@nivas.local` | `+919800000003` | Unit `A-102` (Tenant) | `/app` |
| **Resident (Owner)** | Karthik Sundaram | `resident.b201@nivas.local` | `+919800000012` | Unit `B-201` (Primary Owner) | `/app` |
| **In-House Technician** | Ramesh Kumar | `tech.ramesh@nivas.local` | `+919800000004` | Technician Profile (Cap: 5) | API / Field App |
| **In-House Technician** | Suresh Patil | `tech.suresh@nivas.local` | `+919800000013` | Technician Profile (Cap: 4) | API / Field App |
| **Committee President** | Rajesh Iyer | `president.palm@nivas.local` | `+919800000007` | Management Committee | `/app/operations` |
| **Committee Treasurer** | Ananya Rao | `treasurer.palm@nivas.local` | `+919800000011` | Management Committee | `/app/operations` |
| **Vendor Dispatcher** | Anita Roy | `dispatcher.apex@nivas.local` | `+919811111102` | Apex Facility Management | API / Vendor Portal |
| **Vendor Field Worker** | Vikram Singh | `worker.vikram@nivas.local` | `+919811111103` | Apex Facility Management | API / Field App |

### Green Valley Enclave (`22222222-2222-2222-2222-222222222222`) - Cross-Tenant Testing

| Role / Persona | Name | Email | Mobile Phone | Unit / Association | Workspace Route |
|---|---|---|---|---|---|
| **Facility Manager** | Arun Desai | `fm.green@nivas.local` | `+919800000008` | Society Staff (FM) | `/app/operations` |
| **Resident (Owner)** | Preeti Joshi | `resident.green@nivas.local` | `+919800000009` | Unit `101` (Primary Owner) | `/app` |

---

## 3. Pre-Seeded Tickets Matrix

| Ticket Number | Title | Workflow | Status | Priority | Location | Creator |
|---|---|---|---|---|---|---|
| *None (Draft)* | Leaking Kitchen Tap Draft | `SERVICE` | `DRAFT` | `P3` | Unit `A-101` | Rohan Mehta (`resident.a101@nivas.local`) |
| `PALM-MEADOWS-2026-000001` | Master Bedroom Switch Sparking | `SERVICE` | `SUBMITTED` | `P2` | Unit `A-102` | Divya Nair (`resident.a102@nivas.local`) |
| `PALM-MEADOWS-2026-000002` | Bathroom Main Pipe Leak | `SERVICE` | `IN_PROGRESS` | `P1` | Unit `B-201` | Karthik Sundaram (`resident.b201@nivas.local`)<br>*(Assigned to tech.ramesh)* |
| `PALM-MEADOWS-2026-000003` | Balcony Light Fixture Replaced | `SERVICE` | `RESOLVED` | `P1` | Unit `A-101` | Rohan Mehta (`resident.a101@nivas.local`)<br>*(Verified via OTP & 5★ Rated)* |
| `PALM-MEADOWS-2026-000004` | Late Night Noise in Clubhouse | `GOVERNANCE` | `SUBMITTED` | `P3` | None (Civic) | Rohan Mehta (`resident.a101@nivas.local`) |

---

## 4. Test Flows Catalog

### Flow 1: Authentication & Role-Based Routing
- **Objective**: Verify that the login page validates credentials against Azure PostgreSQL and routes each persona to their dedicated workspace.
- **Steps**:
  1. Open [http://localhost:3000](http://localhost:3000).
  2. Test **Facility Manager Login**:
     - Email: `fm.palm@nivas.local`
     - Password: `TestPass@123`
     - Society UUID: `11111111-1111-1111-1111-111111111111`
     - Persona: Select **Facility Manager**
     - Click **Sign in with Password**.
     - **Expected Outcome**: Redirected to `/app/operations` displaying Society Overview, Service Inbox with 4 tickets, and Governance Inbox with 1 ticket.
  3. Logout or clear session, then test **Resident Login**:
     - Email: `resident.a101@nivas.local`
     - Password: `TestPass@123`
     - Society UUID: `11111111-1111-1111-1111-111111111111`
     - Persona: Select **Resident**
     - Click **Sign in with Password**.
     - **Expected Outcome**: Redirected to `/app` displaying Resident Dashboard with only their 2 tickets (`Leaking Kitchen Tap Draft` and resolved `PALM-MEADOWS-2026-000003`).

---

### Flow 2: Resident Service Ticket Creation & Submission
- **Objective**: Test the two-step draft-then-submit lifecycle with SLA calculation.
- **Steps**:
  1. Sign in as `resident.a101@nivas.local`.
  2. Navigate to **New Ticket Studio** (`/app`).
  3. Select Workflow: **Service**.
  4. Select Category: **Plumbing** -> Subcategory: **Tap / Faucet Repair**.
  5. Select Location: Unit `A-101`.
  6. Title: `Kitchen Sink Clogged`.
  7. Description: `Water is draining very slowly and backing up into the basin.`
  8. Click **Create Draft**.
     - **Expected Outcome**: Ticket is created in `DRAFT` status, `ticket_number` is blank, `state_version` is 1.
  9. Review the summary and click **Submit Ticket**.
     - **Expected Outcome**: Status updates to `SUBMITTED`, canonical ticket number is assigned (`PALM-MEADOWS-2026-000005`), `SLACycle` is computed using the business calendar.

---

### Flow 3: Facility Manager Ticket Assignment (In-House vs Vendor)
- **Objective**: Verify dispatcher assignment and technician capacity tracking.
- **Steps**:
  1. Sign in as `fm.palm@nivas.local`.
  2. Open **Service Inbox** at `/app/operations`.
  3. Click ticket `PALM-MEADOWS-2026-000001` (Master Bedroom Switch Sparking).
  4. View available assignment targets:
     - In-house technicians: `Ramesh Kumar` (Capacity: 1/5 used), `Suresh Patil` (Capacity: 0/4 used).
     - Active vendors: `Apex Facility Management Pvt Ltd` (Contract: `APEX-2026-MAIN`).
  5. Choose **Assign In-House Technician** -> Select `Suresh Patil`.
  6. Submit assignment.
     - **Expected Outcome**: Ticket status updates to `ASSIGNED`, Suresh Patil's active ticket workload increments to 1, audit event `TICKET_ASSIGNMENT_OFFERED` is logged.

---

### Flow 4: In-House Technician Workflow & OTP Resolution
- **Objective**: Complete an in-house ticket with real-time OTP challenge generation and resident verification.
- **Steps**:
  1. As technician `tech.suresh@nivas.local`, accept assignment and start work.
  2. When work is complete, invoke `request_service_ticket_completion`:
     - System generates 6-digit OTP, stores secure capsule in Redis (`nivascache`), and sends email via Azure Communication Services.
  3. Resident Rohan enters the OTP.
  4. **Expected Outcome**: Ticket transitions to `RESOLVED`, technician workload decrements, prompt to rate service (1-5 stars).

---

### Flow 5: Vendor Dispatcher & Field Worker Allocation
- **Objective**: Test contract capacity enforcement, dispatcher delegation, and worker acceptance.
- **Steps**:
  1. Facility Manager assigns ticket to vendor `Apex Facility Management`.
  2. Vendor Dispatcher (`dispatcher.apex@nivas.local`) allocates worker `Vikram Singh`.
  3. Worker (`worker.vikram@nivas.local`) accepts allocation and starts work.
  4. Work is completed via OTP confirmation.
  5. **Expected Outcome**: Worker allocation history preserved, vendor contract capacity properly decremented upon resolution.

---

### Flow 6: Governance Issue Review & Action Record
- **Objective**: Test the civic resolution pathway.
- **Steps**:
  1. Sign in as `fm.palm@nivas.local`.
  2. Open **Governance Inbox** at `/app/operations`.
  3. Open ticket `PALM-MEADOWS-2026-000004` (`Late Night Noise in Clubhouse`).
  4. Click **Begin Review** (`POST /api/v1/governance-tickets/<id>/begin-review/`).
  5. Record formal resolution action record (`POST /api/v1/governance-tickets/<id>/record-action/`):
     - Action Type: `RESOLUTION_NOTICE`
     - Decision: `Clubhouse hours restricted to 10:00 PM on weekends. Security patrol scheduled.`
  6. **Expected Outcome**: Status updates to `RESOLVED`, resolution summary visible to resident, no OTP challenge required.

---

### Flow 7: Deduplication & Ticket Merging / Unmerging
- **Objective**: Test atomic merging of sibling duplicate tickets and versioned unmerging.
- **Steps**:
  1. Facility Manager identifies duplicate tickets for the same unit or common area.
  2. Initiate merge via `POST /api/v1/service-tickets/<secondary_id>/merge/`:
     - Payload: `primary_ticket_id`, `merge_reason`.
  3. **Expected Outcome**: Secondary ticket marked `MERGED`, capacity released, SLA paused/cancelled, primary ticket records merge reference.
  4. Test Unmerge within 24-hour window via `POST /api/v1/service-tickets/<secondary_id>/unmerge/`.
  5. **Expected Outcome**: Secondary ticket restored to previous state with incremented `state_version` and audit event.

---

### Flow 8: Multi-Tenant & RLS Cross-Society Isolation
- **Objective**: Prove zero cross-tenant leakage between `PALM-MEADOWS` and `GREEN-VALLEY`.
- **Steps**:
  1. Log in as `fm.green@nivas.local` with society UUID `22222222-2222-2222-2222-222222222222`.
  2. Query tickets: Observe only Green Valley tickets (0 tickets from Palm Meadows).
  3. Attempt to fetch a Palm Meadows ticket `PALM-MEADOWS-2026-000001` directly:
     - **Expected Outcome**: `404 Not Found` or `403 Forbidden` via PostgreSQL Row Level Security.
  4. Attempt to pass Palm Meadows UUID `11111111-1111-1111-1111-111111111111` in `X-Society-ID`:
     - **Expected Outcome**: `403 Forbidden - No active membership in this society`.

---

## 5. Recommended Testing Methodology

To test NivasOps thoroughly across all layers, execute testing in four phases:

### Phase A: Interactive UI Workflow Testing (Frontend)
- Run Next.js (`http://localhost:3000`) and test login with each of the 4 primary personas:
  1. **Facility Manager** (`fm.palm@nivas.local`): Verify society metrics, directory, vendor lists, service inbox filters (All, Unassigned, In Progress, Resolved), and governance inbox.
  2. **Resident Owner** (`resident.a101@nivas.local`): Verify draft creation, submission, timeline events, and rating modal.
  3. **Resident Tenant** (`resident.a102@nivas.local`): Verify unit-restricted view and lack of cost approval permissions where configured.
  4. **Cross-Tenant Resident** (`resident.green@nivas.local`): Verify clean separation of Green Valley data.
- Validate responsive layouts at desktop (1440px) and mobile viewport (390px x 844px, iPhone 14) to confirm zero horizontal scroll.

### Phase B: Automated Integration Test Suite (Backend)
- Run pytest suites against `nivasopstestdb` to validate core contracts, RLS, and constraints:
  ```bash
  # Ticket assignments and capacity rules
  .venv/bin/pytest backend/tests/test_ticket_assignments.py --reuse-db -q

  # Ticket attachments and upload slot validation
  .venv/bin/pytest backend/tests/test_ticket_attachments.py --reuse-db -q

  # Complete ticket API suite
  .venv/bin/pytest backend/tests/test_ticket_api.py --reuse-db -q
  ```

### Phase C: Cloud Integration Testing (Azure Services)
- **Email Delivery (ACS)**: Test triggering a password reset (`/forgot-password`) or invitation activation (`/activate`) to verify real email delivery through `DoNotReply@9113704f-fbc4-43a7-8bbb-7e63f821ca4e.azurecomm.net`.
- **Cache & Celery (AMR)**: Verify session blacklist, rate limiting, and OTP capsule storage on `nivascache.centralindia.redis.azure.net:10000`.
- **Blob Storage (nivasstrg)**: Request an attachment upload slot to verify container routing (`ticket-quarantine`) and token issuance.

### Phase D: Concurrency & Optimistic Locking Validation
- Simulate concurrent updates on the same ticket (e.g. technician acceptance while FM cancels, or simultaneous status updates) using different `expected_version` values to verify `409 Conflict (TICKET_VERSION_CONFLICT)`.
