"use client";

import {
  AlertTriangle,
  ArrowLeft,
  Archive,
  CheckCircle2,
  ClipboardCheck,
  FileImage,
  FileText,
  GitMerge,
  LoaderCircle,
  LockKeyhole,
  MapPin,
  MessageSquare,
  Paperclip,
  ReceiptText,
  RefreshCw,
  RotateCcw,
  Send,
  ShieldAlert,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

import {
  approveTicketEstimate,
  assignInHouseServiceTicket,
  assignVendorServiceTicket,
  closeTicket,
  createInternalTicketComment,
  createTicketComment,
  fetchTicketEstimates,
  getTicket,
  getTicketOptions,
  isFacilityManagerSession,
  completeAttachmentUpload,
  issueAttachmentUploadSlot,
  listInternalTicketComments,
  listTechnicians,
  listTicketAttachments,
  listTicketMergeHistory,
  listTicketComments,
  listTickets,
  listVendorContracts,
  listVendors,
  mergeTicket,
  NivasOpsApiError,
  overrideResumeServiceTicket,
  reassignServiceTicketFromTriage,
  rejectTicketEstimate,
  reopenTicket,
  supervisorCompleteServiceTicket,
  uploadAttachmentFile,
  validateAttachmentFile,
  TechnicianProfile,
  Ticket,
  TicketAttachment,
  TicketComment,
  TicketEstimate,
  TicketMergeRecord,
  TicketOptions,
  unmergeTicket,
  Vendor,
  VendorContract,
} from "@/lib/nivasops-api";
import { useWorkspaceSession } from "../../../session-context";

type SupervisorCommand = "RESUME" | "COMPLETE" | null;
type LifecycleCommand = "REOPEN" | "CLOSE" | null;
const FACILITY_MANAGER_UNMERGE_WINDOW_MS = 24 * 60 * 60 * 1000;

function isCurrentVendorContract(contract: VendorContract, vendor: Vendor | undefined, today: string) {
  return Boolean(vendor?.is_active)
    && contract.is_active
    && contract.starts_on <= today
    && contract.ends_on >= today
    && (contract.max_active_tickets === null || contract.current_active_tickets_count < contract.max_active_tickets);
}

function isCurrentTechnician(tech: TechnicianProfile, today: string) {
  const startsAt = tech.starts_at ? tech.starts_at.slice(0, 10) : "";
  const endsAt = tech.ends_at ? tech.ends_at.slice(0, 10) : "";
  return tech.is_active
    && (startsAt === "" || startsAt <= today)
    && (endsAt === "" || endsAt >= today)
    && (tech.max_active_tickets === null || tech.current_active_tickets_count < tech.max_active_tickets);
}

function formatDate(value?: string | null) {
  if (!value) return "Not available";
  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function commentAuthor(comment: TicketComment) {
  if (comment.is_authored_by_requester) return "You";
  return comment.author_persona === "resident" ? "Resident" : "Society operations";
}

function ticketFacts(ticket: Ticket, options: TicketOptions | null) {
  const category = options?.categories.find((item) => item.id === ticket.category);
  const subcategory = category?.subcategories.find((item) => item.id === ticket.subcategory);
  const unit = options?.units.find((item) => item.id === ticket.unit);
  const commonArea = options?.common_areas.find((item) => item.id === ticket.common_area);
  return {
    category: category?.name ?? "Category unavailable",
    subcategory: subcategory?.name ?? "Classification unavailable",
    location: unit ? `${unit.block} · ${unit.door_number}` : commonArea?.name ?? "Society-wide",
  };
}

export default function ServiceTicketWorkspacePage() {
  const params = useParams<{ id: string }>();
  const { session } = useWorkspaceSession();
  const [ticket, setTicket] = useState<Ticket | null>(null);
  const [options, setOptions] = useState<TicketOptions | null>(null);
  const [publicComments, setPublicComments] = useState<TicketComment[]>([]);
  const [internalComments, setInternalComments] = useState<TicketComment[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [publicLoading, setPublicLoading] = useState(true);
  const [internalLoading, setInternalLoading] = useState(true);
  const [error, setError] = useState("");
  const [publicError, setPublicError] = useState("");
  const [internalError, setInternalError] = useState("");
  const [publicBody, setPublicBody] = useState("");
  const [internalBody, setInternalBody] = useState("");
  const [postingPublic, setPostingPublic] = useState(false);
  const [postingInternal, setPostingInternal] = useState(false);
  const [supervisorCommand, setSupervisorCommand] = useState<SupervisorCommand>(null);
  const [supervisorReason, setSupervisorReason] = useState("");
  const [proofNotes, setProofNotes] = useState("");
  const [supervisorError, setSupervisorError] = useState("");
  const [submittingSupervisorCommand, setSubmittingSupervisorCommand] = useState(false);
  const [lifecycleCommand, setLifecycleCommand] = useState<LifecycleCommand>(null);
  const [lifecycleReason, setLifecycleReason] = useState("");
  const [lifecycleError, setLifecycleError] = useState("");
  const [submittingLifecycleCommand, setSubmittingLifecycleCommand] = useState(false);
  const [mergeRecords, setMergeRecords] = useState<TicketMergeRecord[]>([]);
  const [mergeRecoveryWindowOpen, setMergeRecoveryWindowOpen] = useState(false);
  const [unmergeDialogOpen, setUnmergeDialogOpen] = useState(false);
  const [unmergeSecondaryTicket, setUnmergeSecondaryTicket] = useState<Ticket | null>(null);
  const [unmergeSecondaryLoading, setUnmergeSecondaryLoading] = useState(false);
  const [unmergeReason, setUnmergeReason] = useState("");
  const [unmergeError, setUnmergeError] = useState("");
  const [submittingUnmerge, setSubmittingUnmerge] = useState(false);

  // Dispatch Dialog State
  const [dispatchDialogOpen, setDispatchDialogOpen] = useState(false);
  const [dispatchType, setDispatchType] = useState<"IN_HOUSE" | "VENDOR">("IN_HOUSE");
  const [dispatchTargetId, setDispatchTargetId] = useState("");
  const [technicians, setTechnicians] = useState<TechnicianProfile[]>([]);
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [vendorContracts, setVendorContracts] = useState<VendorContract[]>([]);
  const [dispatchTargetsLoading, setDispatchTargetsLoading] = useState(false);
  const [dispatchTargetsError, setDispatchTargetsError] = useState("");
  const [dispatchError, setDispatchError] = useState("");
  const [submittingDispatch, setSubmittingDispatch] = useState(false);

  // Merge Dialog State
  const [mergeDialogOpen, setMergeDialogOpen] = useState(false);
  const [mergeCandidates, setMergeCandidates] = useState<Ticket[]>([]);
  const [mergeCandidatesLoading, setMergeCandidatesLoading] = useState(false);
  const [mergeCandidatesError, setMergeCandidatesError] = useState("");
  const [mergeSecondaryId, setMergeSecondaryId] = useState("");
  const [mergeReason, setMergeReason] = useState("");
  const [mergeError, setMergeError] = useState("");
  const [submittingMerge, setSubmittingMerge] = useState(false);

  // Material Estimate State
  const [estimates, setEstimates] = useState<TicketEstimate[]>([]);
  const [estimateActionLoading, setEstimateActionLoading] = useState(false);
  const [estimateActionError, setEstimateActionError] = useState("");
  const [estimateRejectOpen, setEstimateRejectOpen] = useState(false);
  const [estimateRejectReason, setEstimateRejectReason] = useState("");

  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    if (!session) return;
    let current = true;
    void Promise.all([
      getTicket(session, "SERVICE", params.id),
      getTicketOptions(session),
    ]).then(([ticketResult, optionsResult]) => {
      if (!current) return;
      setTicket(ticketResult);
      setOptions(optionsResult);
      setError("");
    }).catch((reason: unknown) => {
      if (current) setError(reason instanceof Error ? reason.message : "Service request details could not be loaded.");
    }).finally(() => {
      if (current) setLoading(false);
    });
    return () => { current = false; };
  }, [params.id, refreshKey, session]);

  useEffect(() => {
    if (!session) return;
    let current = true;
    void listTicketMergeHistory(session, "SERVICE", params.id).then((records) => {
      if (!current) return;
      setMergeRecords(records);
      setMergeRecoveryWindowOpen(records.some((record) => (
        record.is_active
        && record.primary_ticket_id === params.id
        && Date.now() - new Date(record.merged_at).getTime() < FACILITY_MANAGER_UNMERGE_WINDOW_MS
      )));
    }).catch(() => {
      if (!current) return;
      setMergeRecords([]);
      setMergeRecoveryWindowOpen(false);
    });
    return () => { current = false; };
  }, [params.id, refreshKey, session]);

  useEffect(() => {
    if (!session || !ticket || ticket.status === "DRAFT") return;
    let current = true;
    void Promise.allSettled([
      listTicketComments(session, "SERVICE", ticket.id),
      listInternalTicketComments(session, "SERVICE", ticket.id),
    ]).then(([publicResult, internalResult]) => {
      if (!current) return;
      if (publicResult.status === "fulfilled") {
        setPublicComments(publicResult.value);
        setPublicError("");
      } else {
        setPublicError(publicResult.reason instanceof Error ? publicResult.reason.message : "Resident conversation could not be loaded.");
      }
      if (internalResult.status === "fulfilled") {
        setInternalComments(internalResult.value);
        setInternalError("");
      } else {
        setInternalError(internalResult.reason instanceof Error ? internalResult.reason.message : "Private notes could not be loaded.");
      }
    }).finally(() => {
      if (current) {
        setPublicLoading(false);
        setInternalLoading(false);
      }
    });
    return () => { current = false; };
  }, [session, ticket]);

  useEffect(() => {
    if (!session || !ticket || ticket.status === "DRAFT") return;
    let current = true;
    void fetchTicketEstimates(session, ticket.id)
      .then((data) => {
        if (!current) return;
        setEstimates(data);
      })
      .catch(() => {
        if (!current) return;
        setEstimates([]);
      });
    return () => {
      current = false;
    };
  }, [session, ticket, refreshKey]);

  const [attachments, setAttachments] = useState<TicketAttachment[]>([]);
  const [attachmentsLoading, setAttachmentsLoading] = useState(false);
  const [uploadingAttachment, setUploadingAttachment] = useState(false);
  const [attachmentError, setAttachmentError] = useState("");

  useEffect(() => {
    if (!session || !ticket) return;
    let current = true;
    void listTicketAttachments(session, "SERVICE", ticket.id)
      .then((data) => {
        if (!current) return;
        setAttachments(data);
        setAttachmentError("");
      })
      .catch((err: unknown) => {
        if (!current) return;
        setAttachmentError(
          err instanceof Error ? err.message : "Attachments could not be loaded.",
        );
      })
      .finally(() => {
        if (current) setAttachmentsLoading(false);
      });
    return () => {
      current = false;
    };
  }, [session, ticket, refreshKey]);

  async function handleUploadAttachment(file: File) {
    if (!session || !ticket) return;
    const validationErr = validateAttachmentFile(file);
    if (validationErr) {
      setAttachmentError(validationErr);
      return;
    }
    setUploadingAttachment(true);
    setAttachmentError("");
    try {
      const slot = await issueAttachmentUploadSlot(session, "SERVICE", ticket.id, {
        expected_version: ticket.state_version,
        filename: file.name,
        content_type: file.type || "image/jpeg",
        byte_size: file.size,
      });
      await uploadAttachmentFile(slot, file);
      await completeAttachmentUpload(session, slot.attachment.id, "SERVICE", ticket.id).catch(() => {});
      setRefreshKey((value) => value + 1);
    } catch (err) {
      setAttachmentError(
        err instanceof Error ? err.message : "Failed to upload inspection attachment.",
      );
    } finally {
      setUploadingAttachment(false);
    }
  }

  async function refreshWorkspace() {
    setRefreshing(true);
    setRefreshKey((value) => value + 1);
    setRefreshing(false);
  }

  async function postPublicComment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const body = publicBody.trim();
    if (!session || !ticket || ticket.status === "DRAFT" || !body) return;
    setPostingPublic(true);
    try {
      const comment = await createTicketComment(session, ticket, body);
      setPublicComments((current) => [...current, comment]);
      setPublicBody("");
      setPublicError("");
    } catch (reason: unknown) {
      setPublicError(reason instanceof Error ? reason.message : "Resident reply could not be posted.");
    } finally {
      setPostingPublic(false);
    }
  }

  async function postInternalComment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const body = internalBody.trim();
    if (!session || !ticket || ticket.status === "DRAFT" || !body) return;
    setPostingInternal(true);
    try {
      const comment = await createInternalTicketComment(session, ticket, body);
      setInternalComments((current) => [...current, comment]);
      setInternalBody("");
      setInternalError("");
    } catch (reason: unknown) {
      setInternalError(reason instanceof Error ? reason.message : "Private note could not be posted.");
    } finally {
      setPostingInternal(false);
    }
  }

  function closeSupervisorCommand(afterSuccess = false) {
    if (submittingSupervisorCommand && !afterSuccess) return;
    setSupervisorCommand(null);
    setSupervisorReason("");
    setProofNotes("");
    setSupervisorError("");
  }

  async function submitSupervisorCommand(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const reason = supervisorReason.trim();
    const proof = proofNotes.trim();
    if (!session || !ticket || !supervisorCommand || !reason || (supervisorCommand === "COMPLETE" && !proof)) return;

    setSubmittingSupervisorCommand(true);
    setSupervisorError("");
    try {
      const result = supervisorCommand === "RESUME"
        ? await overrideResumeServiceTicket(session, ticket, reason)
        : await supervisorCompleteServiceTicket(session, ticket, reason, proof);
      setTicket((current) => current && current.id === result.id
        ? { ...current, status: result.status, state_version: result.state_version }
        : current);
      closeSupervisorCommand(true);
      setRefreshKey((value) => value + 1);
    } catch (reason: unknown) {
      setSupervisorError(reason instanceof NivasOpsApiError && reason.status === 403
        ? "The server rejected this action because the connected session lacks fresh step-up authentication."
        : reason instanceof NivasOpsApiError && reason.status === 409
          ? "This ticket changed elsewhere. Refresh and review its current state."
          : reason instanceof Error ? reason.message : "The supervisor action could not be completed.");
    } finally {
      setSubmittingSupervisorCommand(false);
    }
  }

  function closeLifecycleCommand(afterSuccess = false) {
    if (submittingLifecycleCommand && !afterSuccess) return;
    setLifecycleCommand(null);
    setLifecycleReason("");
    setLifecycleError("");
  }

  async function submitLifecycleCommand(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const reason = lifecycleReason.trim();
    if (!session || !ticket || !lifecycleCommand || (lifecycleCommand === "REOPEN" && !reason)) return;

    setSubmittingLifecycleCommand(true);
    setLifecycleError("");
    try {
      const result = lifecycleCommand === "REOPEN"
        ? await reopenTicket(session, ticket, reason)
        : await closeTicket(session, ticket, reason);
      setTicket((current) => current && current.id === result.id
        ? { ...current, status: result.status, state_version: result.state_version }
        : current);
      closeLifecycleCommand(true);
      setRefreshKey((value) => value + 1);
    } catch (reason: unknown) {
      setLifecycleError(reason instanceof NivasOpsApiError && reason.status === 409
        ? "This ticket changed elsewhere. Refresh and review its current state."
        : reason instanceof Error ? reason.message : "The lifecycle change could not be recorded.");
    } finally {
      setSubmittingLifecycleCommand(false);
    }
  }

  function closeUnmergeDialog(afterSuccess = false) {
    if (submittingUnmerge && !afterSuccess) return;
    setUnmergeDialogOpen(false);
    setUnmergeSecondaryTicket(null);
    setUnmergeReason("");
    setUnmergeError("");
  }

  async function openUnmergeDialog(record: TicketMergeRecord) {
    if (!session) return;
    setUnmergeDialogOpen(true);
    setUnmergeSecondaryTicket(null);
    setUnmergeReason("");
    setUnmergeError("");
    setUnmergeSecondaryLoading(true);
    try {
      setUnmergeSecondaryTicket(await getTicket(session, "SERVICE", record.secondary_ticket_id));
    } catch (reason: unknown) {
      setUnmergeError(reason instanceof Error ? reason.message : "The merged request could not be loaded for recovery.");
    } finally {
      setUnmergeSecondaryLoading(false);
    }
  }

  async function submitUnmerge(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const reason = unmergeReason.trim();
    if (!session || !ticket || !unmergeSecondaryTicket || !reason) return;
    setSubmittingUnmerge(true);
    setUnmergeError("");
    try {
      const result = await unmergeTicket(session, ticket, unmergeSecondaryTicket, reason);
      setTicket((current) => current && current.id === result.primary_ticket.id
        ? { ...current, status: result.primary_ticket.status, state_version: result.primary_ticket.state_version }
        : current);
      closeUnmergeDialog(true);
      setRefreshKey((value) => value + 1);
    } catch (reason: unknown) {
      setUnmergeError(reason instanceof NivasOpsApiError && reason.status === 403
        ? "The server rejected recovery because step-up authentication is no longer fresh or the 24-hour recovery window has expired."
        : reason instanceof NivasOpsApiError && reason.status === 409
          ? "One of the linked requests changed elsewhere. Refresh and review the current record."
          : reason instanceof Error ? reason.message : "The merge recovery could not be completed.");
    } finally {
      setSubmittingUnmerge(false);
    }
  }

  async function openDispatchDialog() {
    if (!session) return;
    setDispatchDialogOpen(true);
    setDispatchTargetId("");
    setDispatchTargetsError("");
    setDispatchError("");
    setDispatchTargetsLoading(true);
    try {
      const [techResults, vendorResults, contractResults] = await Promise.all([
        listTechnicians(session),
        listVendors(session),
        listVendorContracts(session),
      ]);
      setTechnicians(techResults);
      setVendors(vendorResults);
      setVendorContracts(contractResults);
      if (techResults.length === 0 && contractResults.length > 0) {
        setDispatchType("VENDOR");
      }
    } catch (reason: unknown) {
      setDispatchTargetsError(reason instanceof Error ? reason.message : "Dispatch candidates could not be loaded.");
    } finally {
      setDispatchTargetsLoading(false);
    }
  }

  function closeDispatchDialog(afterSuccess = false) {
    if (submittingDispatch && !afterSuccess) return;
    setDispatchDialogOpen(false);
    setDispatchTargetId("");
    setDispatchError("");
  }

  async function submitDispatch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !ticket || !dispatchTargetId) return;
    setSubmittingDispatch(true);
    setDispatchError("");
    try {
      let result;
      if (ticket.status === "SUPERVISOR_TRIAGE") {
        result = dispatchType === "IN_HOUSE"
          ? await reassignServiceTicketFromTriage(session, ticket, { target_type: "IN_HOUSE", technician_id: dispatchTargetId })
          : await reassignServiceTicketFromTriage(session, ticket, { target_type: "VENDOR", vendor_contract_id: dispatchTargetId });
      } else {
        result = dispatchType === "IN_HOUSE"
          ? await assignInHouseServiceTicket(session, ticket, dispatchTargetId)
          : await assignVendorServiceTicket(session, ticket, dispatchTargetId);
      }
      setTicket((current) => current && current.id === result.id
        ? { ...current, status: result.status, state_version: result.state_version }
        : current);
      closeDispatchDialog(true);
      setRefreshKey((value) => value + 1);
    } catch (reason: unknown) {
      setDispatchError(reason instanceof NivasOpsApiError && reason.status === 409
        ? "This ticket or candidate changed elsewhere. Refresh and choose an available target."
        : reason instanceof Error ? reason.message : "The assignment could not be saved.");
    } finally {
      setSubmittingDispatch(false);
    }
  }

  async function openMergeDialog() {
    if (!session) return;
    setMergeDialogOpen(true);
    setMergeSecondaryId("");
    setMergeReason("");
    setMergeError("");
    setMergeCandidatesError("");
    setMergeCandidatesLoading(true);
    try {
      const allTickets = await listTickets(session);
      const candidates = allTickets.filter((item) => (
        item.workflow_type === "SERVICE"
        && item.id !== params.id
        && item.status !== "DRAFT"
        && item.status !== "RESOLVED"
        && item.status !== "CLOSED"
        && item.status !== "CANCELLED"
        && item.status !== "MERGED"
      ));
      setMergeCandidates(candidates);
    } catch (reason: unknown) {
      setMergeCandidatesError(reason instanceof Error ? reason.message : "Active candidate requests could not be loaded.");
    } finally {
      setMergeCandidatesLoading(false);
    }
  }

  function closeMergeDialog(afterSuccess = false) {
    if (submittingMerge && !afterSuccess) return;
    setMergeDialogOpen(false);
    setMergeSecondaryId("");
    setMergeReason("");
    setMergeError("");
  }

  async function submitMerge(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const reason = mergeReason.trim();
    const secondaryTicket = mergeCandidates.find((item) => item.id === mergeSecondaryId);
    if (!session || !ticket || !secondaryTicket || !reason) return;

    setSubmittingMerge(true);
    setMergeError("");
    try {
      const result = await mergeTicket(session, ticket, secondaryTicket, reason);
      setTicket((current) => current && current.id === result.primary_ticket.id
        ? { ...current, status: result.primary_ticket.status, state_version: result.primary_ticket.state_version }
        : current);
      closeMergeDialog(true);
      setRefreshKey((value) => value + 1);
    } catch (reason: unknown) {
      setMergeError(reason instanceof NivasOpsApiError && reason.status === 409
        ? "One of the tickets changed state or was already merged. Refresh and try again."
        : reason instanceof Error ? reason.message : "The duplicate merge could not be recorded.");
    } finally {
      setSubmittingMerge(false);
    }
  }

  async function handleApproveEstimate() {
    if (!session || !ticket) return;
    setEstimateActionLoading(true);
    setEstimateActionError("");
    try {
      await approveTicketEstimate(session, ticket);
      setRefreshKey((k) => k + 1);
    } catch (err: unknown) {
      setEstimateActionError(
        err instanceof Error ? err.message : "Failed to approve estimate.",
      );
    } finally {
      setEstimateActionLoading(false);
    }
  }

  async function handleRejectEstimate() {
    if (!session || !ticket || !estimateRejectReason.trim()) return;
    setEstimateActionLoading(true);
    setEstimateActionError("");
    try {
      await rejectTicketEstimate(session, ticket, estimateRejectReason.trim());
      setEstimateRejectOpen(false);
      setEstimateRejectReason("");
      setRefreshKey((k) => k + 1);
    } catch (err: unknown) {
      setEstimateActionError(
        err instanceof Error ? err.message : "Failed to reject estimate.",
      );
    } finally {
      setEstimateActionLoading(false);
    }
  }

  if (loading) {
    return <div className="detail-loading"><LoaderCircle className="spin" size={24} /><span>Loading service request</span></div>;
  }

  if (error || !ticket) {
    return <div className="empty-state error-state"><AlertTriangle size={26} /><h3>Service request unavailable</h3><p>{error || "No ticket data was returned."}</p><Link href="/app/operations/service">Return to service inbox</Link></div>;
  }

  const facts = ticketFacts(ticket, options);
  const canCommunicate = ticket.status !== "DRAFT";
  const canResumeFromTriage = session && isFacilityManagerSession(session) && ticket.status === "SUPERVISOR_TRIAGE";
  const canCompleteBySupervisor = session && isFacilityManagerSession(session) && ticket.status === "PENDING_RESIDENT_CONFIRMATION";
  const canUseSupervisorControls = canResumeFromTriage || canCompleteBySupervisor;
  const canDispatch = session && isFacilityManagerSession(session) && (ticket.status === "SUBMITTED" || ticket.status === "SUPERVISOR_TRIAGE");
  const canReopen = session && isFacilityManagerSession(session) && (ticket.status === "RESOLVED" || ticket.status === "CLOSED");
  const canClose = session && isFacilityManagerSession(session) && ticket.status === "RESOLVED";
  const canUseLifecycleControls = canReopen || canClose;
  const canInitiateMerge = session && isFacilityManagerSession(session) && ticket.status !== "DRAFT" && ticket.status !== "RESOLVED" && ticket.status !== "CLOSED" && ticket.status !== "CANCELLED" && ticket.status !== "MERGED";
  const activePrimaryMerge = mergeRecords.find((record) => record.is_active && record.primary_ticket_id === ticket.id);
  const canUnmerge = Boolean(
    session
    && isFacilityManagerSession(session)
    && activePrimaryMerge
    && mergeRecoveryWindowOpen,
  );
  const hasMergeRecoveryContext = Boolean(activePrimaryMerge);
  const currentDate = new Date().toISOString().slice(0, 10);
  const availableTechnicians = technicians.filter((tech) => isCurrentTechnician(tech, currentDate));
  const availableVendorContracts = vendorContracts.filter((contract) => isCurrentVendorContract(contract, vendors.find((vendor) => vendor.id === contract.vendor), currentDate));
  const selectedSecondaryCandidate = mergeCandidates.find((item) => item.id === mergeSecondaryId);

  return (
    <div className="operations-page service-workspace page-enter">
      <section className="operations-header">
        <div className="service-workspace-title">
          <Link className="icon-command" href="/app/operations/service" aria-label="Back to service inbox" title="Back to service inbox"><ArrowLeft size={18} /></Link>
          <div><p className="workspace-kicker">Service request · {ticket.ticket_number}</p><h1>{ticket.title}</h1><p>Canonical request details and current communication context.</p></div>
        </div>
        <button className="icon-command" type="button" title="Refresh service request" aria-label="Refresh service request" disabled={refreshing} onClick={() => void refreshWorkspace()}><RefreshCw className={refreshing ? "spin" : ""} size={17} /></button>
      </section>

      <section className="service-workspace-grid">
        <div className="service-workspace-main">
          <section className="service-dossier">
            <div className="service-dossier-heading"><span className={`priority-marker priority-${ticket.priority.toLowerCase()}`}>{ticket.priority}</span><span className={`status-pill status-${ticket.status.toLowerCase()}`}>{ticket.status.replaceAll("_", " ")}</span></div>
            <p className="workspace-kicker">Resident report</p>
            <p>{ticket.description}</p>
            <dl>
              <div><dt>Category</dt><dd>{facts.category}</dd></div>
              <div><dt>Classification</dt><dd>{facts.subcategory}</dd></div>
              <div><dt>Location</dt><dd><MapPin size={14} /> {facts.location}</dd></div>
              <div><dt>Submitted</dt><dd>{formatDate(ticket.submitted_at)}</dd></div>
            </dl>

            <div className="dossier-attachments-section">
              <div className="attachments-header">
                <div className="attachments-title">
                  <FileImage size={18} />
                  <h3>Inspection & Media Evidence ({attachments.length})</h3>
                </div>
                {!["CANCELLED", "CLOSED", "MERGED"].includes(ticket.status) && (
                  <label className="attach-file-action-btn">
                    {uploadingAttachment ? (
                      <LoaderCircle className="spin" size={14} />
                    ) : (
                      <Paperclip size={14} />
                    )}
                    <span>{uploadingAttachment ? "Uploading..." : "Add evidence"}</span>
                    <input
                      type="file"
                      disabled={uploadingAttachment}
                      accept="image/jpeg,image/png,image/webp,application/pdf"
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        if (file) handleUploadAttachment(file);
                        e.target.value = "";
                      }}
                      style={{ display: "none" }}
                    />
                  </label>
                )}
              </div>

              {attachmentError && (
                <p className="form-error attachment-form-error">{attachmentError}</p>
              )}

              {attachmentsLoading ? (
                <div className="attachments-loading">
                  <LoaderCircle className="spin" size={16} />
                  <span>Loading attachments...</span>
                </div>
              ) : attachments.length === 0 ? (
                <div className="attachments-empty">
                  <FileImage size={18} />
                  <span>No media or inspection files attached yet.</span>
                </div>
              ) : (
                <div className="attachments-grid">
                  {attachments.map((att) => (
                    <div key={att.id} className="attachment-card">
                      <div className="attachment-card-icon">
                        {att.declared_content_type === "application/pdf" ? (
                          <FileText size={20} className="file-icon-pdf" />
                        ) : (
                          <FileImage size={20} className="file-icon-img" />
                        )}
                      </div>
                      <div className="attachment-card-info">
                        <span className="attachment-filename" title={att.original_filename}>
                          {att.original_filename}
                        </span>
                        <div className="attachment-meta">
                          <span>{att.byte_size_formatted}</span>
                          <span>·</span>
                          <span className="attachment-uploader">
                            {att.uploaded_by_name || att.uploader_persona}
                          </span>
                        </div>
                      </div>
                      <span className={`attachment-status-badge status-${att.status.toLowerCase()}`}>
                        {att.status.replace("_", " ")}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </section>

          {canDispatch && <section className="service-dispatch-panel" aria-label="Dispatch service ticket">
            <div className="service-dispatch-heading"><div><p className="workspace-kicker">Dispatch</p><h2>{ticket.status === "SUPERVISOR_TRIAGE" ? "Reassign service resource" : "Assign service provider"}</h2></div><ClipboardCheck size={19} /></div>
            <p>{ticket.status === "SUPERVISOR_TRIAGE" ? "Choose an in-house technician or active vendor contract to restart accountable handling." : "Choose an available in-house technician or active vendor contract."}</p>
            <button className="primary-command" type="button" onClick={() => void openDispatchDialog()}><ClipboardCheck size={16} /> Select technician or vendor</button>
          </section>}
          {ticket.status === "PENDING_ESTIMATE_APPROVAL" && (() => {
            const pendingEstimate = estimates.find((e) => e.status === "SUBMITTED") || estimates[0];
            if (!pendingEstimate) {
              return (
                <section className="service-dispatch-panel" aria-label="Review material estimate">
                  <div className="service-dispatch-heading"><div><p className="workspace-kicker">Material estimate</p><h2>Estimate submitted</h2></div><ReceiptText size={19} /></div>
                  <p>Loading authoritative line-item breakdown and cost details...</p>
                </section>
              );
            }
            return (
              <section className="estimate-card" aria-label="Review material estimate">
                <div className="estimate-card-header">
                  <div className="estimate-card-title-group">
                    <ReceiptText size={22} />
                    <div>
                      <h3>
                        Material Cost Estimate
                        <span className="estimate-version-tag">v{pendingEstimate.version}</span>
                        <span className={`estimate-pill estimate-pill-${pendingEstimate.status.toLowerCase()}`}>
                          {pendingEstimate.status}
                        </span>
                        <span className={`estimate-pill ${pendingEstimate.cost_responsibility === "RESIDENT_UNIT" ? "estimate-pill-resident" : "estimate-pill-society"}`}>
                          {pendingEstimate.cost_responsibility === "RESIDENT_UNIT" ? "Resident Unit Payable" : "Society Cost Center"}
                        </span>
                      </h3>
                      <div className="estimate-meta-row">
                        <span>Submitted by: <strong>{pendingEstimate.created_by_name || "Assigned Worker"}</strong></span>
                        <span>•</span>
                        <span>{formatDate(pendingEstimate.created_at)}</span>
                      </div>
                    </div>
                  </div>
                  <div className="estimate-total-hero">
                    <div className="total-label">Estimated Total</div>
                    <div className="total-amount">₹{pendingEstimate.total_amount}</div>
                  </div>
                </div>

                {pendingEstimate.notes && (
                  <div className="estimate-notes-box">
                    <strong>Submitter notes:</strong> {pendingEstimate.notes}
                  </div>
                )}

                <div className="estimate-table-wrapper">
                  <table className="estimate-table">
                    <thead>
                      <tr>
                        <th>Item Description</th>
                        <th className="num-col">Qty</th>
                        <th className="num-col">Unit Price</th>
                        <th className="num-col">Line Total</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pendingEstimate.items.map((item) => (
                        <tr key={item.id}>
                          <td>{item.description}</td>
                          <td className="num-col">{item.quantity}</td>
                          <td className="num-col">₹{item.unit_cost}</td>
                          <td className="num-col">₹{item.total_cost}</td>
                        </tr>
                      ))}
                      <tr className="total-row">
                        <td colSpan={3} style={{ textAlign: "right" }}>Subtotal:</td>
                        <td className="num-col">₹{pendingEstimate.subtotal_amount}</td>
                      </tr>
                      {Number(pendingEstimate.tax_amount) > 0 && (
                        <tr className="total-row">
                          <td colSpan={3} style={{ textAlign: "right" }}>Estimated Tax:</td>
                          <td className="num-col">₹{pendingEstimate.tax_amount}</td>
                        </tr>
                      )}
                      <tr className="total-row grand-total">
                        <td colSpan={3} style={{ textAlign: "right" }}>Grand Total:</td>
                        <td className="num-col">₹{pendingEstimate.total_amount}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>

                {estimateActionError && <p className="form-error" role="alert">{estimateActionError}</p>}

                <div className="estimate-decision-box">
                  <div className="estimate-decision-info">
                    {pendingEstimate.can_decide ? (
                      <span>Society cost responsibility requires your Facility Manager decision.</span>
                    ) : pendingEstimate.cost_responsibility === "RESIDENT_UNIT" ? (
                      <span>Cost responsibility is assigned to the Resident Unit. Awaiting resident approval.</span>
                    ) : (
                      <span>Decision pending authorized approver.</span>
                    )}
                  </div>

                  {pendingEstimate.can_decide && (
                    <div className="estimate-hold-actions">
                      <button
                        type="button"
                        className="estimate-reject-btn"
                        disabled={estimateActionLoading}
                        onClick={() => { setEstimateRejectOpen(true); setEstimateRejectReason(""); setEstimateActionError(""); }}
                      >
                        <XCircle size={15} /> Reject Quote
                      </button>
                      <button
                        type="button"
                        className="estimate-approve-btn"
                        disabled={estimateActionLoading}
                        onClick={handleApproveEstimate}
                      >
                        <CheckCircle2 size={15} /> {estimateActionLoading ? "Approving..." : "Approve Estimate"}
                      </button>
                    </div>
                  )}
                </div>

                {estimateRejectOpen && (
                  <div className="cancel-dialog" role="dialog" aria-labelledby="fm-reject-estimate-title" style={{ marginTop: 12 }}>
                    <p className="dialog-title" id="fm-reject-estimate-title">Reject Material Estimate</p>
                    <p className="dialog-copy">
                      Declining this quote will return the ticket to <strong>Supervisor Triage</strong> for reassignment or work order revision. A rejection reason is required for audit evidence.
                    </p>
                    <label className="dialog-label" htmlFor="fm-reject-estimate-reason">Rejection reason</label>
                    <textarea
                      className="dialog-textarea"
                      id="fm-reject-estimate-reason"
                      rows={3}
                      value={estimateRejectReason}
                      onChange={(e) => setEstimateRejectReason(e.target.value)}
                      placeholder="Specify reason for quote rejection..."
                      required
                    />
                    <div className="dialog-actions">
                      <button
                        type="button"
                        className="dialog-cancel"
                        disabled={estimateActionLoading}
                        onClick={() => setEstimateRejectOpen(false)}
                      >
                        Keep Reviewing
                      </button>
                      <button
                        type="button"
                        className="dialog-confirm"
                        disabled={estimateActionLoading || !estimateRejectReason.trim()}
                        onClick={handleRejectEstimate}
                      >
                        {estimateActionLoading ? "Rejecting..." : "Confirm Rejection"}
                      </button>
                    </div>
                  </div>
                )}
              </section>
            );
          })()}
          {canUseSupervisorControls && (
            <section className="service-supervisor-panel" aria-label="Supervisor emergency actions">
              <div className="service-supervisor-heading"><div><p className="workspace-kicker">Protected control</p><h2>Supervisor emergency action</h2></div><ShieldAlert size={19} /></div>
              <p>These actions require a mandatory audit reason. The server also verifies a fresh step-up authenticated session before recording the change.</p>
              <div className="supervisor-action-list">
                {canResumeFromTriage && <button type="button" onClick={() => setSupervisorCommand("RESUME")}><ShieldCheck size={16} /> Resume accepted work</button>}
                {canCompleteBySupervisor && <button className="supervisor-complete-command" type="button" onClick={() => setSupervisorCommand("COMPLETE")}><ShieldAlert size={16} /> Complete with supervisor evidence</button>}
              </div>
            </section>
          )}
          {canUseLifecycleControls && (
            <section className="service-lifecycle-panel" aria-label="Service lifecycle controls">
              <div className="service-lifecycle-heading"><div><p className="workspace-kicker">Lifecycle control</p><h2>Close or reopen request</h2></div><RotateCcw size={19} /></div>
              <p>Record a reviewed outcome, or return a resolved or closed request to accountable service triage.</p>
              <div className="lifecycle-action-list">
                {canReopen && <button className="reopen-command" type="button" onClick={() => { setLifecycleCommand("REOPEN"); setLifecycleReason(""); setLifecycleError(""); }}><RotateCcw size={16} /> Reopen request</button>}
                {canClose && <button className="close-command" type="button" onClick={() => { setLifecycleCommand("CLOSE"); setLifecycleReason(""); setLifecycleError(""); }}><Archive size={16} /> Close request</button>}
              </div>
            </section>
          )}
          {canInitiateMerge && (
            <section className="service-lifecycle-panel" aria-label="Duplicate request merge">
              <div className="service-lifecycle-heading"><div><p className="workspace-kicker">Deduplication</p><h2>Merge duplicate request</h2></div><GitMerge size={19} /></div>
              <p>Consolidate another active duplicate service request into this primary ticket with an audit reason.</p>
              <div className="lifecycle-action-list">
                <button className="primary-command" type="button" onClick={() => void openMergeDialog()}><GitMerge size={16} /> Merge duplicate request</button>
              </div>
            </section>
          )}
          {hasMergeRecoveryContext && activePrimaryMerge && (
            <section className="service-recovery-panel" aria-label="Merge recovery controls">
              <div className="service-recovery-heading"><div><p className="workspace-kicker">Protected recovery</p><h2>Recover merged request</h2></div><GitMerge size={19} /></div>
              {canUnmerge ? <><p>A merged request can be restored only within the Facility Manager recovery window. The server requires a fresh step-up authenticated session and an audit reason.</p><button className="recovery-command" type="button" onClick={() => void openUnmergeDialog(activePrimaryMerge)}><GitMerge size={16} /> Restore merged request</button></> : <p className="recovery-unavailable">The Facility Manager recovery window has expired. This merge remains in the operational record.</p>}
            </section>
          )}
          {!canDispatch && ticket.status !== "PENDING_ESTIMATE_APPROVAL" && !canUseSupervisorControls && !canUseLifecycleControls && !canInitiateMerge && !hasMergeRecoveryContext && (
            <section className="service-unavailable" aria-label="Unavailable service handling controls"><FileText size={19} /><div><h2>Service handling controls</h2><p>No additional operational action is available for this request state. SLA timing, authoritative estimate detail, secure completion, and audit history await their complete client contracts.</p></div></section>
          )}
        </div>

        <aside className="service-conversations">
          <section className="internal-notes public-conversation" aria-label="Resident conversation">
            <div className="internal-notes-heading"><div><p className="workspace-kicker">Resident-visible</p><h2>Conversation</h2></div><MessageSquare size={16} /></div>
            {!canCommunicate ? <p className="internal-notes-empty">Conversation opens after this request is submitted.</p> : publicLoading ? <p className="internal-notes-loading"><LoaderCircle className="spin" size={15} /> Loading conversation</p> : publicError ? <p className="conversation-error" role="alert">{publicError}</p> : publicComments.length === 0 ? <p className="internal-notes-empty">No resident messages yet.</p> : <div className="conversation-thread internal-notes-thread">{publicComments.map((comment) => <article className={comment.is_authored_by_requester ? "own" : ""} key={comment.id}><header><strong>{commentAuthor(comment)}</strong><time dateTime={comment.created_at}>{formatDate(comment.created_at)}</time></header><p>{comment.body}</p></article>)}</div>}
            {canCommunicate && <form className="message-composer" onSubmit={postPublicComment}><label className="sr-only" htmlFor="service-workspace-reply">Reply to the resident</label><textarea id="service-workspace-reply" maxLength={4000} onChange={(event) => setPublicBody(event.target.value)} placeholder="Reply to the resident" rows={2} value={publicBody} /><button type="submit" disabled={postingPublic || !publicBody.trim()} aria-label="Post resident reply" title="Post resident reply">{postingPublic ? <LoaderCircle className="spin" size={17} /> : <Send size={17} />}</button></form>}
          </section>

          <section className="internal-notes" aria-label="Private service notes">
            <div className="internal-notes-heading"><div><p className="workspace-kicker">Private workspace</p><h2>Internal notes</h2></div><LockKeyhole size={16} /></div>
            <p className="internal-notes-description">Visible only to authorized staff.</p>
            {!canCommunicate ? <p className="internal-notes-empty">Private notes open after this request is submitted.</p> : internalLoading ? <p className="internal-notes-loading"><LoaderCircle className="spin" size={15} /> Loading private notes</p> : internalError ? <p className="conversation-error" role="alert">{internalError}</p> : internalComments.length === 0 ? <p className="internal-notes-empty">No private notes yet.</p> : <div className="conversation-thread internal-notes-thread">{internalComments.map((comment) => <article className={comment.is_authored_by_requester ? "own" : ""} key={comment.id}><header><strong>{commentAuthor(comment)}</strong><time dateTime={comment.created_at}>{formatDate(comment.created_at)}</time></header><p>{comment.body}</p></article>)}</div>}
            {canCommunicate && <form className="message-composer" onSubmit={postInternalComment}><label className="sr-only" htmlFor="service-workspace-note">Add a private note</label><textarea id="service-workspace-note" maxLength={4000} onChange={(event) => setInternalBody(event.target.value)} placeholder="Add a private operational note" rows={2} value={internalBody} /><button type="submit" disabled={postingInternal || !internalBody.trim()} aria-label="Post private note" title="Post private note">{postingInternal ? <LoaderCircle className="spin" size={17} /> : <Send size={17} />}</button></form>}
          </section>
        </aside>
      </section>

      {supervisorCommand && <div className="dialog-backdrop" role="presentation">
        <section className="cancel-dialog supervisor-dialog" aria-labelledby="supervisor-command-title" aria-modal="true" role="dialog">
          <span className="cancel-dialog-icon supervisor-dialog-icon">{supervisorCommand === "RESUME" ? <ShieldCheck size={23} /> : <ShieldAlert size={23} />}</span>
          <div><p className="workspace-kicker">Step-up protected</p><h2 id="supervisor-command-title">{supervisorCommand === "RESUME" ? "Resume from supervisor triage" : "Supervisor completion override"}</h2><p>{supervisorCommand === "RESUME" ? "Document why the accepted work can safely resume." : "Document the inspection evidence that supports completion without resident confirmation."}</p></div>
          <form onSubmit={submitSupervisorCommand}>
            <p className="supervisor-security-note"><LockKeyhole size={15} /> The connected access token must carry a fresh verified step-up claim. This workspace cannot create one.</p>
            <label htmlFor="supervisor-reason">Audit reason</label>
            <textarea autoFocus id="supervisor-reason" maxLength={1000} onChange={(event) => setSupervisorReason(event.target.value)} placeholder="Record the operational reason for this action" rows={4} value={supervisorReason} />
            {supervisorCommand === "COMPLETE" && <><label htmlFor="supervisor-proof-notes">Inspection evidence</label><textarea id="supervisor-proof-notes" maxLength={2000} onChange={(event) => setProofNotes(event.target.value)} placeholder="Record the physical inspection or other verified evidence" rows={4} value={proofNotes} /></>}
            {supervisorError && <p className="cancel-error" role="alert">{supervisorError}</p>}
            <div className="cancel-dialog-actions"><button type="button" disabled={submittingSupervisorCommand} onClick={() => closeSupervisorCommand()}>Cancel</button><button className="destructive-command" type="submit" disabled={submittingSupervisorCommand || !supervisorReason.trim() || (supervisorCommand === "COMPLETE" && !proofNotes.trim())}>{submittingSupervisorCommand ? <LoaderCircle className="spin" size={15} /> : <LockKeyhole size={15} />}{supervisorCommand === "RESUME" ? "Confirm resume" : "Confirm completion"}</button></div>
          </form>
        </section>
      </div>}

      {lifecycleCommand && <div className="dialog-backdrop" role="presentation">
        <section className="cancel-dialog lifecycle-dialog" aria-labelledby="service-lifecycle-title" aria-modal="true" role="dialog">
          <span className="cancel-dialog-icon lifecycle-dialog-icon">{lifecycleCommand === "REOPEN" ? <RotateCcw size={23} /> : <Archive size={23} />}</span>
          <div><p className="workspace-kicker">{lifecycleCommand === "REOPEN" ? "Return to triage" : "Record closure"}</p><h2 id="service-lifecycle-title">{lifecycleCommand === "REOPEN" ? "Reopen service request" : "Close service request"}</h2><p>{lifecycleCommand === "REOPEN" ? "The request will return to supervisor triage with a renewed service-resolution SLA cycle." : "The completed request will be retained in the operational record. You may include a closing note."}</p></div>
          <form onSubmit={submitLifecycleCommand}>
            <label htmlFor="service-lifecycle-reason">{lifecycleCommand === "REOPEN" ? "Audit reason" : "Closing note (optional)"}</label>
            <textarea autoFocus id="service-lifecycle-reason" maxLength={1000} onChange={(event) => setLifecycleReason(event.target.value)} placeholder={lifecycleCommand === "REOPEN" ? "Explain why service work must resume" : "Add operational context for the closure"} rows={4} value={lifecycleReason} />
            {lifecycleError && <p className="cancel-error" role="alert">{lifecycleError}</p>}
            <div className="cancel-dialog-actions"><button type="button" disabled={submittingLifecycleCommand} onClick={() => closeLifecycleCommand()}>Keep current state</button><button className="lifecycle-command" type="submit" disabled={submittingLifecycleCommand || (lifecycleCommand === "REOPEN" && !lifecycleReason.trim())}>{submittingLifecycleCommand ? <LoaderCircle className="spin" size={15} /> : lifecycleCommand === "REOPEN" ? <RotateCcw size={15} /> : <Archive size={15} />}{submittingLifecycleCommand ? "Updating" : lifecycleCommand === "REOPEN" ? "Confirm reopen" : "Confirm closure"}</button></div>
          </form>
        </section>
      </div>}

      {dispatchDialogOpen && <div className="dialog-backdrop" role="presentation">
        <section className="cancel-dialog dispatch-dialog" aria-labelledby="dispatch-dialog-title" aria-modal="true" role="dialog">
          <span className="cancel-dialog-icon dispatch-dialog-icon"><ClipboardCheck size={23} /></span>
          <div><p className="workspace-kicker">Versioned dispatch</p><h2 id="dispatch-dialog-title">{ticket.status === "SUPERVISOR_TRIAGE" ? "Reassign service resource" : "Assign service provider"}</h2><p>Select an in-house technician or external vendor contract. Capacity and eligibility are atomically locked on submission.</p></div>
          <form onSubmit={submitDispatch}>
            <div className="dispatch-type-selector">
              <button
                type="button"
                className={`dispatch-type-button ${dispatchType === "IN_HOUSE" ? "active" : ""}`}
                onClick={() => { setDispatchType("IN_HOUSE"); setDispatchTargetId(""); }}
              >
                In-house ({availableTechnicians.length})
              </button>
              <button
                type="button"
                className={`dispatch-type-button ${dispatchType === "VENDOR" ? "active" : ""}`}
                onClick={() => { setDispatchType("VENDOR"); setDispatchTargetId(""); }}
              >
                Vendor contract ({availableVendorContracts.length})
              </button>
            </div>

            {dispatchTargetsLoading ? (
              <p className="internal-notes-loading"><LoaderCircle className="spin" size={15} /> Loading dispatch candidates</p>
            ) : dispatchTargetsError ? (
              <p className="cancel-error" role="alert">{dispatchTargetsError}</p>
            ) : dispatchType === "IN_HOUSE" ? (
              <>
                <label htmlFor="dispatch-target">Available in-house technician</label>
                <select id="dispatch-target" value={dispatchTargetId} onChange={(event) => setDispatchTargetId(event.target.value)}>
                  <option value="">Select a technician</option>
                  {availableTechnicians.map((tech) => {
                    const label = tech.user_email ?? tech.id.slice(0, 8);
                    const cap = tech.max_active_tickets === null ? "Unlimited" : `${tech.current_active_tickets_count}/${tech.max_active_tickets} active`;
                    return <option key={tech.id} value={tech.id}>{`${label} · (${cap})`}</option>;
                  })}
                </select>
                {availableTechnicians.length === 0 && <p className="dispatch-empty">No active in-house technician has remaining capacity.</p>}
              </>
            ) : (
              <>
                <label htmlFor="dispatch-target">Eligible vendor contract</label>
                <select id="dispatch-target" value={dispatchTargetId} onChange={(event) => setDispatchTargetId(event.target.value)}>
                  <option value="">Select a vendor contract</option>
                  {availableVendorContracts.map((contract) => {
                    const vendor = vendors.find((item) => item.id === contract.vendor);
                    const capacity = contract.max_active_tickets === null ? "Unlimited" : `${contract.current_active_tickets_count}/${contract.max_active_tickets} active`;
                    return <option key={contract.id} value={contract.id}>{`${vendor?.company_name ?? "Vendor"} · ${capacity}`}</option>;
                  })}
                </select>
                {availableVendorContracts.length === 0 && <p className="dispatch-empty">No active vendor contract has remaining capacity.</p>}
              </>
            )}

            {dispatchError && <p className="cancel-error" role="alert">{dispatchError}</p>}
            <div className="cancel-dialog-actions">
              <button type="button" disabled={submittingDispatch} onClick={() => closeDispatchDialog()}>Cancel</button>
              <button className="primary-command" type="submit" disabled={dispatchTargetsLoading || Boolean(dispatchTargetsError) || submittingDispatch || !dispatchTargetId}>
                {submittingDispatch ? <LoaderCircle className="spin" size={15} /> : <ClipboardCheck size={15} />}
                {ticket.status === "SUPERVISOR_TRIAGE" ? "Confirm reassignment" : "Confirm assignment"}
              </button>
            </div>
          </form>
        </section>
      </div>}

      {mergeDialogOpen && <div className="dialog-backdrop" role="presentation">
        <section className="cancel-dialog merge-dialog" aria-labelledby="merge-dialog-title" aria-modal="true" role="dialog">
          <span className="cancel-dialog-icon merge-dialog-icon"><GitMerge size={23} /></span>
          <div><p className="workspace-kicker">Ticket deduplication</p><h2 id="merge-dialog-title">Merge duplicate service request</h2><p>The secondary request will be marked as merged and its worker capacity/SLA cycle will be released. You must provide an audit reason.</p></div>
          <form onSubmit={submitMerge}>
            {mergeCandidatesLoading ? (
              <p className="internal-notes-loading"><LoaderCircle className="spin" size={15} /> Loading active service requests</p>
            ) : mergeCandidatesError ? (
              <p className="cancel-error" role="alert">{mergeCandidatesError}</p>
            ) : (
              <>
                <label htmlFor="merge-secondary-target">Select duplicate request to merge into this one</label>
                <select
                  id="merge-secondary-target"
                  value={mergeSecondaryId}
                  onChange={(event) => setMergeSecondaryId(event.target.value)}
                >
                  <option value="">Select a duplicate request</option>
                  {mergeCandidates.map((cand) => (
                    <option key={cand.id} value={cand.id}>
                      {`${cand.ticket_number} · ${cand.title} (${cand.status.replaceAll("_", " ")})`}
                    </option>
                  ))}
                </select>
                {mergeCandidates.length === 0 && <p className="dispatch-empty">No other active service requests found in this society.</p>}
                {selectedSecondaryCandidate && (
                  <div className="merge-candidate-card">
                    <header>
                      <strong>{selectedSecondaryCandidate.ticket_number}</strong>
                      <span className={`status-pill status-${selectedSecondaryCandidate.status.toLowerCase()}`}>
                        {selectedSecondaryCandidate.status.replaceAll("_", " ")}
                      </span>
                    </header>
                    <p>{selectedSecondaryCandidate.title}</p>
                  </div>
                )}
              </>
            )}
            <label htmlFor="service-merge-reason">Audit reason</label>
            <textarea
              autoFocus
              disabled={mergeCandidatesLoading || !mergeSecondaryId}
              id="service-merge-reason"
              maxLength={1000}
              onChange={(event) => setMergeReason(event.target.value)}
              placeholder="Explain why this request is a duplicate (e.g. Same issue reported by resident)"
              rows={3}
              value={mergeReason}
            />
            {mergeError && <p className="cancel-error" role="alert">{mergeError}</p>}
            <div className="cancel-dialog-actions">
              <button type="button" disabled={submittingMerge} onClick={() => closeMergeDialog()}>Cancel</button>
              <button
                className="primary-command"
                type="submit"
                disabled={mergeCandidatesLoading || !mergeSecondaryId || submittingMerge || !mergeReason.trim()}
              >
                {submittingMerge ? <LoaderCircle className="spin" size={15} /> : <GitMerge size={15} />}
                {submittingMerge ? "Merging" : "Confirm merge"}
              </button>
            </div>
          </form>
        </section>
      </div>}

      {unmergeDialogOpen && <div className="dialog-backdrop" role="presentation">
        <section className="cancel-dialog recovery-dialog" aria-labelledby="unmerge-dialog-title" aria-modal="true" role="dialog">
          <span className="cancel-dialog-icon recovery-dialog-icon"><GitMerge size={23} /></span>
          <div><p className="workspace-kicker">Step-up protected</p><h2 id="unmerge-dialog-title">Restore merged request</h2><p>The linked request returns to supervisor triage with a fresh SLA cycle. The server checks the recovery window and fresh step-up authentication before it records this action.</p></div>
          <form onSubmit={submitUnmerge}>
            {unmergeSecondaryLoading ? <p className="internal-notes-loading"><LoaderCircle className="spin" size={15} /> Loading linked request</p> : unmergeSecondaryTicket && <p className="recovery-linked-ticket">Linked request: <strong>{unmergeSecondaryTicket.ticket_number}</strong></p>}
            <label htmlFor="service-unmerge-reason">Audit reason</label>
            <textarea autoFocus disabled={unmergeSecondaryLoading || !unmergeSecondaryTicket} id="service-unmerge-reason" maxLength={1000} onChange={(event) => setUnmergeReason(event.target.value)} placeholder="Explain why these requests must be handled separately" rows={4} value={unmergeReason} />
            {unmergeError && <p className="cancel-error" role="alert">{unmergeError}</p>}
            <div className="cancel-dialog-actions"><button type="button" disabled={submittingUnmerge} onClick={() => closeUnmergeDialog()}>Keep merged</button><button className="recovery-command" type="submit" disabled={unmergeSecondaryLoading || !unmergeSecondaryTicket || submittingUnmerge || !unmergeReason.trim()}>{submittingUnmerge ? <LoaderCircle className="spin" size={15} /> : <GitMerge size={15} />}{submittingUnmerge ? "Restoring" : "Confirm restore"}</button></div>
          </form>
        </section>
      </div>}
    </div>
  );
}