/**
 * Normalized error shape for every failed request made through api-client.ts.
 * Screens branch on `status` / `code` instead of parsing raw fetch errors.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(message: string, status: number, code: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }

  get isUnauthorized(): boolean {
    return this.status === 401;
  }

  get isForbidden(): boolean {
    return this.status === 403;
  }

  get isNotFound(): boolean {
    return this.status === 404;
  }
}

export class ApiConfigError extends ApiError {
  constructor() {
    super("The backend API URL is not configured.", 0, "missing_api_url");
    this.name = "ApiConfigError";
  }
}

export class ApiNetworkError extends ApiError {
  constructor(cause: unknown) {
    super("Could not reach the backend service.", 0, "network_error");
    this.name = "ApiNetworkError";
    this.cause = cause;
  }
}
