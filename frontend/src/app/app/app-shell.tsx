"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Bell,
  Building2,
  CirclePlus,
  ClipboardCheck,
  House,
  Inbox,
  LayoutDashboard,
  LogOut,
  MapPinned,
  Menu,
  ShieldCheck,
  TicketCheck,
} from "lucide-react";
import { ReactNode, useEffect, useState } from "react";

import { isFacilityManagerSession, workspaceDisplayName } from "@/lib/nivasops-api";

import { useWorkspaceSession } from "./session-context";

const residentNavigation = [
  { href: "/app", label: "Home", icon: House },
  { href: "/app/new", label: "New request", icon: CirclePlus },
];

const facilityManagerNavigation = [
  { href: "/app/operations/overview", label: "Overview", icon: LayoutDashboard },
  { href: "/app/operations", label: "Governance queue", icon: ClipboardCheck },
  { href: "/app/operations/service", label: "Service inbox", icon: Inbox },
  { href: "/app/operations/vendors", label: "Vendors", icon: Building2 },
  { href: "/app/operations/directory", label: "Directory", icon: MapPinned },
];

export function AppShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { session, disconnect } = useWorkspaceSession();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    if (!session) {
      router.replace("/");
    }
  }, [session, router]);

  useEffect(() => {
    if (typeof window !== "undefined" && !(window as unknown as { __NIVAS_INIT__?: boolean }).__NIVAS_INIT__) {
      (window as unknown as { __NIVAS_INIT__?: boolean }).__NIVAS_INIT__ = true;
      console.info(
        "%c \u2728 NivasOps %c| Multi-Tenant Residential Operations Platform\n%cLicense: AGPL-3.0 \u2022 Author: Susham Nandi\nSource: https://github.com/sushamnandi2468/Nivas",
        "color: #4F46E5; font-weight: bold; font-size: 13px;",
        "color: #06B6D4; font-weight: bold;",
        "color: #64748B; font-size: 11px;"
      );
    }
  }, []);

  if (!session) {
    return (
      <div
        className="workspace-loading-shell"
        style={{
          minHeight: "100svh",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          background: "#0a1010",
          color: "#a9b5b0",
          gap: "14px",
        }}
      >
        <ShieldCheck size={36} color="#45d6bd" />
        <p style={{ margin: 0, fontSize: "0.95rem" }}>Redirecting to secure login...</p>
      </div>
    );
  }

  const facilityManager = isFacilityManagerSession(session);
  const navigation = facilityManager ? facilityManagerNavigation : residentNavigation;
  const workspaceLabel = facilityManager ? "Facility manager desk" : "Resident workspace";
  const displayName = workspaceDisplayName(session);

  return (
    <div className="workspace-shell">
      <aside className={`workspace-sidebar ${mobileMenuOpen ? "open" : ""}`}>
        <Link className="workspace-brand" href="/app" onClick={() => setMobileMenuOpen(false)}>
          <span className="brand-mark"><ShieldCheck size={20} /></span>
          <span><strong>NivasOps</strong><small>{facilityManager ? "Facility desk" : "Resident desk"}</small></span>
        </Link>
        <nav aria-label={workspaceLabel}>
          {navigation.map(({ href, label, icon: Icon }) => (
            <Link
              key={href}
              className={pathname === href ? "active" : ""}
              href={href}
              onClick={() => setMobileMenuOpen(false)}
            >
              <Icon size={18} /> {label}
            </Link>
          ))}
          {!facilityManager && <>
            <span className="nav-section">Requests</span>
            <Link
              className={pathname.includes("/tickets/") ? "active" : ""}
              href="/app"
              onClick={() => setMobileMenuOpen(false)}
            >
              <TicketCheck size={18} /> My tickets
            </Link>
          </>}
        </nav>
        <div className="sidebar-society">
          <span>Connected society</span>
          <strong>{session.societyId.slice(0, 8)}</strong>
          <button
            type="button"
            onClick={() => {
              disconnect();
              router.replace("/");
            }}
          >
            <LogOut size={16} /> End session
          </button>
        </div>
        <div style={{ padding: "8px 16px", fontSize: "0.72rem", color: "#64748b", borderTop: "1px solid rgba(255,255,255,0.06)" }}>
          <a
            href="https://github.com/sushamnandi2468/Nivas"
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: "#94a3b8", textDecoration: "none" }}
          >
            NivasOps Core &bull; AGPL-3.0
          </a>
        </div>
      </aside>

      <div className="workspace-main">
        <header className="workspace-topbar">
          <button
            className="topbar-icon menu-trigger"
            type="button"
            aria-label="Open navigation"
            title="Open navigation"
            onClick={() => setMobileMenuOpen((current) => !current)}
          >
            <Menu size={20} />
          </button>
          <div className="topbar-society">
            <span>{workspaceLabel}</span>
            <strong>{displayName}</strong>
          </div>
          <div className="topbar-actions">
            <button className="topbar-icon" type="button" aria-label="Notifications" title="Notifications" disabled>
              <Bell size={19} />
            </button>
            <span className="profile-initial" aria-label={displayName}>
              {displayName.charAt(0).toUpperCase()}
            </span>
          </div>
        </header>
        <main className="workspace-content">{children}</main>
      </div>

      <nav className={`mobile-navigation ${facilityManager ? "facility-manager-navigation" : ""}`} aria-label={`Mobile ${workspaceLabel}`}>
        {navigation.map(({ href, label, icon: Icon }) => (
          <Link key={href} className={pathname === href ? "active" : ""} href={href}>
            <Icon size={19} /><span>{label}</span>
          </Link>
        ))}
      </nav>
    </div>
  );
}