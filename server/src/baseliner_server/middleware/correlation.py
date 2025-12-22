from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

CORRELATION_ID_HEADER = "X-Correlation-ID"

# Safe id: 1-128 chars, starts with alnum, allow alnum . _ -
_SAFE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _new_id() -> str:
    return str(uuid.uuid4())


def normalize_correlation_id(value: str | None) -> str:
    """Validate and normalize a correlation id.

    If missing or invalid, returns a newly generated UUID.
    """

    if not value:
        return _new_id()

    v = value.strip()
    if not v:
        return _new_id()

    if len(v) > 128:
        v = v[:128]

    if not _SAFE_RE.match(v):
        return _new_id()

    return v


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Adds/propagates X-Correlation-ID and logs basic request lines.

    - If the client sends X-Correlation-ID, we validate and propagate it.
    - If missing/invalid, we generate a new UUID.
    - We set request.state.correlation_id for downstream handlers.
    - We echo X-Correlation-ID in the response header (best-effort).
    """

    def __init__(self, app, *, log_requests: bool = True) -> None:
        super().__init__(app)
        self.log_requests = log_requests
        self.log = logging.getLogger("baseliner_server.request")

    async def dispatch(self, request: Request, call_next) -> Response:
        cid = normalize_correlation_id(request.headers.get(CORRELATION_ID_HEADER))
        request.state.correlation_id = cid

        start = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = int((time.monotonic() - start) * 1000)
            if self.log_requests:
                self.log.exception(
                    "request failed cid=%s method=%s path=%s duration_ms=%s",
                    cid,
                    request.method,
                    request.url.path,
                    duration_ms,
                )
            raise

        # Echo correlation id in response headers.
        try:
            response.headers[CORRELATION_ID_HEADER] = cid
        except Exception:
            # Extremely defensive: some streaming response types may not allow mutation.
            pass

        if self.log_requests:
            duration_ms = int((time.monotonic() - start) * 1000)
            self.log.info(
                "request cid=%s method=%s path=%s status=%s duration_ms=%s",
                cid,
                request.method,
                request.url.path,
                getattr(response, "status_code", None),
                duration_ms,
            )

        return response
