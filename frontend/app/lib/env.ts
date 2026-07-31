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
