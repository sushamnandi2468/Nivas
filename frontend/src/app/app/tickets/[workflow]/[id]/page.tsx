"use client";

import {
  AlertTriangle,
  ArrowLeft,
  Archive,
  Ban,
  CalendarClock,
  Check,
  CheckCircle2,
  Circle,
  Clock3,
  FileImage,
  FileText,
  KeyRound,
  LoaderCircle,
  MapPin,
  MessageSquare,
  Paperclip,
  ReceiptText,
  RefreshCw,
  RotateCcw,
  Send,
  ShieldCheck,
  UserRoundSearch,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

import {
  approveTicketEstimate,
  cancelTicket,
  closeTicket,
  createTicketComment,
  fetchTicketEstimates,
  getTicket,
  getTicketOptions,
  completeAttachmentUpload,
  issueAttachmentUploadSlot,
  listTicketAttachments,
  listTicketComments,
  rejectTicketEstimate,
  reopenTicket,
  submitTicket,
  uploadAttachmentFile,
  validateAttachmentFile,
  Ticket,
  TicketAttachment,
  TicketComment,
  TicketEstimate,
  TicketOptions,
  TicketWorkflow,
  verifyServiceTicketCompletion,
} from "@/lib/nivasops-api";
import { useWorkspaceSession } from "../../../session-context";

const SERVICE_STEPS = [
  { status: "DRAFT", label: "Request drafted", detail: "Details are retained in your workspace." },
  { status: "SUBMITTED", label: "Request submitted", detail: "The society operations queue has received it." },
  { status: "ASSIGNED", label: "Operations assignment", detail: "A qualified service resource is selected." },
  { status: "IN_PROGRESS", label: "Work in progress", detail: "The service task is actively being handled." },
  { status: "RESOLVED", label: "Resolution complete", detail: "Work is complete and retained in history." },
];

const GOVERNANCE_STEPS = [
  { status: "DRAFT", label: "Matter drafted", detail: "Details are retained in your workspace." },
  { status: "SUBMITTED", label: "Matter submitted", detail: "The society governance queue has received it." },
  { status: "SUPERVISOR_TRIAGE", label: "Supervisor triage", detail: "Scope and ownership are being established." },
  { status: "UNDER_REVIEW", label: "Under review", detail: "The responsible society body is reviewing it." },
  { status: "ACTION_TAKEN", label: "Action recorded", detail: "The resulting action has been documented." },
  { status: "CLOSED", label: "Matter closed", detail: "The governance lifecycle is complete." },
];

const SERVICE_STATUS_INDEX: Record<string, number> = {
  DRAFT: 0,
  SUBMITTED: 1,
  ASSIGNED: 2,
  ACCEPTED: 2,
  IN_PROGRESS: 3,
  PENDING_ESTIMATE_APPROVAL: 3,
  PENDING_RESIDENT_CONFIRMATION: 3,
  RESOLVED: 4,
  CLOSED: 4,
  CANCELLED: 1,
};

const GOVERNANCE_STATUS_INDEX: Record<string, number> = {
  DRAFT: 0,
  SUBMITTED: 1,
  SUPERVISOR_TRIAGE: 2,
  UNDER_REVIEW: 3,
  IN_DISCUSSION: 3,
  ACTION_TAKEN: 4,
  RESOLVED: 4,
  CLOSED: 5,
  CANCELLED: 1,
};

function formatDate(value?: string | null) {
  if (!value) return "Not yet available";
  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function labelForTicket(ticket: Ticket, options: TicketOptions | null) {
  const category = options?.categories.find((item) => item.id === ticket.category);
  const subcategory = category?.subcategories.find((item) => item.id === ticket.subcategory);
  const unit = options?.units.find((item) => item.id === ticket.unit);
  const commonArea = options?.common_areas.find((item) => item.id === ticket.common_area);
  return {
    category: category?.name ?? "Category",
    subcategory: subcategory?.name ?? "Classification unavailable",
    location: unit ? `${unit.block} · ${unit.door_number}` : commonArea?.name ?? "Society-wide",
  };
}

function commentAuthorLabel(comment: TicketComment) {
  if (comment.is_authored_by_requester) {
    return "You";
  }
  return comment.author_persona === "resident" ? "Resident" : "Society operations";
}

export default function TicketWorkspacePage() {
  const params = useParams<{ workflow: string; id: string }>();
  const workflow = (params.workflow || "service").toUpperCase() as TicketWorkflow;
  const { session } = useWorkspaceSession();
  const [ticket, setTicket] = useState<Ticket | null>(null);
  const [options, setOptions] = useState<TicketOptions | null>(null);
  const [comments, setComments] = useState<TicketComment[]>([]);
  const [commentBody, setCommentBody] = useState("");
  const [commentError, setCommentError] = useState("");
  const [commentsLoading, setCommentsLoading] = useState(false);
  const [postingComment, setPostingComment] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submissionError, setSubmissionError] = useState("");
  const [cancelOpen, setCancelOpen] = useState(false);
  const [cancelReason, setCancelReason] = useState("");
  const [cancelError, setCancelError] = useState("");
  const [cancelling, setCancelling] = useState(false);
  const [lifecycleCommand, setLifecycleCommand] = useState<"REOPEN" | "CLOSE" | null>(null);
  const [lifecycleReason, setLifecycleReason] = useState("");
  const [lifecycleError, setLifecycleError] = useState("");
  const [transitioningLifecycle, setTransitioningLifecycle] = useState(false);

  // Completion OTP State
  const [completionOtp, setCompletionOtp] = useState("");
  const [submittingCompletionOtp, setSubmittingCompletionOtp] = useState(false);
  const [completionOtpError, setCompletionOtpError] = useState("");

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
      getTicket(session, workflow, params.id),
      getTicketOptions(session),
    ])
      .then(([ticketResult, optionsResult]) => {
        if (!current) return;
        setTicket(ticketResult);
        setOptions(optionsResult);
        setError("");
      })
      .catch((reason: unknown) => {
        if (!current) return;
        setError(
          reason instanceof Error
            ? reason.message
            : "The requested ticket could not be loaded.",
        );
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, [params.id, refreshKey, session, workflow]);

  useEffect(() => {
    if (!session || !ticket || ticket.status === "DRAFT") {
      return;
    }
    let current = true;
    void listTicketComments(session, workflow, ticket.id)
      .then((result) => {
        if (!current) return;
        setComments(result);
        setCommentError("");
      })
      .catch((reason: unknown) => {
        if (!current) return;
        setCommentError(
          reason instanceof Error
            ? reason.message
            : "Conversation could not be loaded.",
        );
      })
      .finally(() => {
        if (current) setCommentsLoading(false);
      });
    return () => {
      current = false;
    };
  }, [session, ticket, workflow]);

  useEffect(() => {
    if (!session || !ticket || ticket.status === "DRAFT" || workflow !== "SERVICE") {
      return;
    }
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
  }, [session, ticket, workflow, refreshKey]);

  const [attachments, setAttachments] = useState<TicketAttachment[]>([]);
  const [attachmentsLoading, setAttachmentsLoading] = useState(false);
  const [uploadingAttachment, setUploadingAttachment] = useState(false);
  const [attachmentError, setAttachmentError] = useState("");

  useEffect(() => {
    if (!session || !ticket) {
      return;
    }
    let current = true;
    void listTicketAttachments(session, workflow, ticket.id)
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
  }, [session, ticket, workflow, refreshKey]);

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
      const slot = await issueAttachmentUploadSlot(session, workflow, ticket.id, {
        expected_version: ticket.state_version,
        filename: file.name,
        content_type: file.type || "image/jpeg",
        byte_size: file.size,
      });
      await uploadAttachmentFile(slot, file);
      await completeAttachmentUpload(session, slot.attachment.id, workflow, ticket.id).catch(() => {});
      setRefreshKey((prev) => prev + 1);
    } catch (err) {
      setAttachmentError(
        err instanceof Error ? err.message : "Failed to upload attachment.",
      );
    } finally {
      setUploadingAttachment(false);
    }
  }

  if (loading) {
    return (
      <div className="detail-loading">
        <LoaderCircle className="spin" size={24} />
        <span>Loading ticket details</span>
      </div>
    );
  }

  if (error || !ticket) {
    return (
      <div className="empty-state error-state">
        <AlertTriangle size={26} />
        <h3>Ticket unavailable</h3>
        <p>{error || "No ticket data was returned."}</p>
        <Link href="/app">Return to your requests</Link>
      </div>
    );
  }

  const currentTicket = ticket;
  const labels = labelForTicket(currentTicket, options);
  const isService = workflow === "SERVICE";
  const steps = isService ? SERVICE_STEPS : GOVERNANCE_STEPS;
  const statusIndexMap = isService ? SERVICE_STATUS_INDEX : GOVERNANCE_STATUS_INDEX;
  const isStopped = currentTicket.status === "CANCELLED" || currentTicket.status === "MERGED";
  const currentIndex = statusIndexMap[currentTicket.status] ?? 0;
  const canReopen = currentTicket.status === "RESOLVED" || currentTicket.status === "CLOSED";
  const canClose = currentTicket.status === "RESOLVED";

  async function handleSubmit() {
    if (!session) return;
    setSubmitting(true);
    setSubmissionError("");
    try {
      const result = await submitTicket(session, currentTicket);
      setTicket((current) => current ? {
        ...current,
        status: result.status,
        state_version: result.state_version,
        ticket_number: result.ticket_number,
      } : current);
      setRefreshKey((value) => value + 1);
    } catch (reason: unknown) {
      setSubmissionError(
        reason instanceof Error
          ? reason.message
          : "The request could not be submitted. Please verify the society calendar configuration.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCommentSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const body = commentBody.trim();
    if (!session || !body || currentTicket.status === "DRAFT") return;
    setPostingComment(true);
    setCommentError("");
    try {
      const comment = await createTicketComment(session, currentTicket, body);
      setComments((current) => [...current, comment]);
      setCommentBody("");
    } catch (reason: unknown) {
      setCommentError(
        reason instanceof Error
          ? reason.message
          : "Your message could not be posted.",
      );
    } finally {
      setPostingComment(false);
    }
  }

  async function handleCancelSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const reason = cancelReason.trim();
    if (!session || !reason) return;
    setCancelling(true);
    setCancelError("");
    try {
      const result = await cancelTicket(session, currentTicket, reason);
      setTicket((current) => (current && current.id === result.id ? { ...current, status: result.status, state_version: result.state_version } : current));
      setCancelOpen(false);
      setCancelReason("");
      setRefreshKey((value) => value + 1);
    } catch (reason: unknown) {
      setCancelError(
        reason instanceof Error
          ? reason.message
          : "The request could not be cancelled.",
      );
    } finally {
      setCancelling(false);
    }
  }

  function openLifecycleCommand(command: "REOPEN" | "CLOSE") {
    setLifecycleCommand(command);
    setLifecycleReason("");
    setLifecycleError("");
  }

  function closeLifecycleCommand() {
    if (transitioningLifecycle) return;
    setLifecycleCommand(null);
    setLifecycleReason("");
    setLifecycleError("");
  }

  async function handleLifecycleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !lifecycleCommand) return;
    const reason = lifecycleReason.trim();
    if (lifecycleCommand === "REOPEN" && !reason) return;
    setTransitioningLifecycle(true);
    setLifecycleError("");
    try {
      if (lifecycleCommand === "REOPEN") {
        await reopenTicket(session, currentTicket, reason);
      } else {
        await closeTicket(session, currentTicket, reason);
      }
      setLifecycleCommand(null);
      setLifecycleReason("");
      setLoading(true);
      setRefreshKey((value) => value + 1);
    } catch (errorReason) {
      setLifecycleError(
        errorReason instanceof Error
          ? errorReason.message
          : "The lifecycle change could not be recorded.",
      );
    } finally {
      setTransitioningLifecycle(false);
    }
  }

  async function handleVerifyCompletion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const otp = completionOtp.trim();
    if (!session || !currentTicket || !otp) return;
    setSubmittingCompletionOtp(true);
    setCompletionOtpError("");
    try {
      await verifyServiceTicketCompletion(session, currentTicket, otp);
      setCompletionOtp("");
      setLoading(true);
      setRefreshKey((value) => value + 1);
    } catch (reason) {
      setCompletionOtpError(reason instanceof Error ? reason.message : "Completion verification failed. Please check the OTP code.");
    } finally {
      setSubmittingCompletionOtp(false);
    }
  }

  async function handleApproveEstimate() {
    if (!session || !currentTicket) return;
    setEstimateActionLoading(true);
    setEstimateActionError("");
    try {
      await approveTicketEstimate(session, currentTicket);
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
    if (!session || !currentTicket || !estimateRejectReason.trim()) return;
    setEstimateActionLoading(true);
    setEstimateActionError("");
    try {
      await rejectTicketEstimate(session, currentTicket, estimateRejectReason.trim());
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

  return (
    <div className="ticket-detail page-enter">
      <div className="ticket-detail-header">
        <div className="page-titlebar">
          <Link className="icon-command" href="/app" aria-label="Back to requests" title="Back to requests"><ArrowLeft size={18} /></Link>
          <div><p className="workspace-kicker">{workflow === "SERVICE" ? "Service request" : "Civic matter"}</p><h1>{ticket.title}</h1><p>{ticket.ticket_number || `Draft · ${ticket.id.slice(0, 8)}`}</p></div>
        </div>
        <div className="detail-header-actions">
          <span className={`priority-marker priority-${ticket.priority.toLowerCase()}`}>{ticket.priority}</span>
          <span className={`status-pill status-${ticket.status.toLowerCase()}`}>{ticket.status.replaceAll("_", " ")}</span>
          {ticket.status === "SUBMITTED" && (
            <button className="icon-command cancel-command" type="button" aria-label="Cancel request" title="Cancel request" onClick={() => { setCancelError(""); setCancelOpen(true); }}><Ban size={17} /></button>
          )}
          {canReopen && <button className="icon-command lifecycle-reopen-command" type="button" aria-label="Reopen request" title="Reopen request" onClick={() => openLifecycleCommand("REOPEN")}><RotateCcw size={17} /></button>}
          {canClose && <button className="icon-command lifecycle-close-command" type="button" aria-label="Close request" title="Close request" onClick={() => openLifecycleCommand("CLOSE")}><Archive size={17} /></button>}
          <button className="icon-command" type="button" aria-label="Refresh request" title="Refresh request" onClick={() => { setLoading(true); setError(""); setRefreshKey((value) => value + 1); }}><RefreshCw size={17} /></button>
        </div>
      </div>

      {ticket.status === "DRAFT" && (
        <div className="submission-hold"><CalendarClock size={21} /><p><strong>Ready for review</strong><span>Submitting creates the society-local request number and starts its auditable SLA clock.</span>{submissionError && <em>{submissionError}</em>}</p><button type="button" disabled={submitting} onClick={handleSubmit}>{submitting ? <LoaderCircle className="spin" size={15} /> : <Send size={15} />}{submitting ? "Submitting" : "Submit request"}</button></div>
      )}

      {isStopped && (
        <div className="submission-hold stopped"><AlertTriangle size={21} /><p><strong>Lifecycle ended: {ticket.status.toLowerCase()}</strong><span>This request is retained for operational history.</span></p></div>
      )}

      {ticket.status === "PENDING_ESTIMATE_APPROVAL" && (() => {
        const pendingEstimate = estimates.find((e) => e.status === "SUBMITTED") || estimates[0];
        if (!pendingEstimate) {
          return (
            <div className="estimate-hold">
              <div className="estimate-hold-header">
                <ReceiptText size={22} />
                <p>
                  <strong>Cost estimate submitted & pending review</strong>
                  <span>Loading estimate line items and cost details...</span>
                </p>
              </div>
            </div>
          );
        }
        return (
          <div className="estimate-card">
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
                <strong>Notes from technician:</strong> {pendingEstimate.notes}
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
                  <span>Please review the quote and choose to approve work or reject to escalate.</span>
                ) : pendingEstimate.cost_responsibility === "SOCIETY" ? (
                  <span>This estimate is charged to Society funds and requires Facility Manager approval.</span>
                ) : (
                  <span>Cost approval for this unit requires an authorized unit occupant.</span>
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
                    <XCircle size={15} /> Reject Estimate
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
              <div className="cancel-dialog" role="dialog" aria-labelledby="reject-estimate-title" style={{ marginTop: 12 }}>
                <p className="dialog-title" id="reject-estimate-title">Reject Material Estimate</p>
                <p className="dialog-copy">
                  Rejecting this cost quote will immediately escalate this ticket to <strong>Supervisor Triage</strong> for Facility Manager review. A rejection reason is required for audit evidence.
                </p>
                <label className="dialog-label" htmlFor="reject-estimate-reason">Rejection reason</label>
                <textarea
                  className="dialog-textarea"
                  id="reject-estimate-reason"
                  rows={3}
                  value={estimateRejectReason}
                  onChange={(e) => setEstimateRejectReason(e.target.value)}
                  placeholder="State why this quote is declined (e.g. resident will procure parts directly)..."
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
          </div>
        );
      })()}

      {ticket.status === "PENDING_RESIDENT_CONFIRMATION" && (
        <div className="completion-hold">
          <div className="completion-hold-header">
            <KeyRound size={22} />
            <p>
              <strong>Verify service completion</strong>
              <span>The technician has completed on-site work and requested your verification. Enter the 6-digit completion OTP to inspect and confirm resolution.</span>
            </p>
          </div>
          <form className="completion-otp-form" onSubmit={handleVerifyCompletion}>
            <label className="sr-only" htmlFor="completion-otp-input">6-digit completion OTP</label>
            <input
              autoFocus
              className="otp-input-field"
              id="completion-otp-input"
              maxLength={6}
              onChange={(e) => setCompletionOtp(e.target.value.replace(/\D/g, ""))}
              placeholder="000000"
              required
              value={completionOtp}
            />
            <button type="submit" disabled={submittingCompletionOtp || completionOtp.length < 6}>
              {submittingCompletionOtp ? <LoaderCircle className="spin" size={15} /> : <Check size={15} />}
              {submittingCompletionOtp ? "Verifying" : "Confirm completion"}
            </button>
          </form>
          {completionOtpError && <p className="cancel-error" role="alert">{completionOtpError}</p>}
        </div>
      )}

      <div className="ticket-detail-grid">
        <div className="detail-primary-column">
          <section className="detail-section">
            <div className="section-heading"><div><p className="workspace-kicker">State version {ticket.state_version}</p><h2>Request lifecycle</h2></div></div>
            <ol className="lifecycle-timeline">
              {steps.map((step, index) => {
                const state = isStopped ? index <= currentIndex ? "complete" : "upcoming" : index < currentIndex ? "complete" : index === currentIndex ? "current" : "upcoming";
                return (
                  <li className={state} key={step.status}>
                    <span className="timeline-node">{state === "complete" ? <Check size={14} /> : state === "current" ? <Clock3 size={14} /> : <Circle size={9} />}</span>
                    <p><strong>{step.label}</strong><small>{step.detail}</small>{state === "current" && <em>Current state · {ticket.status.replaceAll("_", " ")}</em>}</p>
                  </li>
                );
              })}
            </ol>
          </section>

          <section className="detail-section request-description">
            <div className="section-heading"><div><p className="workspace-kicker">Resident report</p><h2>Issue details</h2></div></div>
            <p className="ticket-description-text">{ticket.description}</p>
            <div className="ticket-attachments-panel">
              <div className="attachments-header">
                <div className="attachments-title">
                  <FileImage size={18} />
                  <h3>Media evidence ({attachments.length})</h3>
                </div>
                {!["CANCELLED", "CLOSED", "MERGED"].includes(ticket.status) && (
                  <label className="attach-file-action-btn">
                    {uploadingAttachment ? (
                      <LoaderCircle className="spin" size={14} />
                    ) : (
                      <Paperclip size={14} />
                    )}
                    <span>{uploadingAttachment ? "Uploading..." : "Attach evidence"}</span>
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
                  <span>No media evidence attached yet.</span>
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
        </div>

        <aside className="detail-side-column">
          <section className="detail-section ticket-facts">
            <div className="section-heading"><div><p className="workspace-kicker">Classification</p><h2>Request facts</h2></div></div>
            <dl>
              <div><dt>Category</dt><dd>{labels.category}</dd></div>
              <div><dt>Issue</dt><dd>{labels.subcategory}</dd></div>
              <div><dt>Location</dt><dd><MapPin size={14} /> {labels.location}</dd></div>
              <div><dt>Created</dt><dd>{formatDate(ticket.created_at)}</dd></div>
              <div><dt>Submitted</dt><dd>{formatDate(ticket.submitted_at)}</dd></div>
            </dl>
          </section>

          <section className="detail-section unavailable-capability">
            <div className="capability-icon"><UserRoundSearch size={21} /></div><div><h3>Service assignment</h3><p>Technician and vendor allocation will appear when a resident-safe assignment detail contract is available.</p></div><span>Unavailable</span>
          </section>

          <section className="detail-section conversation-panel">
            <div className="section-heading"><div><p className="workspace-kicker">Updates</p><h2>Conversation</h2></div><ShieldCheck size={18} /></div>
            {ticket.status === "DRAFT" ? (
              <div className="conversation-empty"><MessageSquare size={22} /><p><strong>Conversation opens after submission</strong><small>Review and submit this draft before posting an update.</small></p></div>
            ) : commentsLoading ? (
              <div className="conversation-empty"><LoaderCircle className="spin" size={22} /><p><strong>Loading conversation</strong><small>Retrieving the latest public updates.</small></p></div>
            ) : comments.length === 0 ? (
              <div className="conversation-empty"><MessageSquare size={22} /><p><strong>No updates yet</strong><small>Messages from you and society operations will appear here.</small></p></div>
            ) : (
              <div className="conversation-thread" aria-label="Ticket conversation">
                {comments.map((comment) => (
                  <article className={comment.is_authored_by_requester ? "own" : ""} key={comment.id}>
                    <header><strong>{commentAuthorLabel(comment)}</strong><time dateTime={comment.created_at}>{formatDate(comment.created_at)}</time></header>
                    <p>{comment.body}</p>
                  </article>
                ))}
              </div>
            )}
            {ticket.status !== "DRAFT" && (
              <form className="message-composer" onSubmit={handleCommentSubmit}>
                <label className="sr-only" htmlFor="ticket-comment">Post an update</label>
                <textarea id="ticket-comment" maxLength={4000} onChange={(event) => setCommentBody(event.target.value)} placeholder="Write an update" rows={2} value={commentBody} />
                <button type="submit" disabled={postingComment || !commentBody.trim()} aria-label="Post update" title="Post update">{postingComment ? <LoaderCircle className="spin" size={17} /> : <Send size={17} />}</button>
              </form>
            )}
            {commentError && <p className="conversation-error" role="alert">{commentError}</p>}
          </section>
        </aside>
      </div>

      {cancelOpen && (
        <div className="dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !cancelling) setCancelOpen(false); }}>
          <section className="cancel-dialog" role="dialog" aria-modal="true" aria-labelledby="cancel-dialog-title" onKeyDown={(event) => { if (event.key === "Escape" && !cancelling) setCancelOpen(false); }}>
            <div className="cancel-dialog-icon"><Ban size={22} /></div>
            <div>
              <p className="workspace-kicker">End lifecycle</p>
              <h2 id="cancel-dialog-title">Cancel this request?</h2>
              <p>The operations queue will stop work on this submitted request. The reason is retained in its audit history.</p>
            </div>
            <form onSubmit={handleCancelSubmit}>
              <label htmlFor="cancel-reason">Reason for cancellation</label>
              <textarea id="cancel-reason" autoFocus maxLength={1000} onChange={(event) => setCancelReason(event.target.value)} placeholder="Explain why this request is no longer needed" rows={4} value={cancelReason} />
              {cancelError && <p className="cancel-error" role="alert">{cancelError}</p>}
              <div className="cancel-dialog-actions">
                <button type="button" disabled={cancelling} onClick={() => setCancelOpen(false)}>Keep request</button>
                <button className="destructive-command" type="submit" disabled={cancelling || !cancelReason.trim()}>{cancelling ? <LoaderCircle className="spin" size={15} /> : <Ban size={15} />}{cancelling ? "Cancelling" : "Cancel request"}</button>
              </div>
            </form>
          </section>
        </div>
      )}

      {lifecycleCommand && (
        <div className="dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) closeLifecycleCommand(); }}>
          <section className="cancel-dialog lifecycle-dialog" role="dialog" aria-modal="true" aria-labelledby="lifecycle-dialog-title" onKeyDown={(event) => { if (event.key === "Escape") closeLifecycleCommand(); }}>
            <div className="cancel-dialog-icon lifecycle-dialog-icon">{lifecycleCommand === "REOPEN" ? <RotateCcw size={22} /> : <Archive size={22} />}</div>
            <div>
              <p className="workspace-kicker">{lifecycleCommand === "REOPEN" ? "Resume lifecycle" : "Close lifecycle"}</p>
              <h2 id="lifecycle-dialog-title">{lifecycleCommand === "REOPEN" ? "Reopen this request?" : "Close this request?"}</h2>
              <p>{lifecycleCommand === "REOPEN" ? "The request will return to the society operations queue, and the reason will be retained in its audit history." : "The completed request will be retained in history. You can include an optional closing note."}</p>
            </div>
            <form onSubmit={handleLifecycleSubmit}>
              <label htmlFor="lifecycle-reason">{lifecycleCommand === "REOPEN" ? "Reason for reopening" : "Closing note (optional)"}</label>
              <textarea id="lifecycle-reason" autoFocus maxLength={1000} onChange={(event) => setLifecycleReason(event.target.value)} placeholder={lifecycleCommand === "REOPEN" ? "Explain what still needs attention" : "Add context for the completed request"} rows={4} value={lifecycleReason} />
              {lifecycleError && <p className="cancel-error" role="alert">{lifecycleError}</p>}
              <div className="cancel-dialog-actions">
                <button type="button" disabled={transitioningLifecycle} onClick={closeLifecycleCommand}>Keep request as is</button>
                <button className="lifecycle-command" type="submit" disabled={transitioningLifecycle || (lifecycleCommand === "REOPEN" && !lifecycleReason.trim())}>{transitioningLifecycle ? <LoaderCircle className="spin" size={15} /> : lifecycleCommand === "REOPEN" ? <RotateCcw size={15} /> : <Archive size={15} />}{transitioningLifecycle ? "Updating" : lifecycleCommand === "REOPEN" ? "Reopen request" : "Close request"}</button>
              </div>
            </form>
          </section>
        </div>
      )}
    </div>
  );
}