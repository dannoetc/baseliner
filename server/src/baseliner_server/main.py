from fastapi import FastAPI

from baseliner_server import __version__
from baseliner_server.api.v1.router import router as v1_router
from baseliner_server.core.config import settings
from baseliner_server.middleware.correlation import CorrelationIdMiddleware
from baseliner_server.middleware.rate_limit import InMemoryRateLimiter, RateLimitConfig
from baseliner_server.middleware.request_size import RequestSizeLimitMiddleware, RequestSizeLimits

app = FastAPI(title="Baseliner API", version=__version__)


@app.on_event("startup")
def _bootstrap_db_state() -> None:
    """Best-effort bootstrapping for dev/prod.

    We keep these lightweight and idempotent so a fresh deployment behaves predictably:
      - ensure the default tenant exists
      - ensure a bootstrap admin key row exists for DEFAULT_TENANT_ID
    """

    from baseliner_server.core.bootstrap import ensure_bootstrap_admin_key
    from baseliner_server.core.tenancy import ensure_default_tenant
    from baseliner_server.db.session import SessionLocal

    db = SessionLocal()
    try:
        ensure_default_tenant(db)
        ensure_bootstrap_admin_key(db)
    finally:
        try:
            db.close()
        except Exception:
            pass


# --- Request hardening (Issue #23) ---
# Configurable via env vars (see `baseliner_server.core.config.Settings`).
app.state.request_size_limits = RequestSizeLimits(
    default_max_bytes=settings.max_request_body_bytes_default,
    device_reports_max_bytes=settings.max_request_body_bytes_device_reports,
)
app.state.rate_limit_config = RateLimitConfig(
    enabled=settings.rate_limit_enabled,
    reports_per_minute=settings.rate_limit_reports_per_minute,
    reports_burst=settings.rate_limit_reports_burst,
    reports_ip_per_minute=settings.rate_limit_reports_ip_per_minute,
    reports_ip_burst=settings.rate_limit_reports_ip_burst,
)
app.state.rate_limiter = InMemoryRateLimiter()

# Reject oversized bodies early (streaming-safe).
app.add_middleware(RequestSizeLimitMiddleware)

# Propagate/echo X-Correlation-ID so operators can trace agent logs <-> server logs.
# Added last so it wraps all other middleware and echoes the header on 413/429 responses.
app.add_middleware(CorrelationIdMiddleware, log_requests=True)


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(v1_router)
