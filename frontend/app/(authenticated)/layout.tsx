"use client";

import Image from "next/image";
import { ReactNode } from "react";
import { Sidebar } from "../components/sidebar";
import { SessionProvider, useSessionContext } from "../lib/session-context";
import { Spinner } from "../components/ui";

function AuthenticatedTopbar() {
  const { session } = useSessionContext();

  if (!session) return null;

  return (
    <header className="authenticated-topbar">
      <span className="authenticated-github-status">
        <i aria-hidden="true" />
        GitHub connected
      </span>
      <span className="authenticated-github-user">
        {session.avatarUrl ? (
          <Image src={session.avatarUrl} alt="" width={16} height={16} />
        ) : null}
        {session.githubLogin}
      </span>
    </header>
  );
}

function AuthenticatedShell({ children }: { children: ReactNode }) {
  const { loading } = useSessionContext();

  if (loading) {
    return (
      <div className="authenticated-loading">
        <Spinner size="lg" label="Checking your session" />
      </div>
    );
  }

  return (
    <div className="authenticated-shell">
      <Sidebar />
      <main className="authenticated-main">
        <AuthenticatedTopbar />
        {children}
      </main>
    </div>
  );
}

export default function AuthenticatedLayout({ children }: { children: ReactNode }) {
  return (
    <SessionProvider>
      <AuthenticatedShell>{children}</AuthenticatedShell>
    </SessionProvider>
  );
}
