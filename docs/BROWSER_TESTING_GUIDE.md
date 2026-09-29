# NivasOps End-to-End Browser Testing Guide & Protocol

This guide outlines the complete browser-based validation protocol for NivasOps frontend interfaces, API integrations, persona workflows, and responsive layouts. Follow this document when executing automated or semi-automated validation sessions with the browser subagent.

---

## 1. Prerequisites & Test Environment Setup

### 1.1 Services Architecture
To run browser tests, both the backend API listener and frontend Next.js server must be running locally:

```
+------------------------------------+          +------------------------------------+
|         Next.js 16 Frontend        |  Proxy   |          Django 5.2 Backend        |
|        http://localhost:3000       | -------> |        http://localhost:8000       |
+------------------------------------+          +------------------------------------+
                   ^                                               |
                   |                                               v
        +----------------------+                       +----------------------+
        |   Browser Subagent   |                       |   Azure PostgreSQL   |
        |   (Chromium Engine)  |                       |     Test/Dev DB      |
        +----------------------+                       +----------------------+
```

### 1.2 Local Server Launch Instructions

1. **Backend API Listener (PowerShell Terminal 1):**
   ```powershell
   Set-Location backend
   & "..\.venv\Scripts\python.exe" manage.py runserver 127.0.0.1:8000
   ```

2. **Frontend Next.js Server (PowerShell Terminal 2):**
   ```powershell
   Set-Location frontend
   npm run dev
   ```
   *The frontend starts by default on `http://localhost:3000`.*

3. **Seeded Test Society Context:**
   - **Society Name:** `NivasOps Test Society`
   - **Society Registration Code:** `NIVASOPS-DEV`
   - **Society UUID:** `00000000-0000-0000-0000-000000000001` (or local fixture UUID)

---

## 2. Test Persona Matrix & Credentials

| Persona Role | Target Interface | Mock Phone | Password | Society Role / Permissions |
|---|---|---|---|---|
| **Facility Manager (FM)** | `/app/operations` | `+919876500001` | `TestPass@123` | Full society operations, assignments, directory, vendor mgmt |
| **Helpdesk Operator** | `/app/operations` | `+919876500002` | `TestPass@123` | Ticket triage, queue management, resident communication |
| **Resident (Owner)** | `/app` | `+919876500010` | `TestPass@123` | Unit 101 owner; service & governance ticket creation, OTP verification |
| **Resident (Tenant)** | `/app` | `+919876500011` | `TestPass@123` | Unit 102 tenant; service ticket creation |
| **Committee Member** | `/app` & `/app/operations` | `+919876500020` | `TestPass@123` | Governance review, proposal submissions |
| **In-House Technician** | API / Dossier | `+919876500030` | `TestPass@123` | Assigned field technician |
| **Vendor Dispatcher** | `/app/operations/vendors` | `+919876500040` | `TestPass@123` | Vendor worker allocation |

---

## 3. Detailed Test Suites & Scenarios

---

### Test Suite 1: Authentication, Onboarding & Recovery Flows

#### TC-1.1: Standard User Login & Dynamic Persona Routing
- **URL:** `http://localhost:3000/login`
- **Objective:** Verify that users can authenticate with valid credentials and are redirected to their persona-specific home route.
- **Steps:**
  1. Navigate to `/login`.
  2. Enter Society UUID, Phone Number (`+919876500001` for FM), and Password (`TestPass@123`).
  3. Click **Sign In**.
  4. Assert navigation redirect to `/app/operations` for Facility Manager.
  5. Repeat with Resident credentials (`+919876500010`) and assert redirect to `/app`.
- **Assertions:**
  - Token and tenant context stored in session state.
  - Active header displays society name and persona badge.

#### TC-1.2: Login Validation & Error Feedback
- **URL:** `http://localhost:3000/login`
- **Objective:** Verify client-side format validations and server error handling.
- **Steps:**
  1. Input an invalid Society UUID format (e.g. `invalid-uuid-123`).
  2. Verify that field-level error indicator appears before submission.
  3. Input valid UUID but incorrect password.
  4. Click **Sign In** and verify toast/alert: `"Invalid phone number or password."`.

#### TC-1.3: Multi-Persona Invitation & Activation Flow
- **URL:** `http://localhost:3000/activate?society_id={society_id}&invitation_id={inv_id}&token={token}`
- **Objective:** Verify that an invited member can set their password and activate their account.
- **Steps:**
  1. Open the activation link containing valid URL parameters.
  2. Verify that the invitation summary card displays correct society, role, and unit details.
  3. Enter New Password (`SecurePass@2026`) and confirm password.
  4. Click **Activate Account**.
  5. Verify success screen and automated redirection to `/login`.

#### TC-1.4: Self-Service Password Recovery
- **URL:** `http://localhost:3000/forgot-password` and `/reset-password`
- **Objective:** Verify password reset request and token-based confirmation screens.
- **Steps:**
  1. Navigate to `/forgot-password`, enter phone number, and submit.
  2. Verify confirmation message acknowledging reset initiation.
  3. Navigate to `/reset-password?token={reset_token}`, input new password, and submit.
  4. Verify successful password update toast.

---

### Test Suite 2: Resident Experience & Ticket Lifecycle

#### TC-2.1: Resident Dashboard & Navigation Smoke
- **URL:** `http://localhost:3000/app`
- **Persona:** `Resident`
- **Objective:** Inspect resident hub, active ticket counters, status filtering, and action buttons.
- **Steps:**
  1. Log in as Resident and load `/app`.
  2. Verify presence of:
     - Active Service Tickets list.
     - Governance Proposals list.
     - Quick **"Create Ticket"** primary CTA button.
  3. Toggle filter tabs (`All`, `In Progress`, `Resolved`, `Closed`) and ensure list filters correctly without crash.

#### TC-2.2: Service Ticket Creation with Dynamic Categories
- **URL:** `http://localhost:3000/app/new`
- **Persona:** `Resident`
- **Objective:** Create a new service ticket with cascading categories, priority, and location targeting.
- **Steps:**
  1. Click **Create Ticket** (`/app/new`).
  2. Select **Service Ticket** workflow toggle.
  3. Select Category: `"Plumbing"`.
  4. Verify that Subcategory options populate dynamically (e.g. `"Pipe Leakage"`, `"Tap Repair"`).
  5. Choose Target: `"My Unit (101)"`.
  6. Choose Priority: `"P2 - Medium"`.
  7. Fill Title: `"Bathroom pipe leaking under sink"` and Description: `"Continuous drip since morning."`.
  8. Click **Submit Ticket**.
  9. Verify redirect to the newly created ticket dossier (`/app/tickets/service/[id]`).

#### TC-2.3: Resident Public Commenting & Timeline Auditing
- **URL:** `http://localhost:3000/app/tickets/service/[id]`
- **Persona:** `Resident`
- **Objective:** Post updates to the ticket activity timeline.
- **Steps:**
  1. Open an active service ticket dossier.
  2. Scroll to the **Activity & Comments** section.
  3. Enter message: `"Plumber arrived and inspected the pipe."`.
  4. Click **Post Comment**.
  5. Verify that the comment appears immediately in the timeline with timestamp and `Resident` author badge.

#### TC-2.4: Estimate Hold Presentation
- **URL:** `http://localhost:3000/app/tickets/service/[id]`
- **Persona:** `Resident`
- **Objective:** Verify that when a ticket is in `PENDING_ESTIMATE_APPROVAL`, the resident sees a clear estimate hold warning card.
- **Assertions:**
  - `EstimateHoldCard` is rendered prominently.
  - Explanatory copy informs the resident that cost estimate review is pending.

#### TC-2.5: Anti-Fraud Resident Completion OTP Verification
- **URL:** `http://localhost:3000/app/tickets/service/[id]`
- **Persona:** `Resident`
- **Objective:** Verify service completion using the 6-digit OTP challenge.
- **Steps:**
  1. Open a service ticket in `PENDING_RESIDENT_CONFIRMATION` status.
  2. Verify that the **Verify Service Completion** card is active with 6-digit input slots.
  3. Enter incorrect OTP (e.g. `000000`).
  4. Verify error toast: `"Invalid completion code"`.
  5. Enter correct 6-digit OTP.
  6. Click **Confirm Resolution**.
  7. Verify ticket status badge updates immediately to **`RESOLVED`** and state version increments.

#### TC-2.6: Resident Ticket Cancellation
- **URL:** `http://localhost:3000/app/tickets/service/[id]`
- **Persona:** `Resident`
- **Objective:** Cancel a submitted ticket before work has commenced.
- **Steps:**
  1. Open a newly submitted ticket in `SUBMITTED` state.
  2. Click **Cancel Ticket**.
  3. Enter cancellation reason: `"Issue resolved itself."`.
  4. Confirm cancellation.
  5. Verify ticket status transitions to **`CANCELLED`** and action buttons are disabled.

---

### Test Suite 3: Facility Manager Operations & Service Dossiers

#### TC-3.1: Operations Dashboard & Queue Inspection
- **URL:** `http://localhost:3000/app/operations`
- **Persona:** `Facility Manager`
- **Objective:** Verify ticket queue visibility, SLA health indicators, and metric tiles.
- **Steps:**
  1. Log in as Facility Manager and navigate to `/app/operations`.
  2. Inspect high-level metrics (Total Open, P1 Critical, Overdue SLAs, Unassigned).
  3. Click on a ticket in the triage queue to navigate into its dossier (`/app/operations/service/[id]`).

#### TC-3.2: In-House Technician Assignment with Live Capacity Counter
- **URL:** `http://localhost:3000/app/operations/service/[id]`
- **Persona:** `Facility Manager`
- **Objective:** Assign an in-house technician and inspect real-time workload counters.
- **Steps:**
  1. Open an unassigned service ticket dossier.
  2. Click **Assign Ticket** -> Select **In-House Technician**.
  3. Inspect technician dropdown list:
     - Verify technician names, trade/specialization, and capacity counters (e.g. `(2/5 active tickets)`).
  4. Select an available technician with remaining capacity.
  5. Click **Confirm Assignment**.
  6. Verify ticket state transitions to **`ASSIGNED`**, assigned technician badge appears, and internal timeline logs assignment event.

#### TC-3.3: External Vendor Contract Assignment
- **URL:** `http://localhost:3000/app/operations/service/[id]`
- **Persona:** `Facility Manager`
- **Objective:** Dispatch an active vendor contract to a service ticket.
- **Steps:**
  1. Open a service ticket dossier.
  2. Click **Assign Ticket** -> Select **Vendor Contract**.
  3. Select contracted vendor company from the list.
  4. Click **Assign Vendor**.
  5. Verify vendor assignment is recorded and ticket transitions to **`ASSIGNED`** (Vendor Offered).

#### TC-3.4: Atomic Ticket Deduplication & Merge Modal
- **URL:** `http://localhost:3000/app/operations/service/[id]`
- **Persona:** `Facility Manager`
- **Objective:** Merge a duplicate ticket into a primary ticket with audit accountability.
- **Steps:**
  1. Open the primary service ticket dossier.
  2. Click **Merge Duplicate Ticket**.
  3. Modal opens: search for duplicate candidate ticket by number or keyword.
  4. Select duplicate secondary ticket.
  5. Enter mandatory audit reason: `"Duplicate resident report for same burst pipe in corridor."`.
  6. Click **Execute Merge**.
  7. Verify:
     - Secondary ticket is marked **`MERGED`** and closed.
     - Primary ticket audit timeline records the merge event with link to secondary ticket.

#### TC-3.5: Internal Staff Notes (Restricted Visibility)
- **URL:** `http://localhost:3000/app/operations/service/[id]`
- **Persona:** `Facility Manager`
- **Objective:** Verify private operational notes that are invisible to residents.
- **Steps:**
  1. In the service ticket dossier, switch tab to **Internal Staff Notes**.
  2. Post note: `"Awaiting replacement valve part from supplier on Wednesday."`.
  3. Verify note appears in yellow internal notes box.
  4. (Cross-check): Log in as the Resident and open the same ticket; confirm the internal note is not displayed.

---

### Test Suite 4: Society Directory, Rosters & Vendor Management

#### TC-4.1: Estate Structure Management (Blocks, Units, Common Areas)
- **URL:** `http://localhost:3000/app/operations/directory`
- **Persona:** `Facility Manager`
- **Objective:** Create and list physical society assets.
- **Steps:**
  1. Navigate to Directory -> **Estate Structure** tab.
  2. Click **Add Unit** -> Enter Block: `"Tower B"`, Unit Number: `"402"`, Floor: `"4"`.
  3. Save and verify unit appears in the directory table.
  4. Click **Add Common Area** -> Name: `"Swimming Pool & Deck"`.
  5. Save and verify common area entry is recorded.

#### TC-4.2: Multi-Persona Invitation Issuance & Zero-Email Link Copy
- **URL:** `http://localhost:3000/app/operations/directory`
- **Persona:** `Facility Manager`
- **Objective:** Issue invitations for residents, staff, and committee members with direct copyable links.
- **Steps:**
  1. Click **Issue Invitation**.
  2. Select Persona: `"Resident"` -> Unit: `"Tower B - 402"` -> Occupancy: `"Tenant"`.
  3. Enter Invitee Phone: `+919876500099` and Email.
  4. Click **Generate Invitation**.
  5. Modal renders success confirmation with copyable activation URL:
     `http://localhost:3000/activate?society_id=...&token=...`
  6. Click **Copy Activation Link** and verify clipboard confirmation.

#### TC-4.3: Executive Management Committee Enrollment
- **URL:** `http://localhost:3000/app/operations/directory`
- **Persona:** `Facility Manager`
- **Objective:** Enroll executive committee members with role designations.
- **Steps:**
  1. Switch to **Management Committee** tab.
  2. Click **Enroll Officer**.
  3. Enter User UUID, Role (`President` / `Secretary` / `Treasurer` / `Member`), and term dates.
  4. Click **Enroll Officer**.
  5. Verify officer card is rendered with executive role badge.

#### TC-4.4: In-House Technician Roster & Capacity Configuration
- **URL:** `http://localhost:3000/app/operations/directory`
- **Persona:** `Facility Manager`
- **Objective:** Inspect technician roster, capacity counters, and active statuses.
- **Steps:**
  1. Switch to **Technicians** tab.
  2. Verify roster table lists technician names, current active tickets, and max ticket capacity.
  3. Toggle technician active status and verify update.

#### TC-4.5: Vendor Company & Contract Registration
- **URL:** `http://localhost:3000/app/operations/vendors`
- **Persona:** `Facility Manager`
- **Objective:** Register vendor companies and configure binding service contracts.
- **Steps:**
  1. Navigate to `/app/operations/vendors`.
  2. Click **Add Vendor Company** -> Name: `"Apex Plumbing Services Pvt Ltd"`, Contact: `"Rajesh Kumar"`, Phone: `+919876500050`.
  3. Save vendor company.
  4. Click **Add Contract** under Apex Plumbing:
     - Set start date, end date, and Max Active Ticket Limit: `10`.
  5. Save contract and verify active contract badge.

#### TC-4.6: Vendor Field Staff Enrollment (Dispatchers & Workers)
- **URL:** `http://localhost:3000/app/operations/vendors`
- **Persona:** `Facility Manager`
- **Objective:** Enroll contract dispatchers and on-ground field workers.
- **Steps:**
  1. In the vendor detail card, click **Enroll Staff Member**.
  2. Enter User UUID and select Role: `"WORKER"`.
  3. Save and verify worker appears in the staff table with 1-click UUID copy button and active indicator.

---

### Test Suite 5: Responsive Layouts & Viewport Ergonomics

#### TC-5.1: Desktop Viewport Standards (1280px × 800px)
- **Viewport:** `Width: 1280, Height: 800`
- **Checks:**
  - Two-column dossier layout (ticket details on left, actions & timeline on right).
  - Navigation sidebar permanently visible on operations routes.
  - Table headers sticky on scroll.

#### TC-5.2: Mobile Viewport Standards (390px × 844px - iPhone 12/14/15)
- **Viewport:** `Width: 390, Height: 844`
- **Checks:**
  - **Zero Horizontal Overflow:** Page body width strictly equals viewport width (`document.body.scrollWidth === window.innerWidth`).
  - **Touch Ergonomics:** All interactive buttons, inputs, tabs, and action icons have $\ge 44\text{px}$ touch targets.
  - **Collapsible Navigation:** Sidebar collapses into bottom navigation bar or top hamburger sheet.
  - **Modal Stacking:** Action dialogs (assign, merge, invite) adapt to full-screen mobile sheets.

---

## 4. Browser Subagent Execution Protocol

When invoking the `browser_subagent` tool, structure the prompt with explicit steps, assertions, and stop conditions.

### Example Browser Subagent Prompt Template

```python
browser_subagent(
    TaskName="Resident Ticket Creation Validation",
    RecordingName="resident_ticket_create",
    TaskSummary="Verify resident service ticket creation and redirection to dossier",
    Task="""
    1. Navigate to http://localhost:3000/login
    2. Fill in Society UUID '00000000-0000-0000-0000-000000000001', Phone '+919876500010', Password 'TestPass@123'
    3. Click 'Sign In' and wait for URL to include '/app'
    4. Click 'Create Ticket' button to navigate to '/app/new'
    5. Fill form:
       - Select 'Service Ticket'
       - Select Category 'Plumbing' -> Subcategory 'Pipe Leakage'
       - Enter Title 'Kitchen sink leaking continuously'
       - Enter Description 'Urgent water leakage under cabinet.'
       - Select Priority 'P2'
    6. Click 'Submit Ticket'
    7. Wait for URL to match '/app/tickets/service/*'
    8. Assert ticket number is visible and status is 'SUBMITTED'
    9. Take a screenshot of the ticket dossier.
    10. Report final URL and ticket number.
    """
)
```

---

## 5. Test Results & Execution Log Template

Use this scorecard to record execution outcomes:

| Test Suite | Test Case ID | Description | Viewport | Status | Artifact / Video Ref |
|---|---|---|---|---|---|
| **Suite 1: Auth** | TC-1.1 | Login & Persona Routing | Desktop | `Pending` | — |
| **Suite 1: Auth** | TC-1.3 | Multi-Persona Invitation & Activation | Desktop | `Pending` | — |
| **Suite 2: Resident** | TC-2.2 | Service Ticket Creation | Desktop | `Pending` | — |
| **Suite 2: Resident** | TC-2.5 | Completion OTP Verification | Desktop | `Pending` | — |
| **Suite 3: Ops** | TC-3.2 | In-House Technician Assignment | Desktop | `Pending` | — |
| **Suite 3: Ops** | TC-3.4 | Deduplication Merge Flow | Desktop | `Pending` | — |
| **Suite 4: Directory** | TC-4.2 | Zero-Email Activation Link Issuance | Desktop | `Pending` | — |
| **Suite 4: Directory** | TC-4.5 | Vendor Contract & Staff Enrollment | Desktop | `Pending` | — |
| **Suite 5: Mobile** | TC-5.2 | Mobile 390x844 Responsive Check | Mobile | `Pending` | — |

---

*Maintain this testing guide in `docs/BROWSER_TESTING_GUIDE.md` as new frontend workflows and backend contracts are delivered.*
