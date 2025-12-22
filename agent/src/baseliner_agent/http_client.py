import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

import requests

LogFn = Callable[[dict[str, Any]], None]


@dataclass
class ApiResponse:
    data: Any
    status: int
    headers: dict[str, str]
    request_id: str | None


def _request_id_from_headers(headers: Mapping[str, str] | None) -> str | None:
    if not headers:
        return None

    lower = {str(k).lower(): v for k, v in headers.items()}
    for key in ("x-request-id", "x-requestid", "x-ms-request-id", "request-id"):
        if key in lower:
            return str(lower[key])
    return None


def _emit_log(log_fn: LogFn | None, event: dict[str, Any]) -> None:
    if log_fn is None:
        return
    try:
        log_fn(event)
    except Exception:
        # Never let logging break HTTP handling
        pass


class ApiClient:
    def __init__(
        self,
        base_url: str,
        device_token: str | None = None,
        timeout_s: int = 30,
        *,
        correlation_id: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.device_token = device_token
        self.timeout_s = timeout_s
        self.correlation_id = correlation_id

    def _headers(self, *, correlation_id: str | None = None) -> dict[str, str]:
        h = {"Accept": "application/json"}
        if self.device_token:
            h["Authorization"] = f"Bearer {self.device_token}"
        cid = correlation_id or self.correlation_id
        if cid:
            h["X-Correlation-ID"] = str(cid)
        return h

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        retries: int = 2,
        payload: Any | None = None,
        log_fn: LogFn | None = None,
        correlation_id: str | None = None,
    ) -> ApiResponse:
        url = f"{self.base_url}{path}"
        last_exc: Exception | None = None

        for attempt in range(retries + 1):
            resp = None
            _emit_log(
                log_fn,
                {
                    "level": "info",
                    "event": "http_request",
                    "url": url,
                    "method": method,
                    "attempt": attempt + 1,
                    "correlation_id": correlation_id or self.correlation_id,
                },
            )
            try:
                resp = requests.request(
                    method,
                    url,
                    json=payload,
                    headers=self._headers(correlation_id=correlation_id),
                    timeout=self.timeout_s,
                )
                request_id = _request_id_from_headers(resp.headers)
                _emit_log(
                    log_fn,
                    {
                        "level": "info",
                        "event": "http_response",
                        "url": url,
                        "method": method,
                        "attempt": attempt + 1,
                        "status": resp.status_code,
                        "request_id": request_id,
                        "correlation_id": correlation_id or self.correlation_id,
                    },
                )
                resp.raise_for_status()
                return ApiResponse(
                    data=resp.json(),
                    status=resp.status_code,
                    headers=dict(resp.headers),
                    request_id=request_id,
                )
            except Exception as e:
                last_exc = e
                request_id = _request_id_from_headers(resp.headers if resp is not None else None)
                _emit_log(
                    log_fn,
                    {
                        "level": "warning",
                        "event": "http_error",
                        "url": url,
                        "method": method,
                        "attempt": attempt + 1,
                        "status": getattr(resp, "status_code", None),
                        "request_id": request_id,
                        "correlation_id": correlation_id or self.correlation_id,
                        "error": str(e),
                    },
                )

                if attempt < retries:
                    time.sleep(2**attempt)
                    continue
                raise last_exc

        raise last_exc  # pragma: no cover

    def post_json(
        self,
        path: str,
        payload: Any,
        retries: int = 2,
        *,
        log_fn: LogFn | None = None,
        correlation_id: str | None = None,
    ) -> ApiResponse:
        return self._request_json(
            "POST",
            path,
            payload=payload,
            retries=retries,
            log_fn=log_fn,
            correlation_id=correlation_id,
        )

    def get_json(
        self,
        path: str,
        retries: int = 2,
        *,
        log_fn: LogFn | None = None,
        correlation_id: str | None = None,
    ) -> ApiResponse:
        return self._request_json(
            "GET",
            path,
            retries=retries,
            log_fn=log_fn,
            correlation_id=correlation_id,
        )
