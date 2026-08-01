import { apiGet, apiPost } from "./api-client";
import { ApiError } from "./api-errors";

export type Role = "ADMIN" | "USER";

export type Session = {
  id: string;
  githubLogin: string;
  email: string | null;
  name: string | null;
  avatarUrl: string | null;
  role: Role;
};

/** Returns the current session, or null if not authenticated (401). Any
 * other failure (network, config, 5xx) is rethrown for the caller to handle. */
export async function fetchSession(): Promise<Session | null> {
  try {
    return await apiGet<Session>("/api/session");
  } catch (error) {
    if (error instanceof ApiError && error.isUnauthorized) {
      return null;
    }
    throw error;
  }
}

export async function logout(): Promise<void> {
  await apiPost("/api/auth/logout");
}
