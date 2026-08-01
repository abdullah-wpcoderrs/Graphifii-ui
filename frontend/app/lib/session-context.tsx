"use client";

import { createContext, ReactNode, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { fetchSession, Session } from "./session";

type SessionContextValue = {
  session: Session | null;
  loading: boolean;
};

const SessionContext = createContext<SessionContextValue>({ session: null, loading: true });

/**
 * Fetches /api/session once for the whole (authenticated) route group and
 * redirects to "/" on an unauthenticated (401 -> null) response, so
 * individual pages don't each re-fetch or re-implement the redirect guard.
 */
export function SessionProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    fetchSession()
      .then((result) => {
        if (cancelled) return;
        if (!result) {
          router.replace("/");
          return;
        }
        setSession(result);
        setLoading(false);
      })
      .catch(() => {
        if (!cancelled) {
          router.replace("/");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [router]);

  return (
    <SessionContext.Provider value={{ session, loading }}>{children}</SessionContext.Provider>
  );
}

export function useSessionContext() {
  return useContext(SessionContext);
}
