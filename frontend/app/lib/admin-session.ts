import { apiGet, apiPost } from "./api-client";
import { ApiError } from "./api-errors";

export type AdminSession = {
  id: string;
  email: string;
  last_login_at: string | null;
};

/** Returns the current admin session, or null if not authenticated (401). Any
 * other failure (network, config, 5xx) is rethrown for the caller to handle.
 *
 * This hits /api/admin/me, guarded by the isolated `graphify_admin_session`
 * cookie — entirely separate from the GitHub-based /api/session used by
 * regular users. See graphify/server/admin_sessions.py. */
export async function fetchAdminSession(): Promise<AdminSession | null> {
  try {
    return await apiGet<AdminSession>("/api/admin/me");
  } catch (error) {
    if (error instanceof ApiError && error.isUnauthorized) {
      return null;
    }
    throw error;
  }
}

export async function adminLogin(email: string, password: string): Promise<AdminSession> {
  await apiPost<{ ok: true; email: string }>("/api/admin/login", { email, password });
  const session = await fetchAdminSession();
  if (!session) {
    // The credentials were accepted (the POST above did not throw) but the
    // very next request came back unauthenticated — the browser never stored
    // or never returned the cookie. In production that means the backend
    // issued it without `Secure`/`SameSite=None` across the frontend/API site
    // boundary; see graphify/server/sessions.py's is_secure_cookie(). Its own
    // code so the UI can say that instead of blaming the password.
    throw new ApiError(
      "Signed in, but the session cookie was rejected by your browser.",
      0,
      "session_not_persisted",
    );
  }
  return session;
}

export async function adminLogout(): Promise<void> {
  await apiPost("/api/admin/logout");
}
