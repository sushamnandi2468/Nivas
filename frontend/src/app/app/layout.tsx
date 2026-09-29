import type { ReactNode } from "react";

import { AppShell } from "./app-shell";
import { WorkspaceSessionProvider } from "./session-context";
import "./workspace.css";

export default function WorkspaceLayout({ children }: { children: ReactNode }) {
  return (
    <WorkspaceSessionProvider>
      <AppShell>{children}</AppShell>
    </WorkspaceSessionProvider>
  );
}