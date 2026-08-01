"use client";

import { ReactNode } from "react";
import { useRouter } from "next/navigation";
import { AdminSessionProvider, useAdminSessionContext } from "../../lib/admin-session-context";
import { adminLogout } from "../../lib/admin-session";
import { Spinner } from "../../components/ui";

function AdminProtectedShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { admin, loading } = useAdminSessionContext();

  async function handleLogout() {
    try {
      await adminLogout();
    } finally {
      router.replace("/admin/login");
    }
  }

  if (loading || !admin) {
    return (
      <div className="admin-login-page">
        <Spinner size="lg" label="Checking your admin session" />
      </div>
    );
  }

  return (
    <div className="admin-shell">
      <header className="admin-topbar">
        <span className="admin-topbar-brand">Graphify Admin</span>
        <div className="admin-topbar-account">
          <span>{admin.email}</span>
          <button type="button" className="admin-topbar-signout" onClick={handleLogout}>
            Sign out
          </button>
        </div>
      </header>
      <main className="admin-main">{children}</main>
    </div>
  );
}

export default function AdminProtectedLayout({ children }: { children: ReactNode }) {
  return (
    <AdminSessionProvider>
      <AdminProtectedShell>{children}</AdminProtectedShell>
    </AdminSessionProvider>
  );
}
