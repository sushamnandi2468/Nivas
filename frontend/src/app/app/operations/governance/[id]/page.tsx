"use client";

import {
  AlertTriangle,
  ArrowLeft,
  Archive,
  ClipboardCheck,
  FileText,
  GitMerge,
  LoaderCircle,
  LockKeyhole,
  MessageSquare,
  RefreshCw,
  RotateCcw,
  Send,
  ShieldAlert,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

import {
  beginGovernanceReview,
  cancelTicket,
  closeTicket,
  createInternalTicketComment,
  createTicketComment,
  getTicket,
  isFacilityManagerSession,
  listInternalTicketComments,
  listTicketMergeHistory,
  listTicketComments,
  listTickets,
  mergeTicket,
  NivasOpsApiError,
  openGovernanceDiscussion,
  recordGovernanceAction,
  reopenTicket,
  Ticket,
  TicketComment,
  TicketMergeRecord,
  unmergeTicket,
} from "@/lib/nivasops-api";
import { useWorkspaceSession } from "../../../session-context";

type DraftCommand = "DISCUSSION" | "ACTION" | "CANCEL" | null;
type LifecycleCommand = "REOPEN" | "CLOSE" | null;
const FACILITY_MANAGER_UNMERGE_WINDOW_MS = 24 * 60 * 60 * 1000;

function formatDate(value?: string | null) {
  if (!value) return "Not available";
  return new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function statusLabel(status: string) {
  return status.replaceAll("_", " ");
}

function commandLabel(command: Exclude<DraftCommand, null>) {
  return command === "DISCUSSION" ? "Open discussion" : command === "ACTION" ? "Record action" : "Cancel ticket";
}

function commentAuthor(comment: TicketComment) {
  if (comment.is_authored_by_requester) return "You";
  return comment.author_persona === "committee" ? "Committee" : "Society operations";
}

export default function GovernanceTicketWorkspacePage() {
  const params = useParams<{ id: string }>();
  const { session } = useWorkspaceSession();
  const [ticket, setTicket] = useState<Ticket | null>(null);
  const [publicComments, setPublicComments] = useState<TicketComment[]>([]);
  const [internalComments, setInternalComments] = useState<TicketComment[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [publicLoading, setPublicLoading] = useState(true);
  const [internalLoading, setInternalLoading] = useState(true);
  const [error, setError] = useState("");
  const [publicError, setPublicError] = useState("");
  const [internalError, setInternalError] = useState("");
  const [mutationError, setMutationError] = useState("");
  const [draftCommand, setDraftCommand] = useState<DraftCommand>(null);
  const [commandText, setCommandText] = useState("");
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

  // Merge Dialog State
  const [mergeDialogOpen, setMergeDialogOpen] = useState(false);
  const [mergeCandidates, setMergeCandidates] = useState<Ticket[]>([]);
  const [mergeCandidatesLoading, setMergeCandidatesLoading] = useState(false);
  const [mergeCandidatesError, setMergeCandidatesError] = useState("");
  const [mergeSecondaryId, setMergeSecondaryId] = useState("");
  const [mergeReason, setMergeReason] = useState("");
  const [mergeError, setMergeError] = useState("");
  const [submittingMerge, setSubmittingMerge] = useState(false);

  const [publicBody, setPublicBody] = useState("");
  const [internalBody, setInternalBody] = useState("");
  const [mutating, setMutating] = useState(false);
  const [postingPublic, setPostingPublic] = useState(false);
  const [postingInternal, setPostingInternal] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    if (!session) return;
    let current = true;
    void getTicket(session, "GOVERNANCE", params.id)
      .then((result) => {
        if (current) {
          setTicket(result);
          setError("");
        }
      })
      .catch((reason: unknown) => { if (current) setError(reason instanceof Error ? reason.message : "Governance matter details could not be loaded."); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [params.id, refreshKey, session]);

  useEffect(() => {
    if (!session) return;
    let current = true;
    void listTicketMergeHistory(session, "GOVERNANCE", params.id).then((records) => {
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
      listTicketComments(session, "GOVERNANCE", ticket.id),
      listInternalTicketComments(session, "GOVERNANCE", ticket.id),
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

  async function refreshWorkspace() {
    setRefreshing(true);
    setRefreshKey((value) => value + 1);
    setRefreshing(false);
  }

  async function beginReview() {
    if (!session || !ticket || mutating) return;
    setMutating(true);
    setMutationError("");
    try {
      const result = await beginGovernanceReview(session, ticket);
      setTicket((current) => current && current.id === result.id
        ? { ...current, status: result.status, state_version: result.state_version }
        : current);
      setRefreshKey((value) => value + 1);
    } catch (reason: unknown) {
      setMutationError(reason instanceof NivasOpsApiError && reason.status === 409
        ? "This matter changed elsewhere. Refresh and review its current state."
        : reason instanceof Error ? reason.message : "Review could not be started.");
    } finally {
      setMutating(false);
    }
  }

  async function submitCommand(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = commandText.trim();
    if (!session || !ticket || !draftCommand || mutating || !text) return;
    setMutating(true);
    setMutationError("");
    try {
      const result = draftCommand === "DISCUSSION"
        ? await openGovernanceDiscussion(session, ticket, text)
        : draftCommand === "ACTION"
          ? await recordGovernanceAction(session, ticket, text)
          : await cancelTicket(session, ticket, text);
      setTicket((current) => current && current.id === result.id
        ? { ...current, status: result.status, state_version: result.state_version }
        : current);
      setDraftCommand(null);
      setCommandText("");
      setRefreshKey((value) => value + 1);
    } catch (reason: unknown) {
      setMutationError(reason instanceof NivasOpsApiError && reason.status === 409
        ? "This matter changed elsewhere. Refresh and review its current state."
        : reason instanceof Error ? reason.message : "The governance transition could not be recorded.");
    } finally {
      setMutating(false);
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
        ? "This matter changed elsewhere. Refresh and review its current state."
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
      setUnmergeSecondaryTicket(await getTicket(session, "GOVERNANCE", record.secondary_ticket_id));
    } catch (reason: unknown) {
      setUnmergeError(reason instanceof Error ? reason.message : "The merged matter could not be loaded for recovery.");
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
          ? "One of the linked matters changed elsewhere. Refresh and review the current record."
          : reason instanceof Error ? reason.message : "The merge recovery could not be completed.");
    } finally {
      setSubmittingUnmerge(false);
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
        item.workflow_type === "GOVERNANCE"
        && item.id !== params.id
        && item.status !== "DRAFT"
        && item.status !== "RESOLVED"
        && item.status !== "CLOSED"
        && item.status !== "CANCELLED"
        && item.status !== "MERGED"
      ));
      setMergeCandidates(candidates);
    } catch (reason: unknown) {
      setMergeCandidatesError(reason instanceof Error ? reason.message : "Active governance matters could not be loaded.");
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
        ? "One of the matters changed state or was already merged. Refresh and try again."
        : reason instanceof Error ? reason.message : "The duplicate merge could not be recorded.");
    } finally {
      setSubmittingMerge(false);
    }
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

  if (loading) return <div className="detail-loading"><LoaderCircle className="spin" size={24} /><span>Loading governance matter</span></div>;
  if (error || !ticket) return <div className="empty-state error-state"><AlertTriangle size={26} /><h3>Governance matter unavailable</h3><p>{error || "No ticket data was returned."}</p><Link href="/app/operations">Return to governance queue</Link></div>;

  const canPublicComment = ticket.status !== "DRAFT";
  const canInternalComment = ticket.status !== "DRAFT";
  const canManageLifecycle = Boolean(session && isFacilityManagerSession(session));
  const canReopen = canManageLifecycle && (ticket.status === "RESOLVED" || ticket.status === "CLOSED");
  const canClose = canManageLifecycle && ticket.status === "RESOLVED";
  const canInitiateMerge = canManageLifecycle && ticket.status !== "DRAFT" && ticket.status !== "RESOLVED" && ticket.status !== "CLOSED" && ticket.status !== "CANCELLED" && ticket.status !== "MERGED";
  const activePrimaryMerge = mergeRecords.find((record) => record.is_active && record.primary_ticket_id === ticket.id);
  const canUnmerge = Boolean(
    session
    && isFacilityManagerSession(session)
    && activePrimaryMerge
    && mergeRecoveryWindowOpen,
  );
  const hasMergeRecoveryContext = Boolean(activePrimaryMerge);
  const selectedSecondaryCandidate = mergeCandidates.find((item) => item.id === mergeSecondaryId);

  return (
    <div className="operations-page governance-workspace page-enter">
      <section className="operations-header">
        <div className="service-workspace-title">
          <Link className="icon-command" href="/app/operations" aria-label="Back to governance queue" title="Back to governance queue"><ArrowLeft size={18} /></Link>
          <div><p className="workspace-kicker">Civic matter · {ticket.ticket_number}</p><h1>{ticket.title}</h1><p>Canonical report, review state, and the available governance actions.</p></div>
        </div>
        <button className="icon-command" type="button" title="Refresh governance matter" aria-label="Refresh governance matter" disabled={refreshing} onClick={() => void refreshWorkspace()}><RefreshCw className={refreshing ? "spin" : ""} size={17} /></button>
      </section>

      <section className="service-workspace-grid governance-workspace-grid">
        <div className="service-workspace-main">
          <section className="service-dossier">
            <div className="service-dossier-heading"><span className={`priority-marker priority-${ticket.priority.toLowerCase()}`}>{ticket.priority}</span><span className={`status-pill status-${ticket.status.toLowerCase()}`}>{statusLabel(ticket.status)}</span></div>
            <p className="workspace-kicker">Resident report</p>
            <p>{ticket.description}</p>
            <dl><div><dt>Category</dt><dd>{ticket.category}</dd></div><div><dt>Current version</dt><dd>{ticket.state_version}</dd></div><div><dt>Submitted</dt><dd>{formatDate(ticket.submitted_at)}</dd></div></dl>
          </section>

          <section className="service-unavailable" aria-label="Unavailable governance resolution"><FileText size={19} /><div><h2>Resolution controls</h2><p>Resolution is unavailable until the required tenant approval policy is approved and implemented.</p></div></section>
        </div>

        <aside className="service-conversations governance-actions-panel">
          <section className="governance-action-workspace" aria-label="Governance actions">
            <div className="internal-notes-heading"><div><p className="workspace-kicker">Workflow</p><h2>Available actions</h2></div><ClipboardCheck size={16} /></div>
            {mutationError && <p className="command-error" role="alert">{mutationError}</p>}
            {ticket.status === "SUBMITTED" && <button className="primary-command" type="button" disabled={mutating} onClick={() => void beginReview()}>{mutating ? <LoaderCircle className="spin" size={16} /> : <ClipboardCheck size={16} />} Begin review</button>}
            {ticket.status === "UNDER_REVIEW" && <div className="command-actions"><button type="button" onClick={() => setDraftCommand("DISCUSSION")}>Open discussion</button><button type="button" onClick={() => setDraftCommand("ACTION")}>Record action</button><button className="quiet-danger" type="button" onClick={() => setDraftCommand("CANCEL")}>Cancel</button></div>}
            {ticket.status === "IN_DISCUSSION" && <div className="command-actions"><button type="button" onClick={() => setDraftCommand("ACTION")}>Record action</button><button className="quiet-danger" type="button" onClick={() => setDraftCommand("CANCEL")}>Cancel</button></div>}
            {ticket.status === "ACTION_TAKEN" && <p className="blocked-transition"><ShieldAlert size={16} /> Resolution is unavailable until the required approval policy is configured.</p>}
            {(canReopen || canClose) && <div className="command-actions"><button className="governance-reopen-command" type="button" onClick={() => { setLifecycleCommand("REOPEN"); setLifecycleReason(""); setLifecycleError(""); }}><RotateCcw size={15} /> Reopen</button>{canClose && <button className="governance-close-command" type="button" onClick={() => { setLifecycleCommand("CLOSE"); setLifecycleReason(""); setLifecycleError(""); }}><Archive size={15} /> Close</button>}</div>}
            {canInitiateMerge && <div className="command-actions" style={{ marginTop: "8px" }}><button className="governance-reopen-command" type="button" onClick={() => void openMergeDialog()}><GitMerge size={15} /> Merge duplicate matter</button></div>}
            {hasMergeRecoveryContext && activePrimaryMerge && <div className="governance-merge-recovery"><p>{canUnmerge ? "This primary matter has an active merged item. Recovery is limited to the Facility Manager window and requires fresh step-up authentication." : "The Facility Manager recovery window has expired. This merge remains in the governance record."}</p>{canUnmerge && <div className="command-actions"><button className="governance-recovery-command" type="button" onClick={() => void openUnmergeDialog(activePrimaryMerge)}><GitMerge size={15} /> Restore merged matter</button></div>}</div>}
            {ticket.status === "CANCELLED" && <p className="blocked-transition"><ShieldAlert size={16} /> This matter has been cancelled and cannot be changed.</p>}
            {draftCommand && <form className="governance-command-form" onSubmit={submitCommand}><label htmlFor="governance-command-text">{draftCommand === "DISCUSSION" ? "Discussion purpose" : draftCommand === "ACTION" ? "Action summary" : "Cancellation reason"}</label><textarea id="governance-command-text" autoFocus maxLength={1000} rows={4} value={commandText} onChange={(event) => setCommandText(event.target.value)} /><div><button type="button" disabled={mutating} onClick={() => { setDraftCommand(null); setCommandText(""); }}>Discard</button><button className={draftCommand === "CANCEL" ? "destructive-command" : "primary-command"} type="submit" disabled={mutating || !commandText.trim()}>{mutating ? <LoaderCircle className="spin" size={15} /> : null}{commandLabel(draftCommand)}</button></div></form>}
          </section>

          <section className="internal-notes public-conversation" aria-label="Resident conversation">
            <div className="internal-notes-heading"><div><p className="workspace-kicker">Resident-visible</p><h2>Conversation</h2></div><MessageSquare size={16} /></div>
            {publicLoading ? <p className="internal-notes-loading"><LoaderCircle className="spin" size={15} /> Loading conversation</p> : publicError ? <p className="conversation-error" role="alert">{publicError}</p> : publicComments.length === 0 ? <p className="internal-notes-empty">No resident messages yet.</p> : <div className="conversation-thread internal-notes-thread">{publicComments.map((comment) => <article className={comment.is_authored_by_requester ? "own" : ""} key={comment.id}><header><strong>{commentAuthor(comment)}</strong><time dateTime={comment.created_at}>{formatDate(comment.created_at)}</time></header><p>{comment.body}</p></article>)}</div>}
            {canPublicComment && <form className="message-composer" onSubmit={postPublicComment}><label className="sr-only" htmlFor="governance-workspace-reply">Reply to the resident</label><textarea id="governance-workspace-reply" maxLength={4000} onChange={(event) => setPublicBody(event.target.value)} placeholder="Reply to the resident" rows={2} value={publicBody} /><button type="submit" disabled={postingPublic || !publicBody.trim()} aria-label="Post resident reply" title="Post resident reply">{postingPublic ? <LoaderCircle className="spin" size={17} /> : <Send size={17} />}</button></form>}
          </section>

          <section className="internal-notes" aria-label="Private governance notes">
            <div className="internal-notes-heading"><div><p className="workspace-kicker">Private workspace</p><h2>Internal notes</h2></div><LockKeyhole size={16} /></div>
            <p className="internal-notes-description">Visible only to authorized staff and committee members.</p>
            {!canInternalComment ? <p className="internal-notes-empty">Private notes open after this matter is submitted.</p> : internalLoading ? <p className="internal-notes-loading"><LoaderCircle className="spin" size={15} /> Loading private notes</p> : internalError ? <p className="conversation-error" role="alert">{internalError}</p> : internalComments.length === 0 ? <p className="internal-notes-empty">No private notes yet.</p> : <div className="conversation-thread internal-notes-thread">{internalComments.map((comment) => <article className={comment.is_authored_by_requester ? "own" : ""} key={comment.id}><header><strong>{commentAuthor(comment)}</strong><time dateTime={comment.created_at}>{formatDate(comment.created_at)}</time></header><p>{comment.body}</p></article>)}</div>}
            {canInternalComment && <form className="message-composer" onSubmit={postInternalComment}><label className="sr-only" htmlFor="governance-workspace-note">Add a private note</label><textarea id="governance-workspace-note" maxLength={4000} onChange={(event) => setInternalBody(event.target.value)} placeholder="Add a private operational note" rows={2} value={internalBody} /><button type="submit" disabled={postingInternal || !internalBody.trim()} aria-label="Post private note" title="Post private note">{postingInternal ? <LoaderCircle className="spin" size={17} /> : <Send size={17} />}</button></form>}
          </section>
        </aside>
      </section>

      {lifecycleCommand && <div className="dialog-backdrop" role="presentation">
        <section className="cancel-dialog lifecycle-dialog" aria-labelledby="governance-lifecycle-title" aria-modal="true" role="dialog">
          <span className="cancel-dialog-icon lifecycle-dialog-icon">{lifecycleCommand === "REOPEN" ? <RotateCcw size={23} /> : <Archive size={23} />}</span>
          <div><p className="workspace-kicker">{lifecycleCommand === "REOPEN" ? "Return to review" : "Record closure"}</p><h2 id="governance-lifecycle-title">{lifecycleCommand === "REOPEN" ? "Reopen civic matter" : "Close civic matter"}</h2><p>{lifecycleCommand === "REOPEN" ? "The matter will return to formal review with a renewed governance-resolution SLA cycle." : "The resolved matter will be retained in the governance record. You may include a closing note."}</p></div>
          <form onSubmit={submitLifecycleCommand}>
            <label htmlFor="governance-lifecycle-reason">{lifecycleCommand === "REOPEN" ? "Audit reason" : "Closing note (optional)"}</label>
            <textarea autoFocus id="governance-lifecycle-reason" maxLength={1000} onChange={(event) => setLifecycleReason(event.target.value)} placeholder={lifecycleCommand === "REOPEN" ? "Explain why the matter requires further review" : "Add governance context for the closure"} rows={4} value={lifecycleReason} />
            {lifecycleError && <p className="cancel-error" role="alert">{lifecycleError}</p>}
            <div className="cancel-dialog-actions"><button type="button" disabled={submittingLifecycleCommand} onClick={() => closeLifecycleCommand()}>Keep current state</button><button className="lifecycle-command" type="submit" disabled={submittingLifecycleCommand || (lifecycleCommand === "REOPEN" && !lifecycleReason.trim())}>{submittingLifecycleCommand ? <LoaderCircle className="spin" size={15} /> : lifecycleCommand === "REOPEN" ? <RotateCcw size={15} /> : <Archive size={15} />}{submittingLifecycleCommand ? "Updating" : lifecycleCommand === "REOPEN" ? "Confirm reopen" : "Confirm closure"}</button></div>
          </form>
        </section>
      </div>}

      {mergeDialogOpen && <div className="dialog-backdrop" role="presentation">
        <section className="cancel-dialog merge-dialog" aria-labelledby="governance-merge-dialog-title" aria-modal="true" role="dialog">
          <span className="cancel-dialog-icon merge-dialog-icon"><GitMerge size={23} /></span>
          <div><p className="workspace-kicker">Matter deduplication</p><h2 id="governance-merge-dialog-title">Merge duplicate governance matter</h2><p>The secondary matter will be marked as merged into this primary record. You must provide an audit reason.</p></div>
          <form onSubmit={submitMerge}>
            {mergeCandidatesLoading ? (
              <p className="internal-notes-loading"><LoaderCircle className="spin" size={15} /> Loading active governance matters</p>
            ) : mergeCandidatesError ? (
              <p className="cancel-error" role="alert">{mergeCandidatesError}</p>
            ) : (
              <>
                <label htmlFor="gov-merge-secondary-target">Select duplicate matter to merge into this one</label>
                <select
                  id="gov-merge-secondary-target"
                  value={mergeSecondaryId}
                  onChange={(event) => setMergeSecondaryId(event.target.value)}
                >
                  <option value="">Select a duplicate matter</option>
                  {mergeCandidates.map((cand) => (
                    <option key={cand.id} value={cand.id}>
                      {`${cand.ticket_number} · ${cand.title} (${cand.status.replaceAll("_", " ")})`}
                    </option>
                  ))}
                </select>
                {mergeCandidates.length === 0 && <p className="dispatch-empty">No other active governance matters found in this society.</p>}
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
            <label htmlFor="gov-merge-reason">Audit reason</label>
            <textarea
              autoFocus
              disabled={mergeCandidatesLoading || !mergeSecondaryId}
              id="gov-merge-reason"
              maxLength={1000}
              onChange={(event) => setMergeReason(event.target.value)}
              placeholder="Explain why this matter is a duplicate of the primary record"
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
        <section className="cancel-dialog recovery-dialog" aria-labelledby="governance-unmerge-dialog-title" aria-modal="true" role="dialog">
          <span className="cancel-dialog-icon recovery-dialog-icon"><GitMerge size={23} /></span>
          <div><p className="workspace-kicker">Step-up protected</p><h2 id="governance-unmerge-dialog-title">Restore merged matter</h2><p>The linked matter returns to formal review with a fresh SLA cycle. The server checks the recovery window and fresh step-up authentication before it records this action.</p></div>
          <form onSubmit={submitUnmerge}>
            {unmergeSecondaryLoading ? <p className="internal-notes-loading"><LoaderCircle className="spin" size={15} /> Loading linked matter</p> : unmergeSecondaryTicket && <p className="recovery-linked-ticket">Linked matter: <strong>{unmergeSecondaryTicket.ticket_number}</strong></p>}
            <label htmlFor="governance-unmerge-reason">Audit reason</label>
            <textarea autoFocus disabled={unmergeSecondaryLoading || !unmergeSecondaryTicket} id="governance-unmerge-reason" maxLength={1000} onChange={(event) => setUnmergeReason(event.target.value)} placeholder="Explain why these matters must be handled separately" rows={4} value={unmergeReason} />
            {unmergeError && <p className="cancel-error" role="alert">{unmergeError}</p>}
            <div className="cancel-dialog-actions"><button type="button" disabled={submittingUnmerge} onClick={() => closeUnmergeDialog()}>Keep merged</button><button className="recovery-command" type="submit" disabled={unmergeSecondaryLoading || !unmergeSecondaryTicket || submittingUnmerge || !unmergeReason.trim()}>{submittingUnmerge ? <LoaderCircle className="spin" size={15} /> : <GitMerge size={15} />}{submittingUnmerge ? "Restoring" : "Confirm restore"}</button></div>
          </form>
        </section>
      </div>}
    </div>
  );
}