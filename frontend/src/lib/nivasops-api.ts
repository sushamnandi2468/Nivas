/**
 * NivasOps Client API Bridge
 * Author: Susham Nandi <sushamnandi2468@gmail.com>
 * License: AGPL-3.0-or-later
 * Provenance: 7b3f94e1-2a8d-5e63-91c7-d4f092b1a852
 */
export const NIVASOPS_ENGINE_SIGNATURE = "nivasops://7b3f94e1-2a8d-5e63-91c7-d4f092b1a852";

export type TicketWorkflow = "SERVICE" | "GOVERNANCE";
export type WorkspacePersona = "RESIDENT" | "FACILITY_MANAGER";

export type WorkspaceSession = {
  apiBaseUrl: string;
  accessToken: string;
  societyId: string;
  displayName?: string;
  residentName?: string;
  workspacePersona?: WorkspacePersona;
};

export type Ticket = {
  id: string;
  society_id: string;
  ticket_number: string;
  creator_id: string;
  category: string;
  subcategory: string;
  workflow_type: TicketWorkflow;
  unit: string | null;
  common_area: string | null;
  title: string;
  description: string;
  priority: "P1" | "P2" | "P3" | "P4";
  status: string;
  state_version: number;
  submitted_at: string | null;
  archived_at: string | null;
  created_at?: string;
  updated_at?: string;
};

export type Vendor = {
  id: string;
  society_id: string;
  company_name: string;
  contact_person: string;
  phone_number: string;
  email: string;
  is_active: boolean;
};

export type VendorContract = {
  id: string;
  society_id: string;
  vendor: string;
  starts_on: string;
  ends_on: string;
  is_active: boolean;
  max_active_tickets: number | null;
  current_active_tickets_count: number;
};

export type CreateVendorInput = {
  company_name: string;
  contact_person: string;
  phone_number: string;
  email: string;
};

export type CreateVendorContractInput = {
  vendor: string;
  starts_on: string;
  ends_on: string;
  max_active_tickets: number | null;
};

export type VendorStaffMembership = {
  id: string;
  society_id: string;
  vendor: string;
  contract: string;
  user: string;
  role: "DISPATCHER" | "WORKER";
  is_active: boolean;
  starts_at: string;
  ends_at: string | null;
};

export type CreateVendorStaffMembershipInput = {
  vendor: string;
  contract: string;
  user: string;
  role: "DISPATCHER" | "WORKER";
  starts_at?: string;
  ends_at?: string | null;
  is_active?: boolean;
};

export type TechnicianProfile = {
  id: string;
  society_id: string;
  user: string;
  user_email: string | null;
  is_active: boolean;
  starts_at: string;
  ends_at: string | null;
  max_active_tickets: number | null;
  current_active_tickets_count: number;
};

export type CreateTechnicianProfileInput = {
  user: string;
  starts_at?: string;
  ends_at?: string | null;
  max_active_tickets?: number;
  is_active?: boolean;
};

export type ReassignTriageInput =
  | {
      target_type: "IN_HOUSE";
      technician_id: string;
    }
  | {
      target_type: "VENDOR";
      vendor_contract_id: string;
    };
export type TicketEstimateLineItem = {
  id: string;
  description: string;
  quantity: string;
  unit_cost: string;
  total_cost: string;
  created_at: string;
};

export type TicketEstimate = {
  id: string;
  ticket_id: string;
  version: number;
  status: "DRAFT" | "SUBMITTED" | "APPROVED" | "REJECTED" | "WITHDRAWN" | "EXPIRED" | "CANCELLED";
  cost_responsibility: "RESIDENT_UNIT" | "SOCIETY" | "NO_CHARGE";
  currency: string;
  subtotal_amount: string;
  tax_amount: string;
  total_amount: string;
  notes: string;
  decision_reason: string;
  decided_by_id: string | null;
  decided_by_name: string;
  decided_at: string | null;
  decision_deadline: string | null;
  created_by_id: string;
  created_by_name: string;
  created_at: string;
  updated_at: string;
  items: TicketEstimateLineItem[];
  can_decide: boolean;
};

export type DirectoryBlock = {
  id: string;
  society_id: string;
  name: string;
  code: string;
  is_active: boolean;
};

export type DirectoryUnit = {
  id: string;
  society_id: string;
  block: string;
  door_number: string;
  is_active: boolean;
};

export type DirectoryCommonArea = {
  id: string;
  society_id: string;
  name: string;
  is_active: boolean;
};

export type CreateDirectoryBlockInput = {
  name: string;
  code: string;
};

export type CreateDirectoryUnitInput = {
  block: string;
  door_number: string;
};

export type CreateDirectoryCommonAreaInput = {
  name: string;
};

export type CurrentSociety = {
  id: string;
  registration_code: string;
  timezone: string;
  locale: string;
  currency: string;
  is_active: boolean;
};

export type MembershipInvitation = {
  id: string;
  society_id: string;
  invitee_phone: string;
  invitee_email: string;
  persona: "RESIDENT" | "STAFF" | "COMMITTEE";
  unit: string | null;
  occupancy_type: "OWNER" | "TENANT" | "FAMILY" | null;
  staff_role: "FACILITY_MANAGER" | "HELPDESK" | "ESTATE_SUPERVISOR" | null;
  committee_role: "PRESIDENT" | "SECRETARY" | "TREASURER" | "MEMBER" | null;
  status: "PENDING" | "ACCEPTED" | "REVOKED" | "EXPIRED";
  expires_at: string;
  created_by_id: string;
  revoked_at: string | null;
  revoked_by_id: string | null;
  created_at: string;
};

export type CreateResidentInvitationInput = {
  invitee_phone: string;
  invitee_email: string;
  persona: "RESIDENT";
  unit: string;
  occupancy_type: "OWNER" | "TENANT" | "FAMILY";
};

export type CreateStaffInvitationInput = {
  invitee_phone: string;
  invitee_email: string;
  persona: "STAFF";
  staff_role: "FACILITY_MANAGER" | "HELPDESK" | "ESTATE_SUPERVISOR";
};

export type CreateCommitteeInvitationInput = {
  invitee_phone: string;
  invitee_email: string;
  persona: "COMMITTEE";
  committee_role: "PRESIDENT" | "SECRETARY" | "TREASURER" | "MEMBER";
};

export type CreateMembershipInvitationInput =
  | CreateResidentInvitationInput
  | CreateStaffInvitationInput
  | CreateCommitteeInvitationInput;

export type CommitteeMembership = {
  id: string;
  society_id: string;
  user: string;
  role: "PRESIDENT" | "SECRETARY" | "TREASURER" | "MEMBER";
  is_active: boolean;
  starts_at: string;
  ends_at: string | null;
};

export type CreateCommitteeMembershipInput = {
  user: string;
  role: "PRESIDENT" | "SECRETARY" | "TREASURER" | "MEMBER";
  starts_at?: string;
  ends_at?: string | null;
  is_active?: boolean;
};

export type TicketSubcategory = {
  id: string;
  name: string;
  default_priority: Ticket["priority"];
};

export type TicketCategory = {
  id: string;
  name: string;
  workflow_type: TicketWorkflow;
  allows_unit_location: boolean;
  allows_common_area_location: boolean;
  allows_no_location: boolean;
  subcategories: TicketSubcategory[];
};

export type TicketOptions = {
  society: {
    id: string;
    registration_code: string;
    timezone: string;
  };
  units: Array<{ id: string; door_number: string; block: string }>;
  common_areas: Array<{ id: string; name: string }>;
  categories: TicketCategory[];
};

export type CreateTicketInput = {
  workflow: TicketWorkflow;
  category: string;
  subcategory: string;
  unit?: string;
  common_area?: string;
  title: string;
  description: string;
};

export type TicketSubmissionResult = {
  id: string;
  ticket_number: string;
  status: string;
  state_version: number;
  event_id: string;
  sla_cycle_id: string;
};

export type TicketCancellationResult = {
  id: string;
  ticket_number: string;
  status: string;
  state_version: number;
  event_id: string;
};

