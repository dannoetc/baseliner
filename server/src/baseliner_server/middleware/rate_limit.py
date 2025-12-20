from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.status import HTTP_429_TOO_MANY_REQUESTS

from baseliner_server.api.deps import get_db, hash_token
from baseliner_server.db.models import Device


@dataclass(frozen=True)
class RateLimitConfig:
    """Configuration for app-layer rate limiting."""

    enabled: bool = True
    reports_per_minute: int = 60
    reports_burst: int = 10
    reports_ip_per_minute: int = 60
    reports_ip_burst: int = 10


class _TokenBucket:
    __slots__ = ("capacity", "refill_rate", "tokens", "last_ts")

    def __init__(self, *, capacity: float, refill_rate: float, now: float):
        self.capacity = float(capacity)
        self.refill_rate = float(refill_rate)  # tokens / second
        self.tokens = float(capacity)
        self.last_ts = float(now)

    def consume(self, *, now: float, amount: float = 1.0) -> tuple[bool, int]:
        # Refill
        dt = max(0.0, float(now) - self.last_ts)
        if dt:
            self.tokens = min(self.capacity, self.tokens + dt * self.refill_rate)
            self.last_ts = float(now)

        if self.tokens >= amount:
            self.tokens -= amount
            return True, 0

        # How long until we have enough tokens for one request?
        missing = amount - self.tokens
        if self.refill_rate <= 0:
            return False, 60
        retry_after = int(max(1.0, missing / self.refill_rate))
        return False, retry_after


class InMemoryRateLimiter:
    """In-memory token bucket store.

    NOTE: This does not share state across processes/containers.
    """

    def __init__(self, *, max_entries: int = 50_000, stale_after_seconds: int = 3600):
        self._lock = threading.Lock()
        self._buckets: dict[str, _TokenBucket] = {}
        self._last_seen: dict[str, float] = {}
        self._max_entries = int(max_entries)
        self._stale_after = int(stale_after_seconds)

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()
            self._last_seen.clear()

    def _prune(self, *, now: float) -> None:
        # Cheap opportunistic pruning.
        if len(self._buckets) <= self._max_entries:
            return

        cutoff = now - float(self._stale_after)
        stale_keys = [k for k, ts in self._last_seen.items() if ts < cutoff]
        for k in stale_keys:
            self._buckets.pop(k, None)
            self._last_seen.pop(k, None)

        # Still too large? Drop oldest.
        if len(self._buckets) <= self._max_entries:
            return
        for k, _ts in sorted(self._last_seen.items(), key=lambda kv: kv[1])[: max(0, len(self._buckets) - self._max_entries)]:
            self._buckets.pop(k, None)
            self._last_seen.pop(k, None)

    def consume(
        self,
        *,
        key: str,
        capacity: int,
        per_minute: int,
        now: Optional[float] = None,
    ) -> tuple[bool, int]:
        """Consume one token from the key's bucket.

        Returns (allowed, retry_after_seconds).
        """

        n = time.monotonic() if now is None else float(now)
        cap = max(1, int(capacity))
        rpm = max(1, int(per_minute))
        refill_rate = float(rpm) / 60.0

        with self._lock:
            b = self._buckets.get(key)
            if b is None:
                b = _TokenBucket(capacity=float(cap), refill_rate=refill_rate, now=n)
                self._buckets[key] = b

            self._last_seen[key] = n
            allowed, retry_after = b.consume(now=n, amount=1.0)
            self._prune(now=n)
            return allowed, retry_after


def _client_ip(request: Request) -> str:
    try:
        if request.client and request.client.host:
            return request.client.host
    except Exception:
        pass
    return "unknown"


def _try_get_device_id(db: Session, token: str) -> str | None:
    token_h = hash_token(token)
    # Fetch only the UUID (avoid loading full Device model)
    device_id = db.scalar(select(Device.id).where(Device.auth_token_hash == token_h))
    return str(device_id) if device_id else None


def _get_config(request: Request) -> RateLimitConfig:
    cfg: RateLimitConfig | None = getattr(getattr(request.app, "state", None), "rate_limit_config", None)
    if cfg is None:
        return RateLimitConfig()
    return cfg


def _get_limiter(request: Request) -> InMemoryRateLimiter:
    limiter: InMemoryRateLimiter | None = getattr(getattr(request.app, "state", None), "rate_limiter", None)
    if limiter is None:
        limiter = InMemoryRateLimiter()
        request.app.state.rate_limiter = limiter
    return limiter


def enforce_device_reports_rate_limit(
    request: Request,
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(default=None),
) -> None:
    """Rate-limit POST /api/v1/device/reports.

    Key selection:
      - device:<uuid> when the bearer token maps to a known device
      - ip:<client_ip> fallback (missing/invalid token)
    """

    cfg = _get_config(request)
    if not cfg.enabled:
        return

    token: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()

    device_id = None
    if token:
        try:
            device_id = _try_get_device_id(db, token)
        except Exception:
            device_id = None

    if device_id:
        key = f"device:{device_id}"
        per_minute = cfg.reports_per_minute
        burst = cfg.reports_burst
    else:
        key = f"ip:{_client_ip(request)}"
        per_minute = cfg.reports_ip_per_minute
        burst = cfg.reports_ip_burst

    limiter = _get_limiter(request)
    allowed, retry_after = limiter.consume(key=key, capacity=burst, per_minute=per_minute)
    if allowed:
        return

    raise HTTPException(
        status_code=HTTP_429_TOO_MANY_REQUESTS,
        detail="Rate limit exceeded",
        headers={"Retry-After": str(int(retry_after))},
    )
