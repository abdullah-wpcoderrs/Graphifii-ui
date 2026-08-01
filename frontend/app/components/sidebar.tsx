"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { BrandLockup } from "./brand-lockup";
import { logout } from "../lib/session";
import { useSessionContext } from "../lib/session-context";

const COLLAPSE_STORAGE_KEY = "sidebar-collapsed";

type NavItem = {
  href: string;
  label: string;
};

const NAV_ITEMS: NavItem[] = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/repositories", label: "Repositories" },
  { href: "/projects", label: "Projects" },
  { href: "/integrations", label: "Integrations" },
  { href: "/settings", label: "Settings" },
];

const DOCS_URL = "https://graphify.com/docs";

function DashboardIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 20 20">
      <rect x="2.5" y="2.5" width="6" height="6" rx="1.2" />
      <rect x="11.5" y="2.5" width="6" height="6" rx="1.2" />
      <rect x="2.5" y="11.5" width="6" height="6" rx="1.2" />
      <rect x="11.5" y="11.5" width="6" height="6" rx="1.2" />
    </svg>
  );
}

function RepositoriesIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 20 20">
      <path d="M3 5.5A2 2 0 0 1 5 3.5h3.5l1.5 2H15a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
    </svg>
  );
}

function ProjectsIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 20 20">
      <path d="M4 4.5h12a1 1 0 0 1 1 1V13a1 1 0 0 1-1 1H9l-3.5 3V14H4a1 1 0 0 1-1-1V5.5a1 1 0 0 1 1-1Z" />
      <path d="M6.5 8h7M6.5 10.5h4.5" />
    </svg>
  );
}

function IntegrationsIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 20 20">
      <circle cx="6" cy="6" r="2.5" />
      <circle cx="14" cy="6" r="2.5" />
      <circle cx="10" cy="14" r="2.5" />
      <path d="M8 7.5 9 12M12 7.5 11 12" />
    </svg>
  );
}

function SettingsIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 20 20">
      <circle cx="10" cy="10" r="2.6" />
      <path d="M10 3.2v2M10 14.8v2M16.8 10h-2M5.2 10h-2M15.1 4.9l-1.4 1.4M6.3 13.7l-1.4 1.4M15.1 15.1l-1.4-1.4M6.3 6.3 4.9 4.9" />
    </svg>
  );
}

function DocsIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 20 20">
      <path d="M5 3.5h6l4 4v9a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-12a1 1 0 0 1 1-1Z" />
      <path d="M11 3.5V8h4" />
    </svg>
  );
}

function ExternalLinkIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 20 20">
      <path d="M8 5H5.5A1.5 1.5 0 0 0 4 6.5v8A1.5 1.5 0 0 0 5.5 16h8a1.5 1.5 0 0 0 1.5-1.5V12" />
      <path d="M11 4h5v5M15.5 4.5 9 11" />
    </svg>
  );
}

const ICONS: Record<string, () => React.ReactElement> = {
  "/dashboard": DashboardIcon,
  "/repositories": RepositoriesIcon,
  "/projects": ProjectsIcon,
  "/integrations": IntegrationsIcon,
  "/settings": SettingsIcon,
};

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { session } = useSessionContext();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    // Reads localStorage after mount (client-only) rather than in the
    // initial useState to avoid an SSR/client hydration mismatch.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setCollapsed(window.localStorage.getItem(COLLAPSE_STORAGE_KEY) === "true");
  }, []);

  function toggleCollapsed() {
    setCollapsed((current) => {
      const next = !current;
      window.localStorage.setItem(COLLAPSE_STORAGE_KEY, String(next));
      return next;
    });
  }

  async function handleLogout() {
    try {
      await logout();
    } finally {
      router.replace("/");
    }
  }

  return (
    <>
      <button
        type="button"
        className="sidebar-mobile-toggle"
        aria-label={mobileOpen ? "Close navigation" : "Open navigation"}
        aria-expanded={mobileOpen}
        onClick={() => setMobileOpen((open) => !open)}
      >
        <span />
        <span />
        <span />
      </button>

      {mobileOpen && (
        <div className="sidebar-mobile-scrim" onClick={() => setMobileOpen(false)} aria-hidden="true" />
      )}

      <aside
        className={`sidebar ${collapsed ? "is-collapsed" : ""} ${mobileOpen ? "is-mobile-open" : ""}`}
        aria-label="Primary navigation"
      >
        <div className="sidebar-brand">
          <BrandLockup className={collapsed ? "sr-only" : "brand-lockup"} />
          <button
            type="button"
            className="sidebar-collapse-toggle"
            onClick={toggleCollapsed}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            <svg aria-hidden="true" viewBox="0 0 20 20">
              <path d={collapsed ? "M7 4l6 6-6 6" : "M13 4 7 10l6 6"} />
            </svg>
          </button>
        </div>

        <nav className="sidebar-nav" aria-label="Sections">
          {NAV_ITEMS.map((item) => {
            const Icon = ICONS[item.href];
            const isActive = pathname === item.href || pathname.startsWith(`${item.href}/`);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`sidebar-nav-item ${isActive ? "is-active" : ""}`}
                onClick={() => setMobileOpen(false)}
              >
                <Icon />
                <span>{item.label}</span>
              </Link>
            );
          })}
          <a
            className="sidebar-nav-item sidebar-nav-external"
            href={DOCS_URL}
            target="_blank"
            rel="noopener noreferrer"
          >
            <DocsIcon />
            <span>Docs / Help</span>
            <ExternalLinkIcon />
          </a>
        </nav>

        <div className="sidebar-user">
          {session?.avatarUrl ? (
            <Image
              src={session.avatarUrl}
              alt=""
              width={32}
              height={32}
              className="sidebar-user-avatar"
            />
          ) : (
            <div className="sidebar-user-avatar sidebar-user-avatar-fallback" aria-hidden="true" />
          )}
          <div className="sidebar-user-identity">
            <strong>{session?.name || session?.githubLogin || "Account"}</strong>
            {session?.email && <span>{session.email}</span>}
          </div>
          <button type="button" className="sidebar-logout" onClick={handleLogout}>
            Sign out
          </button>
        </div>
      </aside>
    </>
  );
}
