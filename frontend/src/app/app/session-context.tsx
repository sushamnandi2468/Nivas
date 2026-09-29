"use client";

import {
  createContext,
  FormEvent,
  ReactNode,
  useContext,
  useState,
  useSyncExternalStore,
} from "react";
import { ArrowRight, KeyRound, Server, ShieldCheck } from "lucide-react";

import type { WorkspacePersona, WorkspaceSession } from "@/lib/nivasops-api";

const STORAGE_KEY = "nivasops.workspace-session";
const SESSION_EVENT = "nivasops-session-change";
let cachedValue: string | null | undefined;
let cachedSession: WorkspaceSession | null = null;

function readSession() {
  if (typeof window === "undefined") return null;
  const stored = window.sessionStorage.getItem(STORAGE_KEY);
  if (stored === cachedValue) return cachedSession;
  cachedValue = stored;
  try {
    cachedSession = stored ? (JSON.parse(stored) as WorkspaceSession) : null;
  } catch {
    cachedSession = null;
  }
  return cachedSession;
}

function subscribe(listener: () => void) {
  window.addEventListener("storage", listener);
  window.addEventListener(SESSION_EVENT, listener);
  return () => {
    window.removeEventListener("storage", listener);
    window.removeEventListener(SESSION_EVENT, listener);
  };
}

function writeSession(session: WorkspaceSession | null) {
  if (session) {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session));
  } else {
    window.sessionStorage.removeItem(STORAGE_KEY);
  }
  cachedValue = undefined;
  window.dispatchEvent(new Event(SESSION_EVENT));
}

type SessionContextValue = {
  session: WorkspaceSession | null;
  connect: (session: WorkspaceSession) => void;
  disconnect: () => void;
};

const SessionContext = createContext<SessionContextValue | null>(null);

export function WorkspaceSessionProvider({ children }: { children: ReactNode }) {
  const session = useSyncExternalStore(subscribe, readSession, () => null);
  return (
    <SessionContext.Provider
      value={{ session, connect: writeSession, disconnect: () => writeSession(null) }}
    >
      {children}
    </SessionContext.Provider>
  );
}

export function useWorkspaceSession() {
  const context = useContext(SessionContext);
  if (!context) throw new Error("WorkspaceSessionProvider is required.");
  return context;
}

export function SessionGate() {
  const { connect } = useWorkspaceSession();
  const [apiBaseUrl, setApiBaseUrl] = useState(
    process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000",
  );
  const [societyId, setSocietyId] = useState("");
  const [accessToken, setAccessToken] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [workspacePersona, setWorkspacePersona] = useState<WorkspacePersona>("RESIDENT");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    connect({
      apiBaseUrl: apiBaseUrl.trim(),
      societyId: societyId.trim(),
      accessToken: accessToken.trim(),
      displayName: displayName.trim() || (workspacePersona === "RESIDENT" ? "Resident" : "Facility manager"),
      workspacePersona,
    });
  }

  return (
    <main className="session-gate">
      <section className="session-visual" aria-label="NivasOps operations workspace">
        <div className="session-brand">
          <span className="brand-mark"><ShieldCheck size={21} /></span>
          <strong>NivasOps</strong>
        </div>
        <div>
          <p className="workspace-kicker">Operations workspace</p>
          <h1>One clear view for resident and facility operations.</h1>
        </div>
      </section>
      <section className="session-panel">
        <form onSubmit={handleSubmit}>
          <p className="workspace-kicker">Secure session</p>
          <h2>Connect your workspace</h2>
          <label>
            Display name
            <input
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              placeholder="Ananya Roy"
            />
          </label>
          <label>
            Workspace
            <select value={workspacePersona} onChange={(event) => setWorkspacePersona(event.target.value as WorkspacePersona)}>
              <option value="RESIDENT">Resident desk</option>
              <option value="FACILITY_MANAGER">Facility manager desk</option>
            </select>
          </label>
          <label>
            API address
            <span className="session-input"><Server size={17} /><input required value={apiBaseUrl} onChange={(event) => setApiBaseUrl(event.target.value)} /></span>
          </label>
          <label>
            Society ID
            <input required value={societyId} onChange={(event) => setSocietyId(event.target.value)} placeholder="Society UUID" />
          </label>
          <label>
            Access token
            <span className="session-input"><KeyRound size={17} /><input required type="password" value={accessToken} onChange={(event) => setAccessToken(event.target.value)} autoComplete="off" /></span>
          </label>
          <button className="primary-command" type="submit">Open workspace <ArrowRight size={18} /></button>
          <p className="session-security"><ShieldCheck size={15} /> Session credentials stay in this browser tab.</p>
        </form>
      </section>
    </main>
  );
}