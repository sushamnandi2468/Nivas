# NivasOps Web Application: Comprehensive UI/UX Blueprint & Design Prompts

> **System Overview:** NivasOps is an enterprise-grade, multi-tenant Helpdesk, Facility Management, and Operations Platform engineered for gated communities, residential societies, and apartment complexes.  
> **Source Specification:** Dual-FSM workflows, multi-tier SLA escalation, PBKDF2 OTP verification, tenant isolation, and multi-persona operational consoles.

---

## Table of Contents
1. [Design System & Aesthetics Specification](#1-design-system--aesthetics-specification)
2. [Persona & Navigation Architecture](#2-persona--navigation-architecture)
3. [Master Screen Inventory & Route Matrix](#3-master-screen-inventory--route-matrix)
4. [Detailed Screen Specifications & Design Prompts](#4-detailed-screen-specifications--design-prompts)
   - [Module 1: Authentication & Multi-Tenancy Onboarding](#module-1-authentication--multi-tenancy-onboarding)
   - [Module 2: Facility Manager & Helpdesk Operations Hub](#module-2-facility-manager--helpdesk-operations-hub)
   - [Module 3: RWA Management Committee Executive Portal](#module-3-rwa-management-committee-executive-portal)
   - [Module 4: AMC Vendor & Contractor Portal](#module-4-amc-vendor--contractor-portal)
   - [Module 5: Resident & Occupant Self-Service Portal](#module-5-resident--occupant-self-service-portal)
   - [Module 6: Society Administration & Policy Studio](#module-6-society-administration--policy-studio)
5. [Interactive Micro-States & Edge Case Guide](#5-interactive-micro-states--edge-case-guide)

---

## 1. Design System & Aesthetics Specification

### 1.1 Aesthetic Philosophy
* **Visual Tone:** Ultra-modern, high-density Enterprise SaaS with sleek dark/light adaptive modes, frosted glassmorphic card overlays, crisp data typography, and micro-animated status pulses.
* **Inspiration:** Linear.app, Vercel Dashboard, Stripe Sigma, and Apple HIG desktop ergonomics.
* **Zero Placeholders:** Every prompt specifies concrete data, realistic metric cards, real-world Indian society naming conventions (e.g., *Palm Meadows RWA, Tower 4 - Flat 802, Prestige Lakeside Habitat*), and contextual actions.

### 1.2 Curated Color Tokens
```css
:root {
  /* Brand Core */
  --brand-primary: #4F46E5;        /* Electric Indigo */
  --brand-primary-hover: #4338CA;
  --brand-accent: #06B6D4;         /* Cyber Cyan */
  --brand-accent-glow: rgba(6, 182, 212, 0.25);
  
  /* Neutral Canvas (Dark Mode Default) */
  --bg-app: #0B0F17;              /* Deep Space Obsidian */
  --bg-surface: #111827;          /* Charcoal Slate */
  --bg-surface-elevated: #1F2937; /* Raised Card Surface */
  --bg-glass: rgba(17, 24, 39, 0.75);
  --border-subtle: rgba(255, 255, 255, 0.08);
  --border-highlight: rgba(79, 70, 229, 0.4);

  /* Typography */
  --text-primary: #F9FAFB;
  --text-secondary: #9CA3AF;
  --text-muted: #6B7280;

  /* Priority Tokens */
  --priority-p1: #EF4444;          /* Crimson Red (P1 Critical) */
  --priority-p2: #F97316;          /* Ember Orange (P2 High) */
  --priority-p3: #F59E0B;          /* Amber Yellow (P3 Medium) */
  --priority-p4: #10B981;          /* Emerald Green (P4 Low) */

  /* Dual FSM Status Tokens */
  --status-draft: #6B7280;
  --status-submitted: #3B82F6;
  --status-assigned: #8B5CF6;
  --status-in-progress: #06B6D4;
  --status-estimate-pending: #EC4899;
  --status-resident-otp: #F59E0B;
  --status-resolved: #10B981;
  --status-closed: #4B5563;
  --status-escalated-l1: #F97316;
  --status-escalated-l2: #DC2626;
  --status-escalated-l3: #7F1D1D;
  --status-triage: #E11D48;
}
```

### 1.3 Typography & Components
* **Font Family:** `Outfit` (Headings & Display KPIs), `Inter` (Data tables, forms, status pills), `JetBrains Mono` (Ticket IDs, OTP hashes, SLA Timers, Audit Logs).
* **Card Style:** Subtle 1px translucent border, 16px radius, backdrop blur (12px), soft directional gradient background.
* **Live Micro-Indicators:**
  * **Pulsing Green Dot:** Active on-duty technician / Live SLA clock ticking.
  * **Pulsing Amber Dot:** SLA Paused (Estimate approval pending / Reopened).
  * **Pulsing Red Flame:** L2/L3 Escalated ticket exceeding breach thresholds.

---

## 2. Persona & Navigation Architecture

The web app is a unified, multi-tenant portal with context-aware role switching:

```
+----------------------------------------------------------------------------------------------------+
|                                    NIVASOPS MULTI-TENANT WEB APP                                   |
+----------------------------------------------------------------------------------------------------+
|                                    GLOBAL HEADER & CONTEXT BAR                                     |
| [Society Switcher: Prestige Towers v]  [Search / Command K]  [Role: Facility Manager v]  [Profile] |
+----------------------------------------------------------------------------------------------------+
|  SIDEBAR NAV (Role-Based)  |                           MAIN WORKSPACE                              |
|                            |                                                                       |
|  * FM / Supervisor:        |  - Live Operations Command Center                                     |
|    - Dispatch Console      |  - Split-view Ticket Processing Workspace                             |
|    - Shift Roster & Techs  |  - Interactive Shift & Workload Load-Balancer                         |
|    - SLA Escalation Radar  |  - Supervisor Override & Emergency Dispatch Vault                     |
|                            |                                                                       |
|  * RWA Committee:          |  - Executive Society Analytics & CSAT Radar                           |
|    - L3 Crisis Board       |  - Governance Civic Threads & Action Recorder                         |
|    - Governance Threads    |  - High-Value Estimate CapEx Authorization                            |
|                            |                                                                       |
|  * AMC Vendor:             |  - Society Contract Work Orders & Service Sheets                      |
|    - Work Orders & Staff   |  - Completion Certificate Verification Upload                         |
|                            |                                                                       |
|  * Resident / Owner:       |  - 3-Click Service & Civic Request Wizard                             |
|    - My Unit Helpdesk      |  - Real-time Lifecycle Tracker & Anti-Fraud OTP Display               |
|    - Estimate Approvals    |  - 1-Click Material Estimate Authorization & Rating Card              |
+----------------------------+-----------------------------------------------------------------------+
```

---

## 3. Master Screen Inventory & Route Matrix

| Screen ID | Screen Name | Target Persona | Primary Workflow / Purpose |
| :--- | :--- | :--- | :--- |
| **AUTH-01** | Multi-Tenant Login & OTP Handshake | All Users | Phone/Email Auth, Society auto-discovery, OTP/Password verification |
| **AUTH-02** | Society & Persona Context Switcher | Multi-Role Users | Switching between multiple societies (e.g. Owner in Society A, Committee in Society B) |
| **FM-01** | Operations Command Center | FM / Supervisor | Real-time SLA breach ticker, technician load gauge, live ticket feed |
| **FM-02** | Service Ticket Dispatch & Triage Board | FM / Supervisor / Operator | Filterable Kanban & Table views (P1-P4, SLA status, Skill, Tower) |
| **FM-03** | Service Ticket Detailed Workspace | FM / Supervisor | Split-pane FSM visualizer, SLA pause clock, dispatch dropdown, audit history |
| **FM-04** | Supervisor Override & Reopen Modal | FM / Supervisor | OTP bypass with audit justification, manual tech override, ticket reopening |
| **FM-05** | Technician Workforce & Live Shift Roster | FM / Supervisor | Daily/Weekly shift scheduler, on-duty toggle, real-time workload balancer |
| **FM-06** | Material Estimate & Cost Center | FM / Supervisor | Estimate queue, parts breakdown, vendor quote attachments, approval tracking |
| **FM-07** | Multi-Tier SLA Escalation Monitor | FM / Supervisor / RWA | L1 acceptance timeout radar, L2 FM alert stream, L3 breach register |
| **FM-08** | Society Directory & Unit Occupancy Explorer | FM / Supervisor | Towers, Flats, Owners, Tenants, Lease expiration monitoring |
| **RWA-01** | Executive Society Analytics Dashboard | RWA Committee Members | Macro KPIs, Resolution rate, CSAT trends, Cost burn, L3 Red Alert banner |
| **RWA-02** | L3 Escalation & Crisis Resolution Board | RWA Committee (President/Sec) | Tickets breached > 24 hrs, committee intervention & direct action assign |
| **RWA-03** | Civic Governance & Resolution Center | RWA Committee / Residents | Community threads, policy complaints, AGM resolutions, public polls |
| **RWA-04** | High-Value Estimate CapEx Authorization | RWA Treasurer / President | High-value estimate approval (> threshold), society reserve fund tracking |
| **RWA-05** | AMC Vendor Performance & Compliance Scorecard | RWA Committee | Contract validity, SLA performance metrics, resident ratings, penalty tracker |
| **VEN-01** | AMC Vendor Overview Dashboard | Vendor Staff / Contractors | Active contracts, pending work orders, technician allocation, SLA score |
| **VEN-02** | Vendor Work Order Execution & Certificate Vault| Vendor Technicians / Staff | Job completion upload, signed service certificates, parts invoice sync |
| **VEN-03** | Vendor Staff & Field Roster | Vendor Admin | Vendor technician registry, assigned society contracts, contact directory |
| **RES-01** | Resident Home & Helpdesk Portal | Flat Owner / Tenant | Active ticket status badges, quick raise button, society notices |
| **RES-02** | Ticket Creation Studio | Flat Owner / Tenant | Service Request vs Civic Thread, photo/doc upload, preferred slot |
| **RES-03** | Resident Ticket Lifecycle & Live Tracker | Flat Owner / Tenant | Step-by-step FSM timeline, assigned tech info, in-app conversation thread |
| **RES-04** | Anti-Fraud OTP & Service Completion Modal | Flat Owner / Tenant | 4-Digit OTP display, warning badge, Star Rating & CSAT feedback |
| **RES-05** | Estimate Review & 1-Click Action Modal | Flat Owner / Tenant | Itemized material cost, 1-click Approve / Reject with reason |
| **RES-06** | My Unit & Household Profile | Flat Owner / Tenant | Unit occupants, tenant lease countdown timer, vehicle parking passes |
| **CFG-01** | Category, Sub-Category & Skill Studio | Society SuperAdmin / FM | Category hierarchy, skill mapping, default priority bindings |
| **CFG-02** | SLA Policy & Escalation Matrix Configurator | Society SuperAdmin / FM | P1-P4 SLA rules, acceptance timeouts, target resolution hours, pause rules |
| **CFG-03** | AMC Contracts & Vendor Onboarding | Society SuperAdmin / FM | Vendor directory, contract start/end dates, category allocation |
| **CFG-04** | Audit Vault & Security Compliance Logs | SuperAdmin / Auditor | Immutable `TicketEvent` log viewer, OTP failure anomalies, override records |

---

## 4. Detailed Screen Specifications & Design Prompts

---

### Module 1: Authentication & Multi-Tenancy Onboarding

#### Screen AUTH-01: Multi-Tenant Login & OTP Handshake
* **Persona:** All Personas (Resident, FM, Committee, Technician, Vendor).
* **Key Components:**
  * Clean, split-screen layout: Left hero banner with 3D isometric smart society visual; Right glassmorphic authentication card.
  * Tabbed input: Mobile OTP (Default) or Email & Password.
  * Mobile phone number input with Country code prefix (`+91`), auto-formatted.
  * 4-digit OTP input boxes with auto-focus and countdown resend timer (45s).
  * Auto-detect badge showing associated society count (e.g. *"2 societies linked to this number"*).
* **Interactive Prompt:**
```text
Design a hyper-modern, secure Web Login and OTP Authentication screen for an enterprise gated-community management platform called 'NivasOps'. 
Theme: Dark mode luxury aesthetic (#0B0F17 background, #111827 card surface, electric indigo #4F46E5 primary CTA, cyan #06B6D4 highlights).
Layout: Left 50% split features a high-end 3D architectural render of a futuristic smart gated community with subtle glowing neon telemetry overlays (SLA monitors, green security status indicators, glowing gate entry nodes).
Right 50% features a glassmorphic login card with:
- Top logo 'NivasOps' with a glowing geometric shield icon.
- Header: 'Welcome to Society Operations Portal' with subtitle 'Sign in with your registered phone number'.
- Tabs: 'Quick OTP Sign-In' (Active) and 'Password Access'.
- Phone input with Indian flag (+91) selector, sleek floating label, and instant phone number validation badge.
- 'Send Verification Code' button with a subtle loading spinner micro-state.
- Once sent, reveals four distinct glass-morphic digit boxes with active glow borders, auto-paste support, and a 'Resend OTP in 00:32' countdown timer.
- Security badge at the bottom: 'Multi-Tenant Encrypted Isolation • ISO 27001 Certified • PBKDF2 Protected'.
- Ultra-clean typography (Outfit for headers, Inter for form labels), smooth micro-interactions, zero clutter.
```

---

#### Screen AUTH-02: Society & Persona Context Switcher
* **Persona:** Users holding multiple roles across one or more societies (e.g., Owner in *Palm Heights* + Committee Member in *Silver Oak*).
* **Key Components:**
  * Modal/Overlay or full-page grid displaying all authorized tenant accounts for the user.
  * Card per society showing: Society Name, City, Block/Door Number, Active Role Badge (`RWA President`, `Flat Owner`, `Facility Manager`, `Vendor Staff`), Unread tickets indicator.
  * Search bar to quickly filter societies.
  * "Enter Workspace" hover CTA with smooth scale effect.
* **Interactive Prompt:**
```text
Design a sleek, high-end Multi-Tenant Society & Persona Switcher screen for 'NivasOps'.
Theme: Modern Dark Mode (#0B0F17 app background, frosted glass card overlays, glowing indigo and emerald accents).
Header: 'Select Active Society Workspace' with subtitle 'You have memberships across 3 residential complexes'.
Search bar: Centered search input with shortcut badge [Ctrl + K] to filter societies by name, tower, or role.
Grid: A 3-column responsive card grid showcasing society memberships:
- Card 1: 'Prestige Lakeside Habitat (Bangalore)' | Unit: 'Tower 4 - Flat 1204' | Role Badge: 'Resident Owner' (Cyan badge) | Stats: '2 Active Tickets • 1 Pending Estimate' | 'Enter Workspace ->' button.
- Card 2: 'Palm Meadows Villa Community' | Unit: 'Villa 42' | Role Badge: 'RWA President' (Purple badge with Crown icon) | Stats: '4 L3 Critical Escalations • 12 Open Civic Threads' | 'Enter Workspace ->' button.
- Card 3: 'Greenwood Heights' | Unit: 'Facility Management Hub' | Role Badge: 'Facility Supervisor' (Amber badge with Wrench icon) | Stats: '18 Active Jobs • 3 Techs On Duty' | 'Enter Workspace ->' button.
Footer: 'Need to register a new society or add a flat? Contact your Society Admin or RWA Office'.
Cards have subtle hover elevation, glowing borders, and crisp typography (Outfit + Inter).
```

---

### Module 2: Facility Manager & Helpdesk Operations Hub

#### Screen FM-01: Operations Command Center (Live Dispatch Dashboard)
* **Persona:** Facility Manager, Estate Supervisor, Helpdesk Operator.
* **Key Components:**
  * **Top Metrics Bar (4 KPI Cards):**
    1. *Active Service Jobs* (e.g., 28 Total • 12 In-Progress • 4 Unassigned).
    2. *SLA Health Index* (e.g., 94.2% On-Time • 2 at L1 Risk • 1 at L2 Breach).
    3. *Workforce On-Duty* (e.g., 8/10 Technicians Active • 2 on Shift Break).
    4. *Pending Resident Estimates* (e.g., ₹42,500 across 5 Tickets).
  * **Real-time Live Ticket Queue (Split View):**
    - Filter pills: `All (28)`, `P1 Critical (3)`, `Unassigned (4)`, `Triage Required (2)`, `Estimate Pending (5)`.
    - Live list showing ticket card with countdown timer, assigned tech avatar, category icon, and tower/flat.
  * **Technician Live Workload Heatmap:** Mini-cards for on-duty technicians showing current assigned ticket count (e.g., *Ramesh K. - Electrician - 3 Jobs (Busy)*).
  * **Emergency L2/L3 Alert Banner:** Flashing alert if any ticket has exceeded target resolution SLA.
* **Interactive Prompt:**
```text
Design a breathtaking, high-density Web Operations Command Center Dashboard for Facility Managers in 'NivasOps'.
Theme: Sleek Dark B2B SaaS (#0B0F17 base, #111827 containers, #1F2937 cards, vibrant accent badges in Red #EF4444, Amber #F59E0B, Cyan #06B6D4, Indigo #4F46E5).
Top Navigation: Society selector 'Prestige Lakeside Habitat (Tower A-G)', Global Search [Cmd+K], Live System Clock, Notification Bell (with red pulse), User Avatar 'Rajesh Verma (Facility Manager)'.
Top KPI Row: 4 sleek cards with sparklines and metric changes:
1. 'Active Service Tickets' -> '28' (+4 from yesterday), status breakdown mini-bar.
2. 'SLA Compliance' -> '94.8%' (Circular progress ring with emerald glow, '2 At Risk').
3. 'Field Workforce' -> '8 / 10 On Duty' (Active electrical, plumbing, carpentry staff).
4. 'Pending Estimates' -> '₹48,200' (5 approvals waiting on residents).
Main Section (Split 70/30):
Left 70%: 'Live Dispatch & Triage Stream' with tabbed filters (All, P1 Critical, Triage Required, Vendor Managed). Ticket list items show: Priority badge (P1 Crimson / P2 Orange), Ticket ID (#SR-8921), Flat 'Tower C - 604', Category 'Plumbing - Main Pipe Leak', Dynamic SLA Clock badge ('Breaches in 18m' in pulsing red), Quick Action buttons ('Auto-Dispatch', 'Assign Tech', 'View Details').
Right 30%:
- Top widget: 'Technician Workload Radar' showing on-duty staff cards with active job counters (e.g., 'Suresh M. (Plumber) - 2 active jobs - Status: In Progress at T2-401').
- Bottom widget: 'SLA Escalation Radar' highlighting 1 L2 Breached ticket needing supervisor intervention with a glowing 'Take Action' button.
Typography: Outfit for KPI numbers, Inter for dense tabular lists, JetBrains Mono for ticket IDs and timers.
```

---

#### Screen FM-02: Service Ticket Master Console & Live Triage Board
* **Persona:** Facility Manager, Helpdesk Operator.
* **Key Components:**
  * Dual View Toggle: **Kanban Board** (Columns: *Submitted / Unassigned*, *Assigned*, *In Progress*, *Pending Estimate*, *Supervisor Triage*, *Pending OTP Verification*, *Resolved*) vs **Data Table View**.
  * Multi-dimensional filtering drawer: Priority (P1-P4), Category (Electrical, Plumbing, Lift, Carpentry, Masonry), Block/Tower (Tower A-F), Escalation Tier (None, L1, L2, L3), Assignment (In-house vs AMC Vendor).
  * Drag-and-Drop ticket card support (with FSM transition guard validation popups).
  * Bulk action toolbar: Bulk Assign, Bulk Re-prioritize, Export CSV.
* **Interactive Prompt:**
```text
Design a comprehensive, high-productivity Service Ticket Master Console with a Kanban & Table View switcher for 'NivasOps'.
Theme: Enterprise Dark Mode (#0B0F17 background, #111827 column containers, glassmorphic floating drag cards).
Header: Page title 'Service Tickets & Triage Board', search bar with instant query filtering, 'View Toggle: [Kanban Icon] Board | [Table Icon] List', and '+ Raise Internal Ticket' button.
Filter Ribbon: Interactive filter chips: 'Priority: P1 & P2' (Active), 'Status: All', 'Category: All', 'Tower: All Towers', 'Escalated Only (Toggle)', 'Clear All'.
Kanban View (Horizontal scrolling columns with column counters and SLA risk badges):
1. 'Submitted / Triage' (4) - Cards display 'Rejection Count: 3x' warning badge in amber for tickets needing supervisor manual allocation.
2. 'Assigned / Acknowledging' (6) - Shows 30-minute acceptance countdown timer (e.g. '08:42 left to accept').
3. 'In Progress' (11) - Shows technician avatar, start timestamp, elapsed time, and 'Pause SLA' indicator.
4. 'Pending Estimate' (3) - Shows estimated amount badge '₹1,850' in pink and 'Awaiting Flat 402 Approval'.
5. 'Pending Resident OTP' (4) - Shows 'OTP Requested' badge in amber and 'Awaiting physical signoff'.
6. 'Resolved / Closed' (24) - Shows completion time and 5-star rating summary.
Cards feature crisp typography, category color dots, priority tag, unit number, technician miniature badge, and micro-hover action icons (Quick View, Reassign, Event History).
```

---

#### Screen FM-03: Service Ticket Detailed Workspace (Split-Pane FSM Control)
* **Persona:** Facility Manager, Estate Supervisor.
* **Key Components:**
  * **Top FSM Stepper Ribbon:** Visual lifecycle progress bar (*Draft -> Submitted -> Assigned -> Accepted -> In Progress -> Estimate / Triage -> Pending OTP -> Resolved -> Closed*), showing current active state, timestamps, and active guards.
  * **Left Pane (60%): Ticket Dossier & Actions:**
    - Ticket Header: Title, Ticket ID (`#SR-10492`), Priority pill, Category/Subcategory, Unit info, Resident contact details.
    - Description & Attached Media carousel (high-res photo proofs of leak/damage with zoom modal).
    - Material Estimate Section (if submitted): Parts breakdown, supplier receipt, resident approval status.
    - Technician Dispatch Card: Assigned technician info, on-duty status, current workload, "Reassign" / "Escalate to AMC" buttons.
    - Interactive Conversation Thread: Combined resident chat, internal staff private notes (yellow highlight), and system-generated events.
  * **Right Pane (40%): Live SLA Clock, Anti-Fraud Vault & Audit Stream:**
    - Live Target Resolution Timer widget (ticking down in real-time or showing "PAUSED" with pause reason badge).
    - Total Paused Duration accumulator (`02h 45m`).
    - Anti-Fraud OTP Card: Status (`OTP Generated 8 mins ago - 0/3 attempts`), "Supervisor Override" button.
    - Immutable Audit Timeline: Visual chronological feed of `TicketEvent` records (e.g., *Dispatched -> Accepted by Tech -> Paused for Estimate -> Resumed -> OTP Sent*).
* **Interactive Prompt:**
```text
Design an advanced, ultra-detailed Service Ticket Workspace and FSM Controller screen for 'NivasOps'.
Theme: Modern Dark Mode (#0B0F17 canvas, #111827 panels, #1F2937 inner cards, electric indigo #4F46E5 accents, crisp data typography).
Top FSM Stepper: A glowing horizontal stage progression bar illustrating ticket states: 'Submitted' (Done) -> 'Assigned' (Done) -> 'In Progress' (Active, glowing cyan pulse) -> 'Estimate Approval' (Optional/Passed) -> 'Resident OTP Handshake' (Next) -> 'Resolved'.
Two-Column Split Workspace:
Left Column (60% width):
- Ticket Header: '#SR-10492: Severe Water Leakage under Kitchen Sink', Priority 'P1 Critical' (Crimson badge), Category 'Plumbing > Pipe Burst', Unit 'Tower B - Flat 802 (Mr. Ananya Roy)'.
- Resident Attachments: 2 photo thumbnails with 'Click to expand' overlay showing leaking valve.
- Material Estimate Card: 'Item: Brass Angle Valve + CPVC Pipe Replacement' | Amount: '₹1,450' | Status: 'Approved by Resident at 14:20'.
- Assigned Staff Box: 'Technician: Suresh Mandanna (In-House Plumber)' with phone icon, workload badge '2 active jobs', and 'Reassign Tech' button.
- Communication Thread: Split tabs 'Public Resident Chat' and 'Internal Staff Only Notes' (yellow-tinted container for confidential supervisor memos).
Right Column (40% width):
- SLA Countdown Card: Large digital readout '03h : 24m : 18s Remaining' (Green border glow). Shows initial SLA target, total paused duration ('45 mins during estimate review'), and escalation level 'None (Nominal)'.
- Verification Card: 'Anti-Fraud Completion Status' -> 'Status: Ready for OTP Handshake'. Warning: 'Resident must provide 4-digit code upon physical inspection'.
- 'Supervisor Override' emergency button (secondary danger outline).
- Append-Only Audit Feed: Chronological vertical timeline with timestamps, actor names, status changes, and reason notes.
```

---

#### Screen FM-04: Supervisor Override & Emergency Action Modal
* **Persona:** Facility Manager / Estate Supervisor.
* **Key Components:**
  * Security confirmation modal triggered for high-risk operations:
    1. *Bypassing Resident OTP* (e.g., Resident unavailable / elderly resident phone battery dead).
    2. *Force Re-opening a closed ticket*.
    3. *Force-assigning to off-duty/overloaded technician*.
  * Mandatory Audit Justification text area (minimum 20 characters validation).
  * Proof of physical inspection attachment upload (photo of completed work).
  * Digital signature / Pin confirmation.
* **Interactive Prompt:**
```text
Design a critical security modal for 'Supervisor Manual Override & OTP Bypass' in 'NivasOps'.
Theme: Dark mode with amber/crimson safety warning accents (#111827 modal background, frosted dark backdrop blur #000000AA, amber border #F59E0B).
Modal Header: Warning shield icon with title 'Supervisor Emergency Override — Ticket #SR-10492' and subtitle 'Bypassing resident completion OTP requires mandatory audit justification'.
Form Elements:
1. Reason Category Dropdown: 'Resident Physically Confirmed but Device Inaccessible', 'Disputed Resolution / Supervisor Inspected', 'AMC Vendor Direct Certificate Sign-off'.
2. Detailed Justification Text Area: 'Enter detailed inspection remarks (Min 20 characters)' with live character counter '48/20 characters entered'.
3. Photo Proof Upload: Drag-and-drop zone 'Upload on-site inspection photo / signed job slip (JPG, PNG, PDF up to 10MB)'.
4. Checkbox Confirmation: 'I certify under society operational bylaws that physical work at Tower B - Flat 802 is 100% verified.'
Modal Actions: 'Cancel' (Ghost button) and 'Confirm Override & Mark Resolved' (Amber warning solid button with lock icon).
Include clear security alert text at bottom: 'This action is permanently logged to the immutable Society Audit Vault.'
```

---

#### Screen FM-05: Technician Workforce & Live Shift Roster
* **Persona:** Facility Manager, Estate Supervisor.
* **Key Components:**
  * **Shift Calendar / Roster View:** Daily & Weekly matrix of technicians vs time slots (Morning 08:00–16:00, Evening 14:00–22:00, Night On-Call).
  * **Technician Roster Cards:**
    - Name, Photo, Skill Tags (`Electrician`, `Plumber`, `HVAC`, `Carpenter`).
    - Real-Time "On-Duty" Toggle switch.
    - Live Workload Bar (`Current Active Tickets: 2/5 max capacity`).
    - Today's Completed Jobs & CSAT Rating (e.g., `4.9 ★ (18 reviews)`).
  * Quick Actions: "Add Technician", "Assign Shift", "Emergency Broadcast".
* **Interactive Prompt:**
```text
Design a high-productivity Technician Workforce & Shift Management screen for 'NivasOps'.
Theme: Dark Mode SaaS (#0B0F17 app background, #111827 table & card containers, glowing emerald #10B981 for On-Duty, indigo #4F46E5 for primary buttons).
Top Bar: Title 'Workforce Management & Shifts', Date Picker 'Today: Tuesday, 25 Aug 2026', Shift Filter 'All Shifts', 'Add New Technician' button, and 'Auto-Balance Workload' button.
Top Summary: 3 quick stat pills: '12 Registered Technicians', '8 Currently On-Duty', '2 Shifts Active (Morning & General)'.
Main Layout (Split View):
Left Panel (60%): Interactive Weekly Shift Grid:
- Rows: Technician names with skill icons and duty badges.
- Columns: Days of the week (Mon to Sun) showing colored shift blocks ('08:00 - 16:00', '14:00 - 22:00', 'OFF').
- Clickable cells to reassign shifts or flag leave.
Right Panel (40%): Live Technician Performance & Capacity List:
- Individual technician cards: 'Ramesh Kumar (Master Electrician)', toggle switch 'On-Duty' (Active Green), Workload gauge '3 / 4 Active Jobs (75% Load)', 'Average Resolution Time: 42 mins', 'CSAT: 4.85 ★'.
- Skill tag pills: 'Single Phase', 'Three Phase', 'DG Backup', 'Intercom'.
- 'Quick Re-route Tickets' button on overloaded technicians.
```

---

#### Screen FM-06: Material Estimate & Cost Center
* **Persona:** Facility Manager, Society Accountant.
* **Key Components:**
  * Table of all tickets with material cost estimates.
  * Status Filter: `Pending Resident Decision`, `Approved`, `Rejected (In Triage)`, `Reimbursed`.
  * Detailed cost view showing: Parts name, Unit quantity, Rate, GST, Vendor quotation receipt preview.
  * Total Monthly Material Spend tracker widget.
* **Interactive Prompt:**
```text
Design a polished Material Cost Estimates & Expense Management screen for 'NivasOps'.
Theme: Dark SaaS interface (#0B0F17 base, #111827 cards, #10B981 emerald for approvals, #EC4899 pink for pending estimates).
Header: 'Material Estimates & Maintenance Billing' with 'Export GST Report' and 'Filter by Date Range'.
Top Metric Cards:
1. 'Total Estimates Raised this Month' -> '₹1,24,500' (38 tickets).
2. 'Pending Resident Approval' -> '₹18,400' (6 tickets awaiting resident 1-click consent).
3. 'Approval Rate' -> '91.4%' (Average approval turnaround: 18 mins).
Data Table: Columns for Ticket ID (#SR), Flat Number, Resident Name, Required Parts Summary, Estimated Amount, Vendor/Hardware Store Slip (thumbnail preview), Status Pill ('Pending Approval', 'Approved', 'Rejected by Resident'), Action buttons ('Send WhatsApp Reminder', 'View Breakdown', 'Override').
Side Drawer preview showing itemized invoice: '1x Havells 32A MCB (₹650) + 5m Finolex 4sqmm Wire (₹400) + Labor Charges (₹0 - AMC Covered) = Total ₹1,050'.
```

---

#### Screen FM-07: Multi-Tier SLA Escalation Monitor
* **Persona:** Facility Manager, RWA Committee Auditor.
* **Key Components:**
  * **3-Tier Radar Visualization:**
    1. *Level 1 (Technician Acceptance Breach - 30m timeout):* Real-time list of tickets auto-requeued or waiting for acceptance.
    2. *Level 2 (Target Resolution Breach - FM Alert):* Tickets past resolution target, highlighting hours overdue and assigned staff.
    3. *Level 3 (Critical Overdue >24h - RWA Flag):* Red flag tickets visible on executive board requiring emergency intervention.
  * SLA Paused Tickets section (showing tickets paused for estimate approval or resident unavailability, with duration counters).
* **Interactive Prompt:**
```text
Design an executive SLA Escalation Radar & Breach Management screen for 'NivasOps'.
Theme: High-contrast Dark Operations Center (#0B0F17 background, #111827 panels, pulsating alert indicators in Amber #F59E0B, Crimson #DC2626, and Deep Red #7F1D1D).
Top Header: 'Multi-Tier SLA Escalation Matrix' with live system sync indicator 'Celery Beat Monitor: Active (Every 60s)'.
3-Column Escalation Grid:
Column 1: 'Tier 1: Tech Acceptance Timeout (30 Mins)' (Orange theme, 3 tickets):
- Cards show: Ticket ID, Tech name, Assigned time, 'Breached by 12 mins', 'Action: Auto-Requeued 2/3 times'.
Column 2: 'Tier 2: Target Resolution Breach (FM Escalation)' (Crimson theme, 2 tickets):
- Cards show: Ticket ID, Tower/Flat, Category, 'Target was 14:00 Today', 'Overdue by 02h 15m', 'Facility Manager Alert Sent via Push & Webhook', 'Direct Reassign' button.
Column 3: 'Tier 3: Critical Society Crisis (> 24h Past SLA)' (Deep Red glowing card, 1 ticket):
- Flashing red banner: 'Flagged on RWA Committee Dashboard'.
- Ticket: '#SR-7810 - Main Tower Water Booster Pump Malfunction'.
- Overdue metric: '+28 Hours Overdue'.
- 'Emergency Committee Call' & 'Dispatch External Specialist' action buttons.
Bottom Drawer: 'SLA Paused Inventory' showing 4 tickets with paused timers due to resident estimate reviews or night quiet hours.
```

---

#### Screen FM-08: Society Directory & Unit Occupancy Explorer
* **Persona:** Facility Manager, Helpdesk Operator, Society Admin.
* **Key Components:**
  * Building / Block / Villa hierarchy navigator (e.g., *Tower A -> Floors 1 to 14 -> Flats 101 to 1404*).
  * Flat card view showing: Door Number, Primary Owner, Current Tenant, Lease Validity with color-coded expiry countdown (`Lease ends in 18 days`), Active helpdesk tickets count.
  * Search by Resident Name, Vehicle Number, Flat Number, or Phone.
  * Quick drawer to add occupants, view ticket history for the unit, or send broadcast notice.
* **Interactive Prompt:**
```text
Design a clean, high-density Society Directory & Unit Occupancy Explorer for 'NivasOps'.
Theme: Dark Mode SaaS (#0B0F17 base, #111827 card containers, #1F2937 hover states, cyan #06B6D4 and indigo #4F46E5 accents).
Header: 'Units & Occupancy Directory' with Tower selector pills ('Tower A', 'Tower B', 'Tower C', 'Villas'), search bar, and '+ Register Occupant' button.
Main Layout:
Left side: Interactive visual Tower floor-plan selector (Floors 1–14).
Center/Right: Grid of Unit Cards for selected floor:
- Unit Card: 'Flat 402' | Badge: 'Tenant Occupied' (Cyan) | Owner: 'Dr. K. S. Murthy' | Tenant: 'Vikram Malhotra' | 'Lease: Active until Dec 2026' | 'Active Tickets: 1 Open (P2)' | Quick action icons: [Call], [WhatsApp], [View History], [Edit].
- Unit Card (Expiring Lease): 'Flat 403' | Badge: 'Lease Expiring in 12 Days' (Amber alert badge) | Tenant: 'Pooja Hegde' | 'Prompt Renewal' button.
- Unit Card (Owner Residing): 'Flat 404' | Badge: 'Owner Primary' (Indigo) | Owner: 'Amitabh Sen' | 'Active Tickets: 0'.
Slide-over Drawer: Clicking any flat opens full Unit Profile with occupant list, vehicle registrations, and chronological service ticket log for that unit.
```

---

### Module 3: RWA Management Committee Executive Portal

#### Screen RWA-01: Executive Society Analytics & Governance Dashboard
* **Persona:** RWA President, Secretary, Treasurer, Committee Members.
* **Key Components:**
  * **Top Governance Alert Banner:** If any L3 SLA breaches exist, a persistent dismissible red banner appears with 1-click crisis review.
  * **Macro Society KPIs (5 Cards):**
    1. *Helpdesk Resolution Rate (30 Days)* (e.g., `96.8%`).
    2. *Average Resolution Time* (e.g., `2h 14m`).
    3. *Resident CSAT Satisfaction* (e.g., `4.82 / 5.0 ★` across 340 ratings).
    4. *Civic Governance Threads* (e.g., `8 In Discussion • 2 Action Taken`).
    5. *Monthly Maintenance Cost Burn* (e.g., `₹3,42,000 / ₹4,50,000 Budget`).
  * **Interactive Visualizations:**
    - Category-wise Ticket Distribution Donut Chart (Plumbing 35%, Electrical 28%, Lifts 15%, Civic 22%).
    - Daily Ticket Volume vs Resolution Trend (Spline Area Chart).
    - Technician & Vendor Performance Leaderboard.
* **Interactive Prompt:**
```text
Design a premier, executive-level Society Analytics Dashboard for RWA Management Committee Members in 'NivasOps'.
Theme: Ultra-luxurious Dark Mode (#0B0F17 base, #111827 cards, #1F2937 elevated surfaces, gold/amber accents for RWA prestige, vibrant data charts in cyan, purple, and emerald).
Top Bar: 'Prestige Lakeside Habitat RWA • Executive Operations Dashboard', Date Filter 'Current Quarter (Q3 2026)', Role Badge 'President: Col. R. K. Sharma (Retd.)', 'Download PDF Executive Brief' button.
Top Alert Banner: '⚠️ Level 3 Critical Escalation: 1 Ticket exceeds 24h SLA. Immediate Committee Review Required.' with 'Open Crisis Hub' button.
Top KPI Row:
- 'Helpdesk Resolution SLA' -> '97.2%' with +1.4% improvement trend.
- 'Average Resolution Turnaround' -> '1h 52m' (Fastest in Electrical).
- 'Community CSAT Index' -> '4.85 ★' (520 Verified Resident Reviews).
- 'Open Governance Discussions' -> '6 Active Threads' (AGM topics & parking policy).
- 'CapEx / OpEx Maintenance Burn' -> '₹2,84,000' (63% of Monthly Budget).
Data Visualizations (2-Column Layout):
Left Chart: 'Ticket Volume & Resolution Velocity' (Smooth spline chart comparing raised vs resolved over 30 days).
Right Chart: 'Category Breakdown & Repeat Issues' (Donut chart with glowing category segments).
Bottom Section: 'Vendor AMC Compliance Scorecard' table showing 4 contracted vendors (Elevators, DG Sets, Swimming Pool, Landscaping) with SLA health and contract expiry countdowns.
```

---

#### Screen RWA-02: L3 Escalation & Critical Risk Resolution Hub
* **Persona:** RWA President, Vice President, Secretary.
* **Key Components:**
  * Dedicated crisis management interface for tickets escalated to L3 (`>24h past SLA`).
  * Root-cause breakdown: Reason for delay (e.g., *Part out of stock*, *Vendor unresponsive*, *Technician shortage*).
  * Direct Committee Action Bar:
    - *Authorize Emergency Third-Party Contractor*
    - *Assign Direct Committee Sponsor*
    - *Issue Resident Formal Apology & Credit Memo*
  * Live Chat directly bridging Resident, Facility Manager, and Committee Executive.
* **Interactive Prompt:**
```text
Design an urgent L3 Critical Escalation & Crisis Resolution screen for RWA Committee Executives in 'NivasOps'.
Theme: High-stakes Dark Operations UI (#0B0F17 canvas, deep red #7F1D1D glowing card borders, crimson #EF4444 badges, stark white typography).
Header: 'Level 3 Escalation Emergency Response Hub' with subtitle 'Showing 1 critical ticket requiring executive committee intervention'.
Main Crisis Card (Large layout):
- Header: 'Ticket #SR-7810: Main Block C Water Booster Pump Failure (Affecting 48 Flats)' | Priority: 'P1 CRITICAL' | Escalation Level: 'L3 RWA FLAGGED'.
- Time Overdue: Large prominent counter '+31 Hours 45 Mins Past Target Resolution'.
- Root Cause Audit: 'In-house plumbing unable to source industrial 15HP pressure seal; primary AMC vendor failed to dispatch technician.'
- Impact Meter: 'High Severity • 48 Units Affected • 14 Escalated Complaints Linked'.
- Direct Action Toolbar:
  - Button 1 (Red Solid): 'Authorize Emergency External Vendor (₹15,000 Emergency Fund)'
  - Button 2 (Secondary): 'Summon Facility Manager for Video Briefing'
  - Button 3 (Ghost): 'Broadcast Status Update to Affected Tower C Residents'
Right Side: Direct Tri-Party Emergency Thread between RWA Secretary, Facility Manager, and Tower C Representative with timestamped voice note player and document attachments.
```

---

#### Screen RWA-03: Civic Governance & Committee Thread Center
* **Persona:** Committee Members, Residents (for public threads).
* **Key Components:**
  * Governance ticket workflow for civic matters (Noise complaints, Stray animals, Parking disputes, Club house rules, Renovation violations).
  * Lifecycle States: `Submitted -> Under Review -> In Discussion -> Action Taken -> Resolved -> Closed`.
  * Public vs Private Committee Thread toggle.
  * Formal "Record Official RWA Action" dialog to publish binding resolutions to residents.
  * Sentiment voting widget (Residents can upvote or support civic issues).
* **Interactive Prompt:**
```text
Design an elegant Civic Governance & Committee Discussion Forum screen for 'NivasOps'.
Theme: Dark SaaS Community aesthetic (#0B0F17 base, #111827 discussion cards, indigo #4F46E5 and emerald #10B981 highlights).
Header: 'Civic Governance & RWA Resolutions' with tab filters 'All Civic Issues (14)', 'Under Review (4)', 'In Discussion (6)', 'Action Taken (4)', and '+ Raise Civic Matter' button.
Main Feed (List of Governance Threads):
- Thread Card: 'Petition for Speed Bumps near Children\'s Play Area in Phase 2' | Category: 'Campus Safety' | Author: 'Meera Nambiar (Villa 18)' | Upvotes: '▲ 84 Residents Supported' | Status Pill: 'In Discussion (RWA Committee)' | Assigned to: 'Col. Sharma (President)'.
- Expanded Discussion Drawer:
  - Original complaint with attached photos of speeding vehicles.
  - Resident community comments stream.
  - 'Committee Executive Private Sub-Thread' (Gated to committee members with purple badge).
  - Bottom Action Box: 'Record Official RWA Action / Resolution' with rich text editor, PDF notice generator, and 'Publish Binding Society Order' CTA.
```

---

#### Screen RWA-04: High-Value Estimate CapEx Authorization
* **Persona:** RWA Treasurer, President, Secretary.
* **Key Components:**
  * Workflow for maintenance estimates exceeding standard FM operational limits (e.g., `> ₹10,000` requiring Treasurer sign-off).
  * Society Maintenance Reserve Fund live balance widget.
  * Quotation Comparison Matrix (3 Vendor Bids side-by-side with prices, warranty, and timelines).
  * 2-Key Approval System (e.g., Requires approval by both Treasurer and President).
* **Interactive Prompt:**
```text
Design a high-security CapEx & High-Value Maintenance Estimate Approval screen for the RWA Treasurer in 'NivasOps'.
Theme: Dark Luxury FinTech UI (#0B0F17 base, #111827 card containers, gold/emerald financial accents #10B981 & #F59E0B).
Header: 'CapEx & High-Value Maintenance Approvals' with 'Society Reserve Fund Balance: ₹18,42,000 Available'.
Approval Queue Card (Expanded):
- Title: 'Major Overhaul of Passenger Elevator #2 (Tower A)' | Amount: '₹68,500' | Ticket: '#SR-9204'.
- Approval Status: '1 of 2 Required Approvals Received (Secretary Approved ✓ • Awaiting Treasurer)'.
- Vendor Comparison Matrix (3 Columns):
  - Vendor A (Schindler Official): '₹68,500 • 2 Years Warranty • 3 Days Downtime' (Recommended).
  - Vendor B (Apex Lift Services): '₹54,000 • 6 Months Warranty • 5 Days Downtime'.
  - Vendor C (Local Tech AMC): '₹49,000 • No Warranty • 7 Days Downtime'.
- Action Bar:
  - 'Approve Expenditure (Draw from Elevator AMC Reserve)' with biometric/PIN confirmation prompt.
  - 'Reject with Remarks' / 'Request Lower Quotation'.
```

---

#### Screen RWA-05: AMC Vendor Performance & Compliance Scorecard
* **Persona:** RWA Committee Members, Estate Managers.
* **Key Components:**
  * Overview of all contracted Annual Maintenance Contracts (Elevators, Diesel Generators, Fire Safety, Landscaping, Swimming Pool, Security Systems).
  * Contract Details: Vendor Name, Contract Value, Start/End Date, Renewal Alert (`Expires in 45 Days`).
  * Live SLA Compliance Rate per vendor (e.g., *Schindler Lifts: 98.5% on-time response*).
  * Penalty & Deduction Calculator for breached SLAs.
* **Interactive Prompt:**
```text
Design a comprehensive AMC Vendor Performance & Contract Scorecard screen for 'NivasOps'.
Theme: Dark SaaS (#0B0F17 canvas, #111827 table cards, glowing progress rings, color-coded health badges).
Header: 'Annual Maintenance Contracts (AMC) & Vendor Scorecard' with '+ Onboard New AMC Vendor' and 'Generate Vendor Audit Report' buttons.
Vendor Card Grid (4 Key Contractors):
1. 'Otis Elevators India Ltd' | Scope: '12 Passenger Lifts across Towers A-D' | Contract: 'Valid until 31 Mar 2027 (218 days left)' | SLA Compliance: '99.1% (Exceptional)' | CSAT: '4.9 ★' | Active Tickets: '0 Open'.
2. 'Kirloskar DG Power Solutions' | Scope: '3x 500kVA Society Backup Generators' | Contract: 'Expires in 28 Days (Renewal Warning ⚠️)' | SLA Compliance: '94.0%' | Active Tickets: '1 In Progress'.
3. 'AquaPure Swimming & Water Solutions' | Scope: 'STP Plant & Pool Filtration' | Contract: 'Valid until 15 Nov 2026' | SLA Compliance: '86.5% (Underperforming - 3 Breaches)' | Penalty Accrued: '₹4,500 Deduction'.
Table View at Bottom: Detailed service logs, scheduled preventive maintenance visits, uploaded monthly service sheets, and vendor manager direct contact cards.
```

---

### Module 4: AMC Vendor & Contractor Portal

#### Screen VEN-01: AMC Vendor Overview Dashboard
* **Persona:** AMC Vendor Staff, Service Managers, Off-site Contractors.
* **Key Components:**
  * Society Selector (for vendors managing multiple residential contracts e.g., *Otis managing Prestige, Palm Meadows, and Brigade*).
  * Summary Cards: Active Service Tickets Assigned, Today's Scheduled Preventive Maintenance (PPM), Average Resolution Time, Monthly Service Billings.
  * Live Work Orders Queue with 1-click staff dispatch.
* **Interactive Prompt:**
```text
Design a high-efficiency AMC Vendor Operations Portal Dashboard for third-party contractor companies in 'NivasOps'.
Theme: Dark Slate Modern UI (#0B0F17 base, #111827 surfaces, vibrant blue #3B82F6 vendor branding, emerald #10B981 for completed work).
Top Header: Vendor Brand 'Apex Elevator & Electrical AMC Solutions' | Active Society Contract: 'Prestige Lakeside Habitat' | Switch Society Dropdown | User 'Karan Joshi (Service Coordinator)'.
Top Stat Cards:
- 'Assigned Open Work Orders' -> '4 Tickets' (1 Critical, 3 Routine).
- 'Preventive Maintenance (PPM) Visits Due' -> '2 Societies Today'.
- 'Vendor SLA Score' -> '98.2% On-Time'.
- 'Unbilled Service Value' -> '₹84,200 (12 Approved Invoices)'.
Main Work Order Table:
Columns: Ticket ID, Society Name, Equipment / Location ('Tower B - Elevator #1'), Issue Reported, Assigned Vendor Tech, SLA Target, Action Button ('Upload Service Certificate & Invoice').
```

---

#### Screen VEN-02: Vendor Work Order Execution & Certificate Vault
* **Persona:** Vendor Field Supervisor / Lead Technician.
* **Key Components:**
  * Detailed view of vendor-managed tickets.
  * Vendor Service Certificate Upload: Drag-and-drop signed physical job sheet / digital AMC service certificate (PDF/JPG).
  * Material parts utilized invoice upload.
  * One-click "Submit Completion & Resolve" action which triggers backend `is_vendor_managed` condition guard to close ticket without resident OTP if certified.
* **Interactive Prompt:**
```text
Design a streamlined Vendor Job Completion & Service Certificate Upload screen for 'NivasOps'.
Theme: Clean Dark SaaS UI (#0B0F17 background, #111827 modal/card container, cyan #06B6D4 and emerald #10B981 accents).
Header: 'Work Order #VEN-4029: Quarterly STP Filtration Maintenance & Pump Overhaul' | Society: 'Prestige Towers'.
Form Sections:
1. Job Execution Summary: Checkbox list of completed checklist items ('Filter Backwash', 'Chemical Dosing Check', 'Bearing Lubrication', 'Pressure Valve Calibration').
2. Material & Parts Replaced: Dynamic table to log parts used ('2x Carbon Filter Cartridges', '1x 50mm High-Pressure Gasket') with cost entry.
3. Digital Service Certificate Vault:
   - Large drag-and-drop upload zone: 'Upload Signed Customer Service Sheet / Vendor Inspection Certificate (PDF / Scanned Image)'.
   - Thumbnail preview of uploaded certificate with digital signature seal.
4. Remarks & Warranty: Text area for service notes and warranty period on parts (e.g., '6 Months Replacement Warranty').
Action Footer: 'Save Draft' and 'Submit Signed Certificate & Complete Work Order' (Solid Emerald button with checkmark icon).
```

---

#### Screen VEN-03: Vendor Staff & Field Roster
* **Persona:** Vendor Company Admin.
* **Key Components:**
  * Manage roster of technicians employed by the vendor who are deployed to client societies.
  * Assign vendor staff to specific society contracts.
  * Skill matrix and background verification badge (e.g., *Police Verified, Certified Lift Technician*).
* **Interactive Prompt:**
```text
Design a clean Vendor Field Staff & Technician Directory screen for 'NivasOps'.
Theme: Modern Dark Mode (#0B0F17 base, #111827 containers, blue #3B82F6 and indigo #4F46E5 accents).
Header: 'Vendor Field Workforce & Society Allocations' with '+ Deploy New Technician' button.
Technician Cards Grid:
- Card 1: 'Sandeep Varma' | Photo with green verified shield | Skills: 'Lifts, Escalators, Heavy Motors' | Assigned Societies: 'Prestige Habitat, Brigade Gateway' | Active Status: 'On Duty • 1 Active Job at Prestige' | Contact: '+91 98450 11223'.
- Card 2: 'Mohammad Farhan' | Skills: 'STP Plant, Swimming Pool Filtration' | Assigned Societies: 'Palm Meadows' | Active Status: 'Available for Dispatch'.
Drawer: Clicking on any staff member displays their certifications, police verification documents, and history of completed work orders across all societies.
```

---

### Module 5: Resident & Occupant Self-Service Portal

#### Screen RES-01: Resident Home & Helpdesk Portal
* **Persona:** Flat Owner, Co-Owner, Tenant, Family Member.
* **Key Components:**
  * **Top Welcome Bar:** Greeting (*"Welcome Home, Ananya"*), Flat Identifier (*Tower B - Flat 802*), Unit Switcher (if user owns multiple flats).
  * **Prominent Action Hub:**
    - Large Primary Button: `+ Raise New Request` (Gradient Indigo-Cyan CTA).
    - Emergency Helpdesk Hotline (1-click call Security Gate / Estate Office).
  * **Active Requests Status Carousel/List:**
    - Card for ongoing tickets with real-time status pill, assigned technician photo/name, estimated arrival time, and pending action badge (*"Approve Estimate ₹1,450"* or *"Share OTP on Completion"*).
  * **Society Noticeboard Snippet:** Latest RWA circulars, water maintenance alerts, or AGM updates.
* **Interactive Prompt:**
```text
Design a gorgeous, user-friendly Resident Helpdesk & Home Portal for apartment residents in 'NivasOps'.
Theme: Modern Premium Dark Mode (#0B0F17 background, glassmorphic #111827 card containers, electric indigo #4F46E5 & cyber cyan #06B6D4 glowing accents).
Top Header: 'Prestige Lakeside Habitat' | Unit Selector 'Tower B - Flat 802 (Owner)' | Notification Bell with badge '2' | User Profile Avatar.
Hero Section:
- Left: 'Welcome Home, Ananya Roy' with subtitle 'All society services are operational today'.
- Right: Large Glowing Gradient Button '+ Raise Helpdesk Request' with subtle animated pulse effect.
Active Tickets Live Section (Horizontal swipeable cards):
- Card 1 (In Progress): 'Kitchen Pipe Leakage (#SR-10492)' | Priority: P1 | Status: 'Technician Working at Flat' | Assigned Staff: 'Suresh M. (Plumber)' with avatar and phone icon | Action Pill: 'Share OTP after physical inspection'.
- Card 2 (Estimate Pending): 'Balcony Fan Regulator Replacement (#SR-10510)' | Status: 'Estimate Needs Your Approval' (Pink glowing badge) | Amount: '₹450' | 'Review & Approve ->' button.
Bottom Section (2 Columns):
- Left (50%): 'Recent Resolved Requests' with 1-click star rating prompt ('How was your electrical service yesterday? [★ ★ ★ ★ ★]').
- Right (50%): 'Society Operations Bulletins' showing notices ('Scheduled DG Maintenance on Thursday 10:00 - 12:00').
```

---

#### Screen RES-02: Ticket Creation Studio (Service vs Civic Wizard)
* **Persona:** Flat Owner, Tenant.
* **Key Components:**
  * Step 1: **Request Type Selector:**
    - Option A: *In-Flat / Service Request* (Plumbing, Electrical, Carpentry, Appliance, Pest Control).
    - Option B: *Society / Civic Governance Thread* (Common area lighting, Noise complaint, Stray dogs, Lift breakdown, Security).
  * Step 2: **Category & Subcategory Dynamic Grid:** Visual icons for categories with instant priority preview (e.g., *Plumbing > Pipe Burst = P1 Critical / 2-Hour SLA*).
  * Step 3: **Issue Details & Media Uploader:** Title, Description, Voice Note recorder, Photo/Video attachments (drag-and-drop with thumbnail previews).
  * Step 4: **Convenient Time Slot Picker:** Morning (09:00–12:00), Afternoon (13:00–17:00), Emergency / Immediate.
* **Interactive Prompt:**
```text
Design an intuitive, ultra-polished 3-Step Ticket Creation Studio for residents in 'NivasOps'.
Theme: Dark Mode Luxury UX (#0B0F17 base, #111827 form containers, electric indigo #4F46E5 primary CTA, crisp micro-interactions).
Top Progress Tracker: Step 1: Request Type -> Step 2: Category & Details -> Step 3: Preferred Time & Submit.
Step 1 Selection Cards (2 large interactive radio cards):
- Card 1 (Selected): 'Inside My Flat (Service Request)' with wrench icon. Subtitle: 'In-house plumbing, electrical, carpentry for Flat 802'.
- Card 2: 'Society Common Area / Civic Matter' with building icon. Subtitle: 'Lifts, clubhouse, common lighting, noise, or RWA governance'.
Step 2 Category Grid (Visual tile selectors):
- Tiles: 'Electrical', 'Plumbing', 'Carpentry', 'Appliance', 'Civil / Masonry', 'Pest Control'.
- Clicking 'Plumbing' expands subcategories: 'Tap Leakage', 'Pipe Burst (P1 Urgent)', 'Drain Clog', 'Flush Tank'.
Step 3 Form:
- Issue Title: 'Main Water Valve Under Sink Leaking Rapidly'.
- Description: Text area with AI auto-assist prompt 'Describe the exact location and severity...'.
- Media Uploader: Drag & Drop zone with 2 uploaded photos showing leak, plus a 'Record 30s Voice Note' mic button.
- Preferred Slot: 'Today: Immediate / As Soon As Possible (Emergency)'.
Footer: 'Expected Resolution Time: Within 2 Hours under Society P1 SLA' | 'Submit Request ->' button.
```

---

#### Screen RES-03: Resident Ticket Lifecycle & Live Tracker
* **Persona:** Flat Owner, Tenant.
* **Key Components:**
  * **Interactive FSM Timeline Tracker:** Visual vertical/horizontal tracker showing current stage: *Submitted -> Assigned -> Work in Progress -> OTP Verification -> Closed*.
  * **Technician Live Profile Card:** Photo, Name, Verified Skill Badge, Direct Call / WhatsApp button, Live Status (*"On the way to Tower B"*).
  * **Interactive In-App Thread:** Resident can chat directly with the technician/supervisor, send photos, or view supervisor notes.
  * **Live SLA Clock:** Visual reassurance showing expected resolution time.
* **Interactive Prompt:**
```text
Design a sleek, transparent Ticket Lifecycle & Real-Time Tracking screen for residents in 'NivasOps'.
Theme: Dark Mode (#0B0F17 canvas, #111827 card surfaces, glowing cyan #06B6D4 timeline, emerald #10B981 completed nodes).
Header: 'Ticket #SR-10492: Kitchen Pipe Leakage' | Priority: 'P1 Urgent' | Raised: 'Today at 13:45'.
Main View (2-Column Layout):
Left Column (50%): Visual Status Tracker & Technician Info:
- Stepper Timeline:
  - Node 1 (Checkmark Green): 'Request Submitted' (13:45)
  - Node 2 (Checkmark Green): 'Assigned to In-House Plumber' (13:48)
  - Node 3 (Glowing Cyan Pulse): 'Technician Working on Job' (14:15 - In Progress)
  - Node 4 (Upcoming Hollow): 'Physical Inspection & OTP Confirmation'
  - Node 5 (Upcoming Hollow): 'Resolution Complete'
- Technician Card: 'Suresh Mandanna' (Photo, 4.9 ★ rating, 'Society Certified Plumber'), 'Call Technician' button, 'Chat' button.
Right Column (50%): Conversation Thread & Updates:
- Chronological message bubbles between Resident and Suresh.
- Photo attachment sent by Suresh showing replaced valve.
- System Notice: 'Material estimate of ₹1,450 was approved at 14:20'.
- Bottom Input: 'Type a message or attach photo...' with send button.
```

---

#### Screen RES-04: Anti-Fraud OTP & Service Completion Modal
* **Persona:** Flat Owner, Tenant.
* **Key Components:**
  * **4-Digit OTP Display Card:** Large, high-visibility 4-digit code (e.g., `8 4 9 1`) with monospace numbers and subtle security pattern background.
  * **Prominent Security Warning Badge:**
    - *"⚠️ DO NOT share this OTP until you have physically inspected and verified that the repair is 100% completed."*
  * **15-Minute Expiration Countdown Timer:** e.g., `Valid for 11:42 mins`.
  * **CSAT & Star Rating Component (Appears post-completion):** 5 clickable stars, tag chips (*"Punctual"*, *"Clean Work"*, *"Polite"*, *"Fixed on first visit"*), and feedback text area.
* **Interactive Prompt:**
```text
Design a high-security Anti-Fraud OTP Verification and Star Rating Modal for residents in 'NivasOps'.
Theme: Dark Mode Luxury with gold/amber security accents (#111827 card background, #000000CC frosted backdrop, amber border #F59E0B).
Modal Content:
Top Header: Shield icon with 'Service Completion Handshake — Ticket #SR-10492'.
OTP Display Box:
- A prominent, glowing glassmorphic container displaying a 4-digit numeric code in large bold typography: [ 8 ] [ 4 ] [ 9 ] [ 1 ].
- Monospace font (JetBrains Mono), glowing amber outlines.
- Subtitle: 'Share this 4-digit code with Technician Suresh Mandanna ONLY after verifying physical repair.'
Anti-Fraud Warning Notice:
- Amber warning callout banner: '🔒 Anti-Fraud Protection: Entering this code permanently marks the job as resolved and authorizes labor closure. Do not share over the phone.'
- Expiry Timer: 'OTP Expires in 11:24 mins • [Generate New Code]'.
Post-Verification Rating State (Sub-screen preview):
- 'Rate Your Experience with Suresh Mandanna'
- 5 Golden glowing interactive stars (5/5 selected).
- Feedback chip selector: ['Punctual', 'Clean Workmanship', 'Courteous', 'Fast Fix'].
- 'Add comments (optional)' text input.
- 'Submit Feedback & Close' CTA button.
```

---

#### Screen RES-05: Material Estimate Review & 1-Click Action Modal
* **Persona:** Flat Owner, Tenant.
* **Key Components:**
  * Triggered when technician requests replacement parts.
  * **Detailed Cost Breakdown:** Line items for hardware parts (Part name, quantity, estimated cost), Labor cost (marked as `₹0 - Society AMC Covered`), Total Amount.
  * **Hardware Store Quotation / Photo Attachment Preview.**
  * **Dual 1-Click Action Buttons:**
    - `Approve Estimate (₹1,450)` (Green solid button).
    - `Reject / Discuss with Supervisor` (Red outline button, opens rejection reason selector).
  * Informational Note: *"Approving this estimate resumes the SLA clock immediately."*
* **Interactive Prompt:**
```text
Design an intuitive Material Estimate Approval & Cost Review Modal for residents in 'NivasOps'.
Theme: Dark UI (#111827 container, #1F2937 inner tables, emerald #10B981 for approval, rose #F43F5E for rejection).
Modal Header: 'Material Cost Estimate Approval — Ticket #SR-10492' with subtitle 'Technician has requested approval for replacement parts'.
Content Layout:
- Itemized Parts Table:
  - Row 1: 'Heavy Brass Angle Valve (1/2 inch)' | Qty: 1 | Price: '₹850.00'
  - Row 2: 'CPVC Braided Connection Hose (450mm)' | Qty: 1 | Price: '₹350.00'
  - Row 3: 'Teflon Tape + Solvent Sealant' | Qty: 1 | Price: '₹100.00'
  - Row 4: 'Standard Labor Charges' | Qty: 1 | Price: '₹0.00 (Covered by Society Maintenance)'
- Total Summary Card:
  - Large display: 'Total Estimated Cost: ₹1,300.00' (Inclusive of GST).
- Attachment Thumbnail: 'View Hardware Store Estimate Slip (JPG)'.
- Important Notice: 'Note: Approval authorizes the technician to procure these materials immediately. Payment will be collected upon job completion.'
Action Buttons (Full width dual grid):
- Left: 'Reject Estimate' (Opens quick reason prompt: 'Too expensive', 'Will purchase myself', 'Not required').
- Right: 'Approve Estimate & Resume Work' (Solid emerald glowing button with checkmark icon).
```

---

#### Screen RES-06: My Unit & Household Profile
* **Persona:** Flat Owner, Tenant.
* **Key Components:**
  * Household details for *Tower B - Flat 802*.
  * List of registered occupants (Owner, Co-owner, Tenant, Family members) with role badges and active status.
  * Tenant Lease Management (for owners): Lease Start/End dates, digital tenancy agreement attachment, automated renewal alert settings.
  * Registered Vehicles list (Parking Slot #B2-44, RFID Tag ID, 2 Cars, 1 Bike).
* **Interactive Prompt:**
```text
Design a modern Unit & Household Profile Management screen for residents in 'NivasOps'.
Theme: Dark Mode SaaS (#0B0F17 base, #111827 card containers, indigo #4F46E5 and cyan #06B6D4 accents).
Header: 'My Unit & Household: Tower B - Flat 802' with role badge 'Primary Owner'.
Top Tabs: 'Occupants & Family', 'Tenancy & Lease', 'Vehicles & Parking', 'Unit Ticket History'.
Tab 1 Content (Occupants Grid):
- Occupant Card 1: 'Ananya Roy' | Role: 'Primary Owner' | Phone: '+91 98450 XXXXX' | 'Primary Contact (Active)'.
- Occupant Card 2: 'Siddharth Roy' | Role: 'Co-Owner / Family' | Phone: '+91 98451 XXXXX'.
- Occupant Card 3: 'Aarav Roy' | Role: 'Family Member'.
- '+ Add Family Member / Tenant' button.
Tab 2 Content (Tenancy Overview):
- 'Lease Management Status' -> 'Currently Owner Occupied (Self)'.
- Toggle: 'Mark as Rented / Add Tenant Occupancy' with lease start and end date pickers.
Tab 3 Content (Vehicles):
- Vehicle Tag Card: 'KA-03-MM-8921 (Honda City)' | Parking Slot: 'B2 - 44' | FastTag / RFID: 'ACTIVE'.
```

---

### Module 6: Society Administration & Policy Studio

#### Screen CFG-01: Category, Sub-Category & Skill Studio
* **Persona:** Society SuperAdmin, Facility Director.
* **Key Components:**
  * Hierarchical tree manager for service ticket categories (Electrical, Plumbing, HVAC, Elevators, Civil, Security, Gardening).
  * Sub-category configurator: Name, Default Priority (`P1`, `P2`, `P3`, `P4`), Required Technician Skill binding (`Skill: High Voltage Licensed`, `Skill: Master Plumber`).
  * "Is Governance / Civic Category" toggle switch (routes ticket to Committee workflow instead of Field Service FSM).
* **Interactive Prompt:**
```text
Design a powerful Category, Sub-Category & Skill Configuration Studio for 'NivasOps'.
Theme: Dark SaaS System Studio (#0B0F17 base, #111827 tree panels, #1F2937 configuration cards, indigo #4F46E5 accents).
Header: 'Ticket Categories & Skill Dispatch Matrix' with '+ New Category' and 'Export Schema' buttons.
Layout (2-Column Studio):
Left Panel (35%): Interactive Category Hierarchy Tree:
- Tree nodes: '⚡ Electrical (12 Subcategories)', '🔧 Plumbing (8 Subcategories)', '🚪 Carpentry (5)', '🏛️ Governance & Civic (6)', '🌿 Landscaping (3)'.
- Drag-and-drop reordering, active node highlight.
Right Panel (65%): Detailed Configuration for selected node ('Plumbing > Pipe Burst'):
- Field 1: Category Name: 'Pipe Burst & Major Leakage'.
- Field 2: Workflow Route: Toggle [Field Service Dispatch (FSM)] vs [Civic Governance Thread].
- Field 3: Required Skill Binding: Dropdown 'Master Plumber (Commercial Piping)'.
- Field 4: Default Priority: Segmented control [P1 Critical] [P2 High] [P3 Medium] [P4 Low].
- Field 5: Auto-Dispatch Policy: Toggle 'Enable Auto-Routing to On-Duty Techs with Shift Matching'.
- Bottom Action: 'Save Changes' with toast confirmation preview.
```

---

#### Screen CFG-02: SLA Policy & Escalation Matrix Configurator
* **Persona:** Society SuperAdmin, RWA Executive.
* **Key Components:**
  * Matrix editor for SLA policies across P1, P2, P3, P4 priorities and Governance tickets.
  * Configurable parameters per priority:
    - *Technician Acceptance Timeout* (e.g., P1: 15 mins, P2: 30 mins, P3: 60 mins).
    - *Target Resolution Hours* (e.g., P1: 2 hours, P2: 6 hours, P3: 24 hours, P4: 48 hours).
    - *Re-open Resolution Hours* (e.g., P1: 1 hour, P2: 4 hours, P3: 12 hours).
    - *Auto-Pause Triggers* (Pending estimate approval, Night quiet hours 22:00–07:00).
* **Interactive Prompt:**
```text
Design an enterprise SLA Policy & Escalation Matrix Configurator screen for 'NivasOps'.
Theme: High-precision Dark SaaS (#0B0F17 background, #111827 matrix tables, #1F2937 slider cards, color-coded priority columns).
Header: 'SLA Policies & Automated Escalation Timers' with 'Reset to Standard Society Bylaws' and 'Deploy Policy' buttons.
Main SLA Configuration Matrix (4 Interactive Priority Cards):
1. Card P1 (Critical - Red #EF4444):
   - Acceptance Timeout Slider: '15 Minutes'
   - Target Resolution Slider: '2 Hours'
   - Reopen Resolution Slider: '1 Hour'
   - Escalation Rules: 'L1 Requeue at 15m -> L2 FM Alert at 2h -> L3 RWA Board at 24h past target'.
2. Card P2 (High - Orange #F97316):
   - Acceptance Timeout: '30 Minutes' | Target Resolution: '6 Hours' | Reopen Resolution: '4 Hours'.
3. Card P3 (Medium - Amber #F59E0B):
   - Acceptance Timeout: '60 Minutes' | Target Resolution: '24 Hours' | Reopen Resolution: '12 Hours'.
4. Card P4 (Low - Green #10B981):
   - Acceptance Timeout: '120 Minutes' | Target Resolution: '48 Hours' | Reopen Resolution: '24 Hours'.
Bottom Settings Card:
- 'SLA Pause Configuration': Checkboxes for 'Pause during resident estimate review', 'Pause during night quiet hours (22:00 to 07:00)', 'Pause on resident request'.
```

---

#### Screen CFG-03: AMC Contracts & Vendor Onboarding Manager
* **Persona:** Society SuperAdmin, Facility Manager.
* **Key Components:**
  * Master directory of all vendor companies and contracts.
  * Form to onboard a new vendor: Company Name, GST Number, Contact Person, Phone, Email, Contract Start & End Dates, Category Binding (e.g., *Otis bound to Elevator Category*).
  * Auto-dispatch binding (Tickets in this category automatically route to this AMC vendor).
* **Interactive Prompt:**
```text
Design a comprehensive AMC Contracts & Vendor Onboarding Manager screen for 'NivasOps'.
Theme: Dark Mode SaaS (#0B0F17 canvas, #111827 containers, indigo #4F46E5 & emerald #10B981 accents).
Header: 'AMC Vendor Contracts & Master Agreements' with '+ Onboard New AMC Vendor' button.
Vendor Directory Table:
- Columns: Vendor Company Name, Service Category, Contact Person, Phone/Email, Contract Term (Start - End), Status Pill ('Active', 'Expiring in 30 Days', 'Terminated'), Actions ('Edit Contract', 'View Staff Roster', 'Deactivate').
Slide-over Modal: 'Onboard New Vendor Agreement':
- Input 1: Vendor Company: 'Schindler Lifts India Pvt Ltd'.
- Input 2: Bound Service Category: Dropdown 'Elevators & Escalators'.
- Input 3: Contract Validity: Date Range Picker '01 Apr 2026 to 31 Mar 2027'.
- Input 4: Direct Auto-Dispatch: Toggle 'Automatically assign all new elevator tickets to this vendor contract'.
- Input 5: Service Level Agreement: Upload Master AMC Agreement PDF.
- Button: 'Save & Activate Vendor Contract'.
```

---

#### Screen CFG-04: Audit Vault & Security Compliance Logs
* **Persona:** SuperAdmin, RWA Auditor, Society Legal Counsel.
* **Key Components:**
  * Immutable viewer for all system `TicketEvent` records.
  * Filter by Event Type: `TECH_REJECT_REQUEUE`, `SLA_L2_ESCALATION`, `SLA_L3_ESCALATION`, `SUPERVISOR_OVERRIDE`, `OTP_FAILED_ATTEMPT`, `ESTIMATE_APPROVED`.
  * Anomaly detection flags (e.g., 3 consecutive OTP failures on Flat 402, Supervisor override by User X with attached reason).
  * One-click tamper-evident cryptographic export (JSON/CSV with SHA-256 integrity hashes).
* **Interactive Prompt:**
```text
Design an immutable, forensic Audit Vault & Security Compliance Log screen for 'NivasOps'.
Theme: High-Security Dark Terminal & SaaS hybrid (#0B0F17 background, #111827 log viewer, JetBrains Mono typography for hash/event IDs, amber/crimson anomaly tags).
Header: 'Cryptographic Audit Vault & Immutable Event Trail' with 'Export Certified Audit Log (SHA-256)' and 'Date Filter: Last 90 Days'.
Top Anomaly KPI Row:
- 'Total Audit Events Logged' -> '14,892 Events'.
- 'Supervisor Overrides' -> '3 Events' (Requires verified justifications).
- 'OTP Failure Anomalies' -> '1 Flagged' (Flat 402 exceeded 3 attempts).
- 'SLA Breaches Recorded' -> '12 Events'.
Forensic Event Table:
Columns: Timestamp (ISO format), Event Type Badge ('SUPERVISOR_OVERRIDE' in Amber, 'SLA_L2_ESCALATION' in Red, 'OTP_VERIFIED' in Green), Ticket ID (#SR-10492), Actor ('Rajesh Verma - FM'), State Shift ('PENDING_OTP -> RESOLVED'), Remarks / Justification ('Physical work verified on-site by supervisor; resident mobile unreachable'), Proof Attachment ('view_proof.jpg').
Expanding any row shows full JSON payload with database transaction IDs and client IP stamps.
```

---

## 5. Interactive Micro-States & Edge Case Guide

To guarantee a world-class user experience, the web app designs must account for these critical operational edge cases:

| Edge Case / State | Visual & Functional Behavior |
| :--- | :--- |
| **Technician Rejection (> 3x Requeue)** | Ticket automatically transitions to `SUPERVISOR_TRIAGE`. Card in FM console glows with an amber warning badge: *"Auto-dispatch failed 3 times. Manual allocation required."* |
| **OTP Brute-Force Lockout (3 Failures)** | After 3 invalid OTP attempts, the input is permanently locked. Banner displays: *"Maximum OTP attempts exceeded. Contact Facility Manager for on-site physical verification override."* |
| **SLA Clock Paused State** | SLA timer changes to amber with a pause symbol `⏸️ Paused (Estimate Review)`. The countdown stops and accumulator logs total paused seconds. |
| **Level 3 Crisis Breach (> 24h Overdue)** | Top navigation bar displays a persistent crimson alert banner across all RWA Committee screens. Card pulses with a red glow and priority escalation tag. |
| **Estimate Rejected by Resident** | Ticket shifts to `SUPERVISOR_TRIAGE` state. Supervisor receives push notification to renegotiate parts or cancel the job. |
| **Multi-Society Role Switching** | Instant top-left dropdown switches tenant header `X-Society-ID` and hot-reloads permissions without requiring re-authentication. |

---

## 6. Summary of Deliverables & Next Steps

This document provides:
1. Complete structural taxonomy of all **28 web application screens** spanning 6 operational modules.
2. Production-grade **copy-pasteable design prompts** tailored for AI UI generators, Figma prompt-to-design workflows, or Next.js / Tailwind / Vanilla CSS coding agents.
3. Strict alignment with backend FSM states, data models, multi-tenancy middleware, and SLA escalation rules.

*Next Phase:* Proceed with front-end component scaffolding or screen-by-screen code generation using these detailed specifications.