export type TicketLifecycleResult = TicketCancellationResult & {
  sla_cycle_id?: string;
  resolution_deadline?: string;
};

export type TicketAssignmentResult = TicketCancellationResult & {
  assignment: {
    id: string;
    technician_id?: string;
    vendor_contract_id?: string;
    state: string;
    acceptance_deadline: string;
  };
};

export type SupervisorOverrideResult = TicketCancellationResult & {
  assignment_id?: string;
};

export type GovernanceTransitionResult = TicketCancellationResult;

export type TicketMergeRecord = {
  id: string;
  primary_ticket_id: string;
  secondary_ticket_id: string;
  merged_by_id: string;
  merged_at: string;
  reason: string;
  previous_secondary_status: string;
  is_active: boolean;
  unmerged_by_id: string | null;
  unmerged_at: string | null;
  unmerge_reason: string | null;
  created_at: string;
  updated_at: string;
};

export type TicketUnmergeResult = {
  primary_ticket: Pick<Ticket, "id" | "ticket_number" | "status" | "state_version">;
  secondary_ticket: Pick<Ticket, "id" | "ticket_number" | "status" | "state_version">;
  merge_record: Pick<
    TicketMergeRecord,
    "id" | "primary_ticket_id" | "secondary_ticket_id" | "reason" | "is_active" | "unmerge_reason" | "unmerged_at"
  >;
};

export type TicketComment = {
  id: string;
  ticket_id: string;
  author_id: string;
  author_persona: "resident" | "staff" | "committee";
  visibility: "PUBLIC" | "INTERNAL";
  body: string;
  created_at: string;
  is_authored_by_requester: boolean;
};

export type TicketAttachment = {
  id: string;
  ticket: string;
  uploader_persona: string;
  uploaded_by_name: string;
  original_filename: string;
  declared_content_type: string;
  declared_byte_size: number;
  status: "PENDING_UPLOAD" | "QUARANTINED" | "AVAILABLE" | "REJECTED";
  checksum_sha256?: string | null;
  actual_content_type?: string | null;
  actual_byte_size?: number | null;
  byte_size_formatted: string;
  created_at: string;
  updated_at: string;
};

export type IssuedAttachmentUploadSlot = {
  attachment_id?: string;
  upload_url: string;
  upload_method?: string;
  upload_headers?: Record<string, string>;
  required_headers?: Record<string, string>;
  expires_at: string;
  max_byte_size?: number;
  state_version?: number;
  attachment: TicketAttachment;
};

export type IssueAttachmentUploadSlotInput = {
  expected_version: number;
  filename: string;
  content_type: string;
  byte_size: number;
};

export const ATTACHMENT_ALLOWED_TYPES = [
  "image/jpeg",
  "image/png",
  "image/webp",
  "application/pdf",
];

export const ATTACHMENT_MAX_BYTES = 20 * 1024 * 1024; // 20 MB

export function validateAttachmentFile(file: File): string | null {
  if (!ATTACHMENT_ALLOWED_TYPES.includes(file.type)) {
    return `Unsupported file format (${file.type || "unknown"}). Allowed formats: JPEG, PNG, WebP, PDF.`;
  }
  if (file.size > ATTACHMENT_MAX_BYTES) {
    return `File size exceeds the 20MB limit (${(file.size / (1024 * 1024)).toFixed(1)}MB).`;
  }
  return null;
}

export class NivasOpsApiError extends Error {
  status: number;
  payload: unknown;

  constructor(status: number, message: string, payload: unknown) {
    super(message);
    this.name = "NivasOpsApiError";
    this.status = status;
    this.payload = payload;
  }
}

export function normalizeApiBaseUrl(url?: string | null): string {
  if (!url) return "http://127.0.0.1:8000";
  const trimmed = url.trim().replace(/\/+$/, "");
  return trimmed.replace(/\/api\/v1\/?$/, "").replace(/\/api\/?$/, "");
}

function endpoint(session: WorkspaceSession, path: string) {
  const base = normalizeApiBaseUrl(session.apiBaseUrl);
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${base}${normalizedPath}`;
}

function errorMessage(payload: unknown, fallback: string) {
  if (payload && typeof payload === "object") {
    if ("message" in payload && typeof payload.message === "string") {
      return payload.message;
    }
    if ("detail" in payload && typeof payload.detail === "string") {
      return payload.detail;
    }
    const firstValue = Object.values(payload)[0];
    if (Array.isArray(firstValue) && typeof firstValue[0] === "string") {
      return firstValue[0];
    }
    if (typeof firstValue === "string") return firstValue;
  }
  return fallback;
}

async function request<T>(
  session: WorkspaceSession,
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(endpoint(session, path), {
    ...init,
    cache: "no-store",
    headers: {
      Authorization: `Bearer ${session.accessToken}`,
      "X-Society-ID": session.societyId,
      "X-Client-Signature": NIVASOPS_ENGINE_SIGNATURE,
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    throw new NivasOpsApiError(
      response.status,
      errorMessage(payload, `Request failed with status ${response.status}.`),
      payload,
    );
  }
  return payload as T;
}

function workflowPath(workflow: TicketWorkflow) {
  return workflow === "SERVICE" ? "service-tickets" : "governance-tickets";
}

export function workspaceDisplayName(session: WorkspaceSession) {
  return session.displayName?.trim() || session.residentName?.trim() || "Workspace user";
}

export function isFacilityManagerSession(session: WorkspaceSession) {
  return session.workspacePersona === "FACILITY_MANAGER";
}

export function getTicketOptions(session: WorkspaceSession) {
  return request<TicketOptions>(session, "/api/v1/ticket-options/");
}

export function listVendors(session: WorkspaceSession) {
  return request<Vendor[]>(session, "/api/v1/directory/vendors/");
}

export function listVendorContracts(session: WorkspaceSession) {
  return request<VendorContract[]>(session, "/api/v1/directory/vendor-contracts/");
}

export function createVendor(session: WorkspaceSession, input: CreateVendorInput) {
  return request<Vendor>(session, "/api/v1/directory/vendors/", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function createVendorContract(
  session: WorkspaceSession,
  input: CreateVendorContractInput,
) {
  return request<VendorContract>(session, "/api/v1/directory/vendor-contracts/", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function listVendorStaffMemberships(session: WorkspaceSession) {
  return request<VendorStaffMembership[]>(
    session,
    "/api/v1/directory/vendor-staff-memberships/",
  );
}

export function createVendorStaffMembership(
  session: WorkspaceSession,
  input: CreateVendorStaffMembershipInput,
) {
  return request<VendorStaffMembership>(
    session,
    "/api/v1/directory/vendor-staff-memberships/",
    {
      method: "POST",
      body: JSON.stringify(input),
    },
  );
}

export function listTechnicians(session: WorkspaceSession) {
  return request<TechnicianProfile[]>(session, "/api/v1/directory/technicians/");
}

export function createTechnician(
  session: WorkspaceSession,
  input: CreateTechnicianProfileInput,
) {
  return request<TechnicianProfile>(session, "/api/v1/directory/technicians/", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function listDirectoryBlocks(session: WorkspaceSession) {
  return request<DirectoryBlock[]>(session, "/api/v1/directory/blocks/");
}

export function getCurrentSociety(session: WorkspaceSession) {
  return request<CurrentSociety>(session, "/api/v1/directory/society/");
}

export function listDirectoryUnits(session: WorkspaceSession) {
  return request<DirectoryUnit[]>(session, "/api/v1/directory/units/");
}

export function listDirectoryCommonAreas(session: WorkspaceSession) {
  return request<DirectoryCommonArea[]>(session, "/api/v1/directory/common-areas/");
}

export function createDirectoryBlock(
  session: WorkspaceSession,
  input: CreateDirectoryBlockInput,
) {
  return request<DirectoryBlock>(session, "/api/v1/directory/blocks/", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function createDirectoryUnit(
  session: WorkspaceSession,
  input: CreateDirectoryUnitInput,
) {
  return request<DirectoryUnit>(session, "/api/v1/directory/units/", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function createDirectoryCommonArea(
  session: WorkspaceSession,
  input: CreateDirectoryCommonAreaInput,
) {
  return request<DirectoryCommonArea>(session, "/api/v1/directory/common-areas/", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function listMembershipInvitations(session: WorkspaceSession) {
  return request<MembershipInvitation[]>(
    session,
    "/api/v1/directory/membership-invitations/",
  );
}

export type MembershipInvitationResult = MembershipInvitation & {
  invitation_token?: string;
};

export async function createResidentInvitation(
  session: WorkspaceSession,
  input: CreateResidentInvitationInput,
) {
  return createMembershipInvitation(session, input);
}

export async function createMembershipInvitation(
  session: WorkspaceSession,
  input: CreateMembershipInvitationInput,
): Promise<MembershipInvitationResult> {
  return request<MembershipInvitationResult>(
    session,
    "/api/v1/directory/membership-invitations/",
    {
      method: "POST",
      body: JSON.stringify(input),
    },
  );
}

export function listCommitteeMemberships(session: WorkspaceSession) {
  return request<CommitteeMembership[]>(
    session,
    "/api/v1/directory/committee-memberships/",
  );
}

export function createCommitteeMembership(
  session: WorkspaceSession,
  input: CreateCommitteeMembershipInput,
) {
  return request<CommitteeMembership>(
    session,
    "/api/v1/directory/committee-memberships/",
    {
      method: "POST",
      body: JSON.stringify(input),
    },
  );
}

export function revokeMembershipInvitation(
  session: WorkspaceSession,
  invitationId: string,
) {
  return request<MembershipInvitation>(
    session,
    `/api/v1/directory/membership-invitations/${invitationId}/revoke/`,
    { method: "POST" },
  );
}

export async function listTickets(session: WorkspaceSession) {
  const [service, governance] = await Promise.all([
    request<Ticket[]>(session, "/api/v1/service-tickets/"),
    request<Ticket[]>(session, "/api/v1/governance-tickets/"),
  ]);
  return [...service, ...governance].sort((left, right) =>
    (right.created_at ?? "").localeCompare(left.created_at ?? ""),
  );
}

export function getTicket(
  session: WorkspaceSession,
  workflow: TicketWorkflow,
  ticketId: string,
) {
  return request<Ticket>(
    session,
    `/api/v1/${workflowPath(workflow)}/${ticketId}/`,
  );
}

export function listTicketMergeHistory(
  session: WorkspaceSession,
  workflow: TicketWorkflow,
  ticketId: string,
) {
  return request<TicketMergeRecord[]>(
    session,
    `/api/v1/${workflowPath(workflow)}/${ticketId}/merges/`,
  );
}

export function unmergeTicket(
  session: WorkspaceSession,
  primaryTicket: Ticket,
  secondaryTicket: Ticket,
  reason: string,
) {
  return request<TicketUnmergeResult>(
    session,
    `/api/v1/${workflowPath(primaryTicket.workflow_type)}/${primaryTicket.id}/unmerge/`,
    {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({
        expected_primary_version: primaryTicket.state_version,
        expected_secondary_version: secondaryTicket.state_version,
        secondary_ticket_id: secondaryTicket.id,
        reason,
      }),
    },
  );
}

export function mergeTicket(
  session: WorkspaceSession,
  primaryTicket: Ticket,
  secondaryTicket: Ticket,
  reason: string,
) {
  return request<TicketUnmergeResult>(
    session,
    `/api/v1/${workflowPath(primaryTicket.workflow_type)}/${primaryTicket.id}/merge/`,
    {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({
        expected_primary_version: primaryTicket.state_version,
        expected_secondary_version: secondaryTicket.state_version,
        secondary_ticket_id: secondaryTicket.id,
        reason,
      }),
    },
  );
}

export function createTicket(
  session: WorkspaceSession,
  input: CreateTicketInput,
) {
  const { workflow, ...payload } = input;
  return request<Ticket>(session, `/api/v1/${workflowPath(workflow)}/`, {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify(payload),
  });
}

export function submitTicket(
  session: WorkspaceSession,
  ticket: Ticket,
) {
  return request<TicketSubmissionResult>(
    session,
    `/api/v1/${workflowPath(ticket.workflow_type)}/${ticket.id}/submit/`,
    {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({ expected_version: ticket.state_version }),
    },
  );
}

export function cancelTicket(
  session: WorkspaceSession,
  ticket: Ticket,
  reason: string,
) {
  return request<TicketCancellationResult>(
    session,
    `/api/v1/${workflowPath(ticket.workflow_type)}/${ticket.id}/cancel/`,
    {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({
        expected_version: ticket.state_version,
        reason,
      }),
    },
  );
}

export function reopenTicket(
  session: WorkspaceSession,
  ticket: Ticket,
  reason: string,
) {
  return request<TicketLifecycleResult>(
    session,
    `/api/v1/${workflowPath(ticket.workflow_type)}/${ticket.id}/reopen/`,
    {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({ expected_version: ticket.state_version, reason }),
    },
  );
}

export function closeTicket(
  session: WorkspaceSession,
  ticket: Ticket,
  reason: string,
) {
  return request<TicketLifecycleResult>(
    session,
    `/api/v1/${workflowPath(ticket.workflow_type)}/${ticket.id}/close/`,
    {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({ expected_version: ticket.state_version, reason }),
    },
  );
}

export function assignInHouseServiceTicket(
  session: WorkspaceSession,
  ticket: Ticket,
  technicianId: string,
) {
  return request<TicketAssignmentResult>(
    session,
    `/api/v1/service-tickets/${ticket.id}/assign-in-house/`,
    {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({
        expected_version: ticket.state_version,
        technician_id: technicianId,
      }),
    },
  );
}

export function assignVendorServiceTicket(
  session: WorkspaceSession,
  ticket: Ticket,
  vendorContractId: string,
) {
  return request<TicketAssignmentResult>(
    session,
    `/api/v1/service-tickets/${ticket.id}/assign-vendor/`,
    {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({
        expected_version: ticket.state_version,
        vendor_contract_id: vendorContractId,
      }),
    },
  );
}

export function reassignServiceTicketFromTriage(
  session: WorkspaceSession,
  ticket: Ticket,
  target: ReassignTriageInput,
) {
  return request<TicketCancellationResult>(
    session,
    `/api/v1/service-tickets/${ticket.id}/reassign-triage/`,
    {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({
        expected_version: ticket.state_version,
        ...target,
      }),
    },
  );
}

export function overrideResumeServiceTicket(
  session: WorkspaceSession,
  ticket: Ticket,
  reason: string,
) {
  return request<SupervisorOverrideResult>(
    session,
    `/api/v1/service-tickets/${ticket.id}/override-resume/`,
    {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({
        expected_version: ticket.state_version,
        reason,
      }),
    },
  );
}

export function supervisorCompleteServiceTicket(
  session: WorkspaceSession,
  ticket: Ticket,
  reason: string,
  proofNotes: string,
) {
  return request<SupervisorOverrideResult>(
    session,
    `/api/v1/service-tickets/${ticket.id}/supervisor-complete/`,
    {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({
        expected_version: ticket.state_version,
        reason,
        proof_notes: proofNotes,
      }),
    },
  );
}

export function fetchTicketEstimates(
  session: WorkspaceSession,
  ticketId: string,
) {
  return request<TicketEstimate[]>(
    session,
    `/api/v1/service-tickets/${ticketId}/estimates/`,
  );
}

export function approveTicketEstimate(
  session: WorkspaceSession,
  ticket: Ticket,
  notes = "",
) {
  return request<{ id: string; ticket_number: string; status: string; state_version: number; estimate_id: string }>(
    session,
    `/api/v1/service-tickets/${ticket.id}/approve-estimate/`,
    {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({
        expected_version: ticket.state_version,
        notes,
      }),
    },
  );
}

export function rejectTicketEstimate(
  session: WorkspaceSession,
  ticket: Ticket,
  reason: string,
) {
  return request<{ id: string; ticket_number: string; status: string; state_version: number; estimate_id: string }>(
    session,
    `/api/v1/service-tickets/${ticket.id}/reject-estimate/`,
    {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({
        expected_version: ticket.state_version,
        reason,
      }),
    },
  );
}

export function verifyServiceTicketCompletion(
  session: WorkspaceSession,
  ticket: Ticket,
  otp: string,
) {
  return request<{ id: string; ticket_number: string; status: string; state_version: number; event_id: string }>(
    session,
    `/api/v1/service-tickets/${ticket.id}/verify-completion/`,
    {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({
        expected_version: ticket.state_version,
        otp,
      }),
    },
  );
}

export function beginGovernanceReview(session: WorkspaceSession, ticket: Ticket) {
  return request<GovernanceTransitionResult>(
    session,
    `/api/v1/governance-tickets/${ticket.id}/begin-review/`,
    {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({ expected_version: ticket.state_version }),
    },
  );
}

export function openGovernanceDiscussion(
  session: WorkspaceSession,
  ticket: Ticket,
  purpose: string,
) {
  return request<GovernanceTransitionResult>(
    session,
    `/api/v1/governance-tickets/${ticket.id}/open-discussion/`,
    {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({ expected_version: ticket.state_version, purpose }),
    },
  );
}

export function recordGovernanceAction(
  session: WorkspaceSession,
  ticket: Ticket,
  summary: string,
) {
  return request<GovernanceTransitionResult>(
    session,
    `/api/v1/governance-tickets/${ticket.id}/record-action/`,
    {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({ expected_version: ticket.state_version, summary }),
    },
  );
}

export function listTicketComments(
  session: WorkspaceSession,
  workflow: TicketWorkflow,
  ticketId: string,
) {
  return request<TicketComment[]>(
    session,
    `/api/v1/tickets/${workflow.toLowerCase()}/${ticketId}/comments/`,
  );
}

export function createTicketComment(
  session: WorkspaceSession,
  ticket: Ticket,
  body: string,
) {
  return request<TicketComment>(
    session,
    `/api/v1/tickets/${ticket.workflow_type.toLowerCase()}/${ticket.id}/comments/`,
    {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({
        body,
        expected_version: ticket.state_version,
      }),
    },
  );
}

export function listInternalTicketComments(
  session: WorkspaceSession,
  workflow: TicketWorkflow,
  ticketId: string,
) {
  return request<TicketComment[]>(
    session,
    `/api/v1/tickets/${workflow.toLowerCase()}/${ticketId}/internal-comments/`,
  );
}

export function createInternalTicketComment(
  session: WorkspaceSession,
  ticket: Ticket,
  body: string,
) {
  return request<TicketComment>(
    session,
    `/api/v1/tickets/${ticket.workflow_type.toLowerCase()}/${ticket.id}/internal-comments/`,
    {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({
        body,
        expected_version: ticket.state_version,
      }),
    },
  );
}

export function listTicketAttachments(
  session: WorkspaceSession,
  workflow: TicketWorkflow,
  ticketId: string,
) {
  return request<TicketAttachment[]>(
    session,
    `/api/v1/tickets/${workflow.toLowerCase()}/${ticketId}/attachments/`,
  );
}

export function issueAttachmentUploadSlot(
  session: WorkspaceSession,
  workflow: TicketWorkflow,
  ticketId: string,
  input: IssueAttachmentUploadSlotInput,
) {
  return request<IssuedAttachmentUploadSlot>(
    session,
    `/api/v1/tickets/${workflow.toLowerCase()}/${ticketId}/attachments/upload-slot/`,
    {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify(input),
    },
  );
}

export function completeAttachmentUpload(
  session: WorkspaceSession,
  attachmentId: string,
  workflow?: TicketWorkflow,
  ticketId?: string,
) {
  const path =
    workflow && ticketId
      ? `/api/v1/tickets/${workflow.toLowerCase()}/${ticketId}/attachments/${attachmentId}/complete/`
      : `/api/v1/attachments/${attachmentId}/complete/`;
  return request<TicketAttachment>(session, path, {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
  });
}

export async function uploadAttachmentFile(
  slot: IssuedAttachmentUploadSlot,
  file: File,
): Promise<void> {
  // If in test mode with blob.local or mock storage URL, skip external HTTP request to avoid DNS/network failures
  if (
    slot.upload_url.includes("blob.local") ||
    slot.upload_url.includes("test-quarantine")
  ) {
    return;
  }
  const rawHeaders = slot.upload_headers || slot.required_headers || {};
  const headers = new Headers(rawHeaders);
  if (!headers.has("Content-Type") && file.type) {
    headers.set("Content-Type", file.type);
  }
  const response = await fetch(slot.upload_url, {
    method: slot.upload_method || "PUT",
    headers,
    body: file,
  });
  if (!response.ok) {
    throw new Error(
      `Failed to upload file to storage: ${response.statusText} (${response.status})`,
    );
  }
}

export type LoginResponse = {
  access: string;
  refresh: string;
};

export async function loginWithEmailPassword(
  apiBaseUrl: string,
  email: string,
  password: string,
): Promise<LoginResponse> {
  const base = normalizeApiBaseUrl(apiBaseUrl);
  const response = await fetch(`${base}/api/v1/auth/login/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: email.trim(), password }),
  });
  if (!response.ok) {
    let errorDetail = "Invalid email or password.";
    try {
      const data = await response.json();
      if (data?.detail) errorDetail = data.detail;
      else if (typeof data === "object") {
        const messages = Object.values(data).flat().join(" ");
        if (messages) errorDetail = messages;
      }
    } catch {}
    throw new Error(errorDetail);
  }
  return response.json();
}

