import { getPublicApiUrl } from "./env";
import { ApiConfigError, ApiError, ApiNetworkError } from "./api-errors";

type RequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
};

function statusToCode(status: number): string {
  if (status === 401) return "unauthorized";
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status >= 500) return "server_error";
  return `http_${status}`;
}

async function parseErrorMessage(response: Response): Promise<string> {
  try {
    const data = await response.clone().json();
    if (typeof data?.detail === "string") return data.detail;
    if (typeof data?.message === "string") return data.message;
  } catch {
    // response body wasn't JSON — fall through to statusText
  }
  return response.statusText || `Request failed with status ${response.status}`;
}

/**
 * Credentialed fetch wrapper for the Graphify backend. Always sends the
 * session cookie (`credentials: "include"`), always normalizes failures into
 * `ApiError` so screens can branch on `.status` / `.code` instead of
 * re-parsing fetch/JSON errors themselves.
 */
export async function apiFetch<T = unknown>(
  endpoint: string,
  options: RequestOptions = {},
): Promise<T> {
  const apiUrl = getPublicApiUrl();
  if (!apiUrl) {
    throw new ApiConfigError();
  }

  const { body, headers, ...rest } = options;
  const init: RequestInit = {
    ...rest,
    credentials: "include",
    headers: {
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...headers,
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  };

  let response: Response;
  try {
    response = await fetch(`${apiUrl}${endpoint}`, init);
  } catch (cause) {
    throw new ApiNetworkError(cause);
  }

  if (!response.ok) {
    const message = await parseErrorMessage(response);
    throw new ApiError(message, response.status, statusToCode(response.status));
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export function apiGet<T = unknown>(endpoint: string, options?: RequestOptions) {
  return apiFetch<T>(endpoint, { ...options, method: "GET" });
}

export function apiPost<T = unknown>(
  endpoint: string,
  body?: unknown,
  options?: RequestOptions,
) {
  return apiFetch<T>(endpoint, { ...options, method: "POST", body });
}

export function apiPut<T = unknown>(
  endpoint: string,
  body?: unknown,
  options?: RequestOptions,
) {
  return apiFetch<T>(endpoint, { ...options, method: "PUT", body });
}

export function apiDelete<T = unknown>(endpoint: string, options?: RequestOptions) {
  return apiFetch<T>(endpoint, { ...options, method: "DELETE" });
}
