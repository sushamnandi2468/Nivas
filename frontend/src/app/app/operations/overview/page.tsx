"use client";

import Link from "next/link";
import {
  ArrowUpRight,
  ClipboardCheck,
  FileText,
  Inbox,
  RefreshCw,
  ShieldAlert,
} from "lucide-react";
import { useEffect, useState } from "react";

import { listTickets, Ticket } from "@/lib/nivasops-api";
import { useWorkspaceSession } from "../../session-context";

function statusLabel(status: string) {
  return status.replaceAll("_", " ");
}

function ticketDestination(ticket: Ticket) {
  return ticket.workflow_type === "SERVICE"
    ? `/app/operations/service/${ticket.id}`
    : `/app/operations/governance/${ticket.id}`;
}

export default function OperationsOverviewPage() {
  const { session } = useWorkspaceSession();
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");

  async function loadTickets() {
    if (!session) return;
    setError("");
    try {
      setTickets(await listTickets(session));
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "The operations overview could not be loaded.");
    }
  }

  useEffect(() => {
    if (!session) return;
    let current = true;
    void listTickets(session)
      .then((result) => {
        if (current) setTickets(result);
      })
      .catch((reason: unknown) => {
        if (current) setError(reason instanceof Error ? reason.message : "The operations overview could not be loaded.");
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => { current = false; };
  }, [session]);

  async function refreshOverview() {
    setRefreshing(true);
    await loadTickets();
    setRefreshing(false);
  }

  const submittedServiceTickets = tickets.filter((ticket) => (
    ticket.workflow_type === "SERVICE" && ticket.status === "SUBMITTED"
  ));
  const priorityServiceTickets = submittedServiceTickets.filter((ticket) => (
    ticket.priority === "P1" || ticket.priority === "P2"
  ));
  const activeGovernanceTickets = tickets.filter((ticket) => (
    ticket.workflow_type === "GOVERNANCE" && ticket.status !== "CANCELLED"
  ));
  const recentTickets = tickets.slice(0, 6);

  return (
    <div className="operations-page page-enter">
      <section className="operations-header">
        <div>
          <p className="workspace-kicker">Facility operations</p>
          <h1>Operations overview</h1>
          <p>See the currently visible workload, then move into the service or governance workspace to act on it.</p>
        </div>
        <button className="icon-command" type="button" title="Refresh operations overview" aria-label="Refresh operations overview" disabled={refreshing} onClick={() => void refreshOverview()}>
          <RefreshCw className={refreshing ? "spin" : ""} size={17} />
        </button>
      </section>

      <section className="metric-strip operations-metrics" aria-label="Operations overview metrics">
        <div><span className="metric-icon teal"><Inbox size={18} /></span><p><strong>{submittedServiceTickets.length}</strong><span>Submitted service requests</span></p></div>
        <div><span className="metric-icon coral"><ShieldAlert size={18} /></span><p><strong>{priorityServiceTickets.length}</strong><span>Priority P1-P2 service</span></p></div>
        <div><span className="metric-icon amber"><ClipboardCheck size={18} /></span><p><strong>{activeGovernanceTickets.length}</strong><span>Active governance matters</span></p></div>
        <div><span className="metric-icon green"><FileText size={18} /></span><p><strong>{tickets.length}</strong><span>All visible tickets</span></p></div>
      </section>

      {loading ? <div className="ticket-list governance-queue" aria-label="Loading operations overview">{[0, 1, 2].map((item) => <div className="ticket-row skeleton" key={item} />)}</div> : error ? (
        <section className="empty-state error-state"><FileText size={25} /><h2>Operations overview unavailable</h2><p>{error}</p></section>
      ) : (
        <section className="operations-overview-grid">
          <article className="operations-overview-panel">
            <p className="workspace-kicker">Service desk</p>
            <h2>Submitted requests</h2>
            <p>Reply to residents and capture private operational context.</p>
            <Link className="operations-route-link" href="/app/operations/service">Open service inbox <ArrowUpRight size={16} /></Link>
          </article>
          <article className="operations-overview-panel">
            <p className="workspace-kicker">Governance desk</p>
            <h2>Civic matters</h2>
            <p>Review, discuss, record action, and retain private committee context.</p>
            <Link className="operations-route-link" href="/app/operations">Open governance queue <ArrowUpRight size={16} /></Link>
          </article>
          <section className="operations-recent-panel" aria-labelledby="recent-tickets-heading">
            <div className="operations-recent-heading">
              <div><p className="workspace-kicker">Latest activity</p><h2 id="recent-tickets-heading">Recently created tickets</h2></div>
              <FileText size={19} />
            </div>
            {recentTickets.length === 0 ? <p className="quiet-copy">No tickets are visible for this society yet.</p> : (
              <div className="governance-queue" role="list" aria-label="Recently created tickets">
                {recentTickets.map((ticket) => (
                  <Link className="governance-row" key={ticket.id} href={ticketDestination(ticket)}>
                    <span className={`priority-marker priority-${ticket.priority.toLowerCase()}`}>{ticket.priority}</span>
                    <span className="governance-row-copy"><small>{ticket.workflow_type === "SERVICE" ? "Service" : "Governance"} · {ticket.ticket_number}</small><strong>{ticket.title}</strong><span>{ticket.category}</span></span>
                    <span className={`status-pill status-${ticket.status.toLowerCase()}`}>{statusLabel(ticket.status)}</span>
                    <ArrowUpRight size={17} />
                  </Link>
                ))}
              </div>
            )}
          </section>
        </section>
      )}
    </div>
  );
}