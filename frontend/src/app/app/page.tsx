"use client";

import Link from "next/link";
import {
  ArrowRight,
  CheckCircle2,
  CirclePlus,
  Clock3,
  FileText,
  RefreshCw,
  ShieldCheck,
  TicketCheck,
} from "lucide-react";
import { useEffect, useState } from "react";

import { listTickets, Ticket } from "@/lib/nivasops-api";
import { useWorkspaceSession } from "./session-context";

const TERMINAL_STATUSES = new Set(["RESOLVED", "CLOSED", "CANCELLED", "MERGED"]);

function ticketHref(ticket: Ticket) {
  return `/app/tickets/${ticket.workflow_type.toLowerCase()}/${ticket.id}`;
}

function StatusPill({ status }: { status: string }) {
  return <span className={`status-pill status-${status.toLowerCase()}`}>{status.replaceAll("_", " ")}</span>;
}

export default function ResidentHome() {
  const { session } = useWorkspaceSession();
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) return;
    let current = true;
    listTickets(session)
      .then((result) => {
        if (current) setTickets(result);
      })
      .catch((reason: unknown) => {
        if (current) setError(reason instanceof Error ? reason.message : "Tickets could not be loaded.");
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => { current = false; };
  }, [session]);

  const activeTickets = tickets.filter((ticket) => !TERMINAL_STATUSES.has(ticket.status));
  const resolvedTickets = tickets.filter((ticket) => TERMINAL_STATUSES.has(ticket.status));
  const urgentTickets = activeTickets.filter((ticket) => ticket.priority === "P1");

  return (
    <div className="resident-home page-enter">
      <section className="resident-banner">
        <div>
          <p className="workspace-kicker"><span className="operations-dot" /> Society services connected</p>
          <h1>Welcome home, {session?.residentName ?? "Resident"}</h1>
          <p>Track service requests and civic matters from one place.</p>
        </div>
        <Link className="primary-command" href="/app/new"><CirclePlus size={19} /> Raise new request</Link>
      </section>

      <section className="metric-strip" aria-label="Request overview">
        <div><span className="metric-icon teal"><TicketCheck size={18} /></span><p><strong>{activeTickets.length}</strong><span>Active requests</span></p></div>
        <div><span className="metric-icon amber"><Clock3 size={18} /></span><p><strong>{tickets.filter((ticket) => ticket.status === "DRAFT").length}</strong><span>Drafts</span></p></div>
        <div><span className="metric-icon coral"><ShieldCheck size={18} /></span><p><strong>{urgentTickets.length}</strong><span>Critical priority</span></p></div>
        <div><span className="metric-icon green"><CheckCircle2 size={18} /></span><p><strong>{resolvedTickets.length}</strong><span>Completed</span></p></div>
      </section>

      <section className="content-section">
        <div className="section-heading">
          <div><p className="workspace-kicker">Live queue</p><h2>Active requests</h2></div>
          <button className="icon-command" type="button" title="Refresh requests" aria-label="Refresh requests" onClick={() => window.location.reload()}><RefreshCw size={17} /></button>
        </div>

        {loading ? (
          <div className="ticket-list" aria-label="Loading requests">
            {[0, 1, 2].map((item) => <div className="ticket-row skeleton" key={item} />)}
          </div>
        ) : error ? (
          <div className="empty-state error-state"><FileText size={25} /><h3>Requests unavailable</h3><p>{error}</p></div>
        ) : activeTickets.length === 0 ? (
          <div className="empty-state"><TicketCheck size={26} /><h3>No active requests</h3><p>New service and civic requests will appear here.</p><Link href="/app/new">Raise a request <ArrowRight size={16} /></Link></div>
        ) : (
          <div className="ticket-list">
            {activeTickets.map((ticket) => (
              <Link className="ticket-row" href={ticketHref(ticket)} key={ticket.id}>
                <span className={`priority-marker priority-${ticket.priority.toLowerCase()}`}>{ticket.priority}</span>
                <div className="ticket-primary">
                  <span>{ticket.workflow_type === "SERVICE" ? "Service request" : "Civic matter"}</span>
                  <strong>{ticket.title}</strong>
                  <small>{ticket.ticket_number || `Draft · ${ticket.id.slice(0, 8)}`}</small>
                </div>
                <StatusPill status={ticket.status} />
                <ArrowRight className="row-arrow" size={18} />
              </Link>
            ))}
          </div>
        )}
      </section>

      <section className="home-lower-grid">
        <div className="plain-panel">
          <div className="section-heading"><div><p className="workspace-kicker">History</p><h2>Recently completed</h2></div></div>
          {resolvedTickets.length ? resolvedTickets.slice(0, 3).map((ticket) => (
            <Link className="compact-ticket" href={ticketHref(ticket)} key={ticket.id}><CheckCircle2 size={17} /><span><strong>{ticket.title}</strong><small>{ticket.ticket_number}</small></span><ArrowRight size={16} /></Link>
          )) : <p className="panel-empty">Completed requests will be retained here.</p>}
        </div>
        <div className="plain-panel bulletin-panel">
          <div className="section-heading"><div><p className="workspace-kicker">Society desk</p><h2>Operations bulletin</h2></div></div>
          <div className="bulletin-item"><span>API</span><p><strong>Resident helpdesk online</strong><small>Ticket list, drafts, and details are available.</small></p></div>
          <div className="bulletin-item muted"><span>SLA</span><p><strong>Submission calendar pending</strong><small>Draft requests remain available until calendar activation.</small></p></div>
        </div>
      </section>
    </div>
  );
}