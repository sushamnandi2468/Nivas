"use client";

import {
  CheckCircle2,
  ChevronRight,
  ClipboardCheck,
  FileText,
  MessageSquareMore,
  RefreshCw,
  ShieldAlert,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import {
  listTickets,
  Ticket,
} from "@/lib/nivasops-api";
import { useWorkspaceSession } from "../session-context";

const ACTIVE_STATUSES = new Set(["SUBMITTED", "UNDER_REVIEW", "IN_DISCUSSION", "ACTION_TAKEN"]);

function statusLabel(status: string) {
  return status.replaceAll("_", " ");
}

export default function GovernanceOperationsPage() {
  const { session } = useWorkspaceSession();
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");

  const governanceTickets = tickets.filter((ticket) => ticket.workflow_type === "GOVERNANCE");
  const activeTickets = governanceTickets.filter((ticket) => ACTIVE_STATUSES.has(ticket.status));

  useEffect(() => {
    if (!session) return;
    let current = true;
    void listTickets(session)
      .then((result) => {
        if (current) setTickets(result);
      })
      .catch((reason: unknown) => {
        if (current) setError(reason instanceof Error ? reason.message : "The governance queue could not be loaded.");
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => { current = false; };
  }, [session]);

  async function refreshQueue() {
    if (!session) return;
    setRefreshing(true);
    setError("");
    try {
      setTickets(await listTickets(session));
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "The governance queue could not be loaded.");
    } finally {
      setRefreshing(false);
    }
  }

  const reviewedCount = activeTickets.filter((ticket) => ticket.status === "UNDER_REVIEW").length;
  const discussionCount = activeTickets.filter((ticket) => ticket.status === "IN_DISCUSSION").length;
  const actionCount = activeTickets.filter((ticket) => ticket.status === "ACTION_TAKEN").length;

  return (
    <div className="operations-page page-enter">
      <section className="operations-header">
        <div>
          <p className="workspace-kicker">Facility operations</p>
          <h1>Governance queue</h1>
          <p>Review civic matters, open a resident discussion, and record the approved operational action.</p>
        </div>
        <button className="icon-command" type="button" title="Refresh governance queue" aria-label="Refresh governance queue" disabled={refreshing} onClick={() => void refreshQueue()}>
          <RefreshCw className={refreshing ? "spin" : ""} size={17} />
        </button>
      </section>

      <section className="metric-strip operations-metrics" aria-label="Governance queue overview">
        <div><span className="metric-icon teal"><ClipboardCheck size={18} /></span><p><strong>{activeTickets.length}</strong><span>Active matters</span></p></div>
        <div><span className="metric-icon amber"><ShieldAlert size={18} /></span><p><strong>{reviewedCount}</strong><span>Under review</span></p></div>
        <div><span className="metric-icon coral"><MessageSquareMore size={18} /></span><p><strong>{discussionCount}</strong><span>In discussion</span></p></div>
        <div><span className="metric-icon green"><CheckCircle2 size={18} /></span><p><strong>{actionCount}</strong><span>Action recorded</span></p></div>
      </section>

      {loading ? <div className="ticket-list governance-queue" aria-label="Loading governance matters">{[0, 1, 2].map((item) => <div className="ticket-row skeleton" key={item} />)}</div> : error ? (
        <section className="empty-state error-state"><FileText size={25} /><h2>Governance queue unavailable</h2><p>{error}</p></section>
      ) : activeTickets.length === 0 ? (
        <section className="empty-state"><ClipboardCheck size={27} /><h2>No active civic matters</h2><p>Submitted governance tickets will appear here for review.</p></section>
      ) : (
        <section className="operations-grid">
          <div className="governance-queue" role="list" aria-label="Active governance matters">
            {activeTickets.map((ticket) => (
              <Link className="governance-row" key={ticket.id} href={`/app/operations/governance/${ticket.id}`}>
                <span className={`priority-marker priority-${ticket.priority.toLowerCase()}`}>{ticket.priority}</span>
                <span className="governance-row-copy"><small>{ticket.ticket_number}</small><strong>{ticket.title}</strong><span>{ticket.category}</span></span>
                <span className={`status-pill status-${ticket.status.toLowerCase()}`}>{statusLabel(ticket.status)}</span>
                <ChevronRight size={18} />
              </Link>
            ))}
          </div>
          <aside className="governance-detail governance-queue-guide" aria-label="Governance matter workspace">
            <ClipboardCheck size={20} />
            <h2>Open a civic matter</h2>
            <p>Review the report, restricted staff notes, and the supported governance actions in its dedicated workspace.</p>
          </aside>
        </section>
      )}
    </div>
  );
}