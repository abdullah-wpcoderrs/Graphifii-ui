"use client";

import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AdminSession, fetchAdminSession } from "./admin-session";

type AdminSessionContextValue = {
  admin: AdminSession | null;
  loading: boolean;
  refresh: () => Promise<void>;
};

const AdminSessionContext = createContext<AdminSessionContextValue>({
  admin: null,
  loading: true,
  refresh: async () => {},
});

/**
 * Fetches /api/admin/me for the whole admin route group and redirects to
 * /admin/login on an unauthenticated (401 -> null) response. Deliberately
 * separate from SessionProvider (session-context.tsx): the admin cookie and
 * the GitHub user cookie are independent principals with no shared state —
 * see graphify/server/admin_sessions.py.
 */
export function AdminSessionProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [admin, setAdmin] = useState<AdminSession | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const result = await fetchAdminSession();
      if (!result) {
        router.replace("/admin/login");
        return;
      }
      setAdmin(result);
      setLoading(false);
    } catch {
      router.replace("/admin/login");
    }
  }, [router]);

  useEffect(() => {
    let cancelled = false;

    fetchAdminSession()
      .then((result) => {
        if (cancelled) return;
        if (!result) {
          router.replace("/admin/login");
          return;
        }
        setAdmin(result);
        setLoading(false);
      })
      .catch(() => {
        if (!cancelled) {
          router.replace("/admin/login");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [router]);

  return (
    <AdminSessionContext.Provider value={{ admin, loading, refresh: load }}>
      {children}
    </AdminSessionContext.Provider>
  );
}

export function useAdminSessionContext() {
  return useContext(AdminSessionContext);
}