export async function activateInvitation(
  apiBaseUrl: string,
  input: {
    society_id: string;
    invitation_id: string;
    token: string;
    password: string;
  },
): Promise<void> {
  const base = normalizeApiBaseUrl(apiBaseUrl);
  const response = await fetch(`${base}/api/v1/auth/activate/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) {
    let errorDetail = "This invitation is invalid or expired.";
    try {
      const data = await response.json();
      if (data?.detail) errorDetail = data.detail;
      else if (data?.token) errorDetail = Array.isArray(data.token) ? data.token.join(" ") : String(data.token);
      else if (data?.password) errorDetail = Array.isArray(data.password) ? data.password.join(" ") : String(data.password);
    } catch {}
    throw new Error(errorDetail);
  }
}

export async function requestPasswordReset(
  apiBaseUrl: string,
  email: string,
): Promise<{ detail: string }> {
  const base = normalizeApiBaseUrl(apiBaseUrl);
  const response = await fetch(`${base}/api/v1/auth/password-reset/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: email.trim() }),
  });
  if (!response.ok) {
    throw new Error("Unable to request password reset. Please try again.");
  }
  return response.json();
}

export async function confirmPasswordReset(
  apiBaseUrl: string,
  input: { token: string; password: string },
): Promise<void> {
  const base = normalizeApiBaseUrl(apiBaseUrl);
  const response = await fetch(`${base}/api/v1/auth/password-reset/confirm/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) {
    let errorDetail = "This password-reset link is invalid or expired.";
    try {
      const data = await response.json();
      if (data?.detail) errorDetail = data.detail;
      else if (data?.token) errorDetail = Array.isArray(data.token) ? data.token.join(" ") : String(data.token);
      else if (data?.password) errorDetail = Array.isArray(data.password) ? data.password.join(" ") : String(data.password);
    } catch {}
    throw new Error(errorDetail);
  }
}

export async function refreshAuthSession(
  apiBaseUrl: string,
  refresh: string,
): Promise<LoginResponse> {
  const base = normalizeApiBaseUrl(apiBaseUrl);
  const response = await fetch(`${base}/api/v1/auth/refresh/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh }),
  });
  if (!response.ok) {
    throw new Error("Session expired. Please sign in again.");
  }
  return response.json();
}

export async function logoutAuthSession(
  apiBaseUrl: string,
  refresh: string,
): Promise<void> {
  const base = normalizeApiBaseUrl(apiBaseUrl);
  await fetch(`${base}/api/v1/auth/logout/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh }),
  });
}