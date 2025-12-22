from __future__ import annotations

from dataclasses import dataclass

from starlette.responses import JSONResponse
from starlette.status import HTTP_413_REQUEST_ENTITY_TOO_LARGE
from starlette.types import ASGIApp, Message, Receive, Scope, Send


@dataclass(frozen=True)
class RequestSizeLimits:
    """Per-route request body limits (in bytes)."""

    default_max_bytes: int | None = None
    device_reports_max_bytes: int | None = None


class RequestEntityTooLarge(Exception):
    def __init__(self, *, limit: int, received: int):
        super().__init__(f"Request body too large (limit={limit}, received={received})")
        self.limit = limit
        self.received = received


class RequestSizeLimitMiddleware:
    """ASGI middleware that rejects requests whose body exceeds a configured limit.

    This protects us from accidentally (or maliciously) ingesting huge payloads.

    Notes:
      - If Content-Length is present, we can reject before reading the body.
      - If Content-Length is missing, we enforce a streaming limit by wrapping `receive`.
      - Limits are resolved per-path from `app.state.request_size_limits`.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    def _resolve_limit(self, scope: Scope) -> int | None:
        app = scope.get("app")
        limits: RequestSizeLimits | None = getattr(
            getattr(app, "state", None), "request_size_limits", None
        )
        if not limits:
            return None

        path = (scope.get("path") or "").rstrip("/")
        if path == "/api/v1/device/reports":
            return limits.device_reports_max_bytes or limits.default_max_bytes
        return limits.default_max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        limit = self._resolve_limit(scope)
        if not limit or limit <= 0:
            await self.app(scope, receive, send)
            return

        # Fast-path: reject early if Content-Length is present and too big.
        headers = {k.lower(): v for (k, v) in (scope.get("headers") or [])}
        raw_len = headers.get(b"content-length")
        if raw_len:
            try:
                content_length = int(raw_len.decode("ascii", errors="ignore").strip() or "0")
                if content_length > limit:
                    resp = JSONResponse(
                        status_code=HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        content={
                            "detail": "Request body too large",
                            "limit": limit,
                            "received": content_length,
                        },
                    )
                    await resp(scope, receive, send)
                    return
            except Exception:
                # If parsing fails, fall back to streaming enforcement.
                pass

        received = 0

        async def receive_limited() -> Message:
            nonlocal received
            msg = await receive()
            if msg.get("type") != "http.request":
                return msg
            body = msg.get("body") or b""
            received += len(body)
            if received > limit:
                raise RequestEntityTooLarge(limit=limit, received=received)
            return msg

        try:
            await self.app(scope, receive_limited, send)
        except RequestEntityTooLarge as exc:
            resp = JSONResponse(
                status_code=HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content={
                    "detail": "Request body too large",
                    "limit": exc.limit,
                    "received": exc.received,
                },
            )
            await resp(scope, receive, send)
