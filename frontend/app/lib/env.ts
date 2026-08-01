const TRAILING_SLASHES = /\/+$/;

export function getPublicApiUrl(): string | null {
  const value = process.env.NEXT_PUBLIC_API_URL?.trim();

  if (!value) {
    return null;
  }

  try {
    const url = new URL(value);

    if (url.protocol !== "http:" && url.protocol !== "https:") {
      return null;
    }

    return value.replace(TRAILING_SLASHES, "");
  } catch {
    return null;
  }
}

/** Same origin as the API, but ws(s):// — for /ws/projects/:id. */
export function getPublicWsUrl(): string | null {
  const apiUrl = getPublicApiUrl();
  if (!apiUrl) return null;

  try {
    const url = new URL(apiUrl);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    return url.toString().replace(TRAILING_SLASHES, "");
  } catch {
    return null;
  }
}
