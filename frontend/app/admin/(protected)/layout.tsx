"use client";

import { ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { AdminSessionProvider, useAdminSessionContext } from "../../lib/admin-session-context";
import { adminLogout } from "../../lib/admin-session";
import { Spinner } from "../../components/ui";

const ADMIN_NAV_ITEMS = [
  { href: "/admin/settings", label: "LLM Credentials" },
  { href: "/admin/usage", label: "Usage & Spend" },
  { href: "/admin/analytics", label: "Analytics" },
  { href: "/admin/users", label: "Users" },
];

function AdminProtectedShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
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
      <nav className="admin-nav" aria-label="Admin sections">
        {ADMIN_NAV_ITEMS.map((item) => {
          const isActive = pathname === item.href || pathname.startsWith(`${item.href}/`);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`admin-nav-item ${isActive ? "is-active" : ""}`}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>
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
