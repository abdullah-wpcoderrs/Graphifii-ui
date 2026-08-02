"""CSRF defense for the single known frontend origin.

The session and admin cookies are `SameSite=None` in production (see
`sessions.session_cookie_samesite()`'s docstring) because the frontend and
this API are different sites there, so an ordinary `SameSite=Lax` boundary
can't survive the frontend's cross-site `fetch()` calls. That trade removed
the CSRF protection `Lax` was incidentally providing, and this app
authenticates purely via cookies with no CSRF token — so this middleware
rejects any state-changing browser request that carries an auth cookie but
whose `Origin` (or `Referer`, as a fallback) does not match the configured
frontend origin.

Only requests carrying one of the auth cookie names are checked. The
internal sandbox callback routes (`/api/internal/...`) are never called with
a browser session cookie attached, so they are exempt without needing an
explicit path allowlist that could drift from the real route list.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _origin_of(value: str) -> str:
    """Reduce a URL (an Origin header, or a Referer header with a path) to
    its `scheme://host[:port]` for comparison."""
    parts = urlsplit(value)
    return f"{parts.scheme}://{parts.netloc}"


class CSRFOriginMiddleware(BaseHTTPMiddleware):
    def __init__(
        self, app: ASGIApp, *, frontend_url: str, cookie_names: frozenset[str]
    ) -> None:
        super().__init__(app)
        self._frontend_origin = _origin_of(frontend_url)
        self._cookie_names = cookie_names

    async def dispatch(self, request: Request, call_next):
        if request.method in _UNSAFE_METHODS and any(
            name in request.cookies for name in self._cookie_names
        ):
            candidate = request.headers.get("origin") or request.headers.get("referer")
            if candidate is None or _origin_of(candidate) != self._frontend_origin:
                return JSONResponse(
                    {"detail": "cross-site request rejected"}, status_code=403
                )
        return await call_next(request)
