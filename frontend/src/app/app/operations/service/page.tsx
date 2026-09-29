"use client";

import {
  ChevronRight,
  FileText,
  Filter,
  Inbox,
  LoaderCircle,
  LockKeyhole,
  MessageSquare,
  RefreshCw,
  Send,
  ShieldAlert,
} from "lucide-react";
import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

import {
  createInternalTicketComment,
  createTicketComment,
  listInternalTicketComments,
  listTicketComments,
  listTickets,
  Ticket,
  TicketComment,
} from "@/lib/nivasops-api";
import { useWorkspaceSession } from "../../session-context";

type ServiceCommentState = {
  ticketId: string;
  publicComments: TicketComment[];
  internalComments: TicketComment[];
  publicError: string;
  internalError: string;
};

function statusLabel(status: string) {
  return status.replaceAll("_", " ");
}

function formatCommentDate(value: string) {
  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function commentAuthor(comment: TicketComment) {
  if (comment.is_authored_by_requester) return "You";
  return comment.author_persona === "resident" ? "Resident" : "Society operations";
}

export default function ServiceInboxPage() {
  const { session } = useWorkspaceSession();
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [commentState, setCommentState] = useState<ServiceCommentState | null>(null);
  const [publicCommentBody, setPublicCommentBody] = useState("");
  const [internalCommentBody, setInternalCommentBody] = useState("");
  const [postingPublicComment, setPostingPublicComment] = useState(false);
  const [postingInternalComment, setPostingInternalComment] = useState(false);
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [priorityFilter, setPriorityFilter] = useState("ALL");
  const [query, setQuery] = useState("");

  const serviceTickets = tickets.filter((ticket) => ticket.workflow_type === "SERVICE");
  const inboxTickets = serviceTickets.filter((ticket) => ticket.status !== "DRAFT");
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const filtersActive = statusFilter !== "ALL" || priorityFilter !== "ALL" || Boolean(normalizedQuery);
  const filteredTickets = inboxTickets.filter((ticket) =>
    (statusFilter === "ALL" || ticket.status === statusFilter)
    && (priorityFilter === "ALL" || ticket.priority === priorityFilter)
    && (!normalizedQuery
      || ticket.ticket_number.toLocaleLowerCase().includes(normalizedQuery)
      || ticket.title.toLocaleLowerCase().includes(normalizedQuery)
      || ticket.description.toLocaleLowerCase().includes(normalizedQuery)),
  );
  const selectedTicket = filteredTickets[0] ?? null;
  const selectedCommentState = selectedTicket && commentState?.ticketId === selectedTicket.id
    ? commentState
    : null;
  const publicComments = selectedCommentState?.publicComments ?? [];
  const internalComments = selectedCommentState?.internalComments ?? [];
  const publicCommentError = selectedCommentState?.publicError ?? "";
  const internalCommentError = selectedCommentState?.internalError ?? "";
  const commentsLoading = Boolean(selectedTicket && !selectedCommentState);

  useEffect(() => {
    if (!session) return;
    let current = true;
    void listTickets(session)
      .then((result) => {
        if (current) setTickets(result);
      })
      .catch((reason: unknown) => {
        if (current) setError(reason instanceof Error ? reason.message : "The service inbox could not be loaded.");
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => { current = false; };
  }, [session]);

  useEffect(() => {
    if (!session || !selectedTicket) return;
    let current = true;
    void Promise.allSettled([
      listTicketComments(session, "SERVICE", selectedTicket.id),
      listInternalTicketComments(session, "SERVICE", selectedTicket.id),
    ]).then(([publicResult, internalResult]) => {
      if (!current) return;
      setCommentState({
        ticketId: selectedTicket.id,
        publicComments: publicResult.status === "fulfilled" ? publicResult.value : [],
        internalComments: internalResult.status === "fulfilled" ? internalResult.value : [],
        publicError: publicResult.status === "rejected"
          ? publicResult.reason instanceof Error ? publicResult.reason.message : "Resident conversation could not be loaded."
          : "",
        internalError: internalResult.status === "rejected"
          ? internalResult.reason instanceof Error ? internalResult.reason.message : "Private notes could not be loaded."
          : "",
      });
    });
    return () => { current = false; };
  }, [selectedTicket, session]);

  async function refreshInbox() {
    if (!session) return;
    setRefreshing(true);
    setError("");
    try {
      setTickets(await listTickets(session));
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "The service inbox could not be loaded.");
    } finally {
      setRefreshing(false);
    }
  }

  function clearFilters() {
    setStatusFilter("ALL");
    setPriorityFilter("ALL");
    setQuery("");
  }

  async function postPublicComment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const body = publicCommentBody.trim();
    if (!session || !selectedTicket || !body) return;
    setPostingPublicComment(true);
    try {
      const comment = await createTicketComment(session, selectedTicket, body);
      setCommentState((current) => ({
        ticketId: selectedTicket.id,
        publicComments: current?.ticketId === selectedTicket.id ? [...current.publicComments, comment] : [comment],
        internalComments: current?.ticketId === selectedTicket.id ? current.internalComments : [],
        publicError: "",
        internalError: current?.ticketId === selectedTicket.id ? current.internalError : "",
      }));
      setPublicCommentBody("");
    } catch (reason: unknown) {
      setCommentState((current) => ({
        ticketId: selectedTicket.id,
        publicComments: current?.ticketId === selectedTicket.id ? current.publicComments : [],
        internalComments: current?.ticketId === selectedTicket.id ? current.internalComments : [],
        publicError: reason instanceof Error ? reason.message : "Resident reply could not be posted.",
        internalError: current?.ticketId === selectedTicket.id ? current.internalError : "",
      }));
    } finally {
      setPostingPublicComment(false);
    }
  }

  async function postInternalComment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const body = internalCommentBody.trim();
    if (!session || !selectedTicket || !body) return;
    setPostingInternalComment(true);
    try {
      const comment = await createInternalTicketComment(session, selectedTicket, body);
      setCommentState((current) => ({
        ticketId: selectedTicket.id,
        publicComments: current?.ticketId === selectedTicket.id ? current.publicComments : [],
        internalComments: current?.ticketId === selectedTicket.id ? [...current.internalComments, comment] : [comment],
        publicError: current?.ticketId === selectedTicket.id ? current.publicError : "",
        internalError: "",
      }));
      setInternalCommentBody("");
    } catch (reason: unknown) {
      setCommentState((current) => ({
        ticketId: selectedTicket.id,
        publicComments: current?.ticketId === selectedTicket.id ? current.publicComments : [],
        internalComments: current?.ticketId === selectedTicket.id ? current.internalComments : [],
        publicError: current?.ticketId === selectedTicket.id ? current.publicError : "",
        internalError: reason instanceof Error ? reason.message : "Private note could not be posted.",
      }));
    } finally {
      setPostingInternalComment(false);
    }
  }

  const urgentTickets = inboxTickets.filter((ticket) => ticket.priority === "P1" || ticket.priority === "P2").length;
  const residentReplies = publicComments.filter((comment) => comment.author_persona === "resident").length;

  return (
    <div className="operations-page page-enter">
      <section className="operations-header">
        <div>
          <p className="workspace-kicker">Facility operations</p>
          <h1>Service inbox</h1>
          <p>Review submitted and active service requests, keep residents informed, and capture private operational context for staff.</p>
        </div>
        <button className="icon-command" type="button" title="Refresh service inbox" aria-label="Refresh service inbox" disabled={refreshing} onClick={() => void refreshInbox()}>
          <RefreshCw className={refreshing ? "spin" : ""} size={17} />
        </button>
      </section>

      <section className="metric-strip operations-metrics" aria-label="Service inbox overview">
        <div><span className="metric-icon teal"><Inbox size={18} /></span><p><strong>{inboxTickets.length}</strong><span>Submitted and active</span></p></div>
        <div><span className="metric-icon coral"><ShieldAlert size={18} /></span><p><strong>{urgentTickets}</strong><span>Priority P1-P2</span></p></div>
        <div><span className="metric-icon amber"><MessageSquare size={18} /></span><p><strong>{residentReplies}</strong><span>Resident messages</span></p></div>
        <div><span className="metric-icon green"><FileText size={18} /></span><p><strong>{serviceTickets.length}</strong><span>All visible tickets</span></p></div>
      </section>

      {!loading && !error && inboxTickets.length > 0 && <section className="service-filter-bar" aria-label="Filter service requests">
        <div className="service-filter-heading"><Filter size={16} /><span>Filter requests</span></div>
        <label><span>Status</span><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="ALL">All statuses</option>{Array.from(new Set(inboxTickets.map((ticket) => ticket.status))).sort().map((status) => <option key={status} value={status}>{statusLabel(status)}</option>)}</select></label>
        <label><span>Priority</span><select value={priorityFilter} onChange={(event) => setPriorityFilter(event.target.value)}><option value="ALL">All priorities</option>{["P1", "P2", "P3", "P4"].map((priority) => <option key={priority} value={priority}>{priority}</option>)}</select></label>
        <label className="service-filter-search"><span>Search</span><input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Number, title, or description" /></label>
        <div className="service-filter-summary"><p>{filteredTickets.length} of {inboxTickets.length} requests</p>{filtersActive && <button type="button" onClick={clearFilters}>Clear filters</button>}</div>
      </section>}

      {loading ? <div className="ticket-list governance-queue" aria-label="Loading service requests">{[0, 1, 2].map((item) => <div className="ticket-row skeleton" key={item} />)}</div> : error ? (
        <section className="empty-state error-state"><FileText size={25} /><h2>Service inbox unavailable</h2><p>{error}</p></section>
      ) : inboxTickets.length === 0 ? (
        <section className="empty-state"><Inbox size={27} /><h2>No service requests to review</h2><p>Submitted service tickets will appear here for staff review.</p></section>
      ) : filteredTickets.length === 0 ? (
        <section className="empty-state"><Filter size={27} /><h2>No requests match these filters</h2><p>Clear or adjust a filter to review the available service work.</p></section>
      ) : (
        <section className="operations-grid">
          <div className="governance-queue" role="list" aria-label="Submitted and active service requests">
            {filteredTickets.map((ticket) => (
              <Link className={`governance-row ${selectedTicket?.id === ticket.id ? "selected" : ""}`} key={ticket.id} href={`/app/operations/service/${ticket.id}`}>
                <span className={`priority-marker priority-${ticket.priority.toLowerCase()}`}>{ticket.priority}</span>
                <span className="governance-row-copy"><small>{ticket.ticket_number}</small><strong>{ticket.title}</strong><span>{ticket.submitted_at ? `Submitted ${new Intl.DateTimeFormat("en-IN", { dateStyle: "medium" }).format(new Date(ticket.submitted_at))}` : "Submitted"}</span></span>
                <span className={`status-pill status-${ticket.status.toLowerCase()}`}>{statusLabel(ticket.status)}</span>
                <ChevronRight size={18} />
              </Link>
            ))}
          </div>

          {selectedTicket && <aside className="governance-detail" aria-label="Selected service request">
            <div className="governance-detail-heading"><span className={`status-pill status-${selectedTicket.status.toLowerCase()}`}>{statusLabel(selectedTicket.status)}</span><small>{selectedTicket.ticket_number}</small></div>
            <h2>{selectedTicket.title}</h2>
            <p>{selectedTicket.description}</p>
            <dl><div><dt>Priority</dt><dd>{selectedTicket.priority}</dd></div><div><dt>Current version</dt><dd>{selectedTicket.state_version}</dd></div></dl>

            <section className="internal-notes public-conversation" aria-label="Resident conversation">
              <div className="internal-notes-heading"><div><p className="workspace-kicker">Resident-visible</p><h3>Conversation</h3></div><MessageSquare size={16} /></div>
              {commentsLoading ? <p className="internal-notes-loading"><LoaderCircle className="spin" size={15} /> Loading conversation</p> : publicCommentError ? <p className="conversation-error" role="alert">{publicCommentError}</p> : publicComments.length === 0 ? <p className="internal-notes-empty">No resident messages yet.</p> : (
                <div className="conversation-thread internal-notes-thread" aria-label="Resident conversation">
                  {publicComments.map((comment) => (
                    <article className={comment.is_authored_by_requester ? "own" : ""} key={comment.id}>
                      <header><strong>{commentAuthor(comment)}</strong><time dateTime={comment.created_at}>{formatCommentDate(comment.created_at)}</time></header>
                      <p>{comment.body}</p>
                    </article>
                  ))}
                </div>
              )}
              <form className="message-composer" onSubmit={postPublicComment}>
                <label className="sr-only" htmlFor="service-public-reply">Reply to the resident</label>
                <textarea id="service-public-reply" maxLength={4000} onChange={(event) => setPublicCommentBody(event.target.value)} placeholder="Reply to the resident" rows={2} value={publicCommentBody} />
                <button type="submit" disabled={postingPublicComment || !publicCommentBody.trim()} aria-label="Post resident reply" title="Post resident reply">{postingPublicComment ? <LoaderCircle className="spin" size={17} /> : <Send size={17} />}</button>
              </form>
            </section>

            <section className="internal-notes" aria-label="Private service notes">
              <div className="internal-notes-heading"><div><p className="workspace-kicker">Private workspace</p><h3>Internal notes</h3></div><LockKeyhole size={16} /></div>
              <p className="internal-notes-description">Visible only to authorized staff.</p>
              {commentsLoading ? <p className="internal-notes-loading"><LoaderCircle className="spin" size={15} /> Loading private notes</p> : internalCommentError ? <p className="conversation-error" role="alert">{internalCommentError}</p> : internalComments.length === 0 ? <p className="internal-notes-empty">No private notes yet.</p> : (
                <div className="conversation-thread internal-notes-thread" aria-label="Private service notes">
                  {internalComments.map((comment) => (
                    <article className={comment.is_authored_by_requester ? "own" : ""} key={comment.id}>
                      <header><strong>{commentAuthor(comment)}</strong><time dateTime={comment.created_at}>{formatCommentDate(comment.created_at)}</time></header>
                      <p>{comment.body}</p>
                    </article>
                  ))}
                </div>
              )}
              <form className="message-composer" onSubmit={postInternalComment}>
                <label className="sr-only" htmlFor="service-internal-note">Add a private note</label>
                <textarea id="service-internal-note" maxLength={4000} onChange={(event) => setInternalCommentBody(event.target.value)} placeholder="Add a private operational note" rows={2} value={internalCommentBody} />
                <button type="submit" disabled={postingInternalComment || !internalCommentBody.trim()} aria-label="Post private note" title="Post private note">{postingInternalComment ? <LoaderCircle className="spin" size={17} /> : <Send size={17} />}</button>
              </form>
            </section>
          </aside>}
        </section>
      )}
    </div>
  );
}
