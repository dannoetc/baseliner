from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    baseliner_token_pepper: str
    baseliner_admin_key: str

    # --- Request hardening (Issue #23) ---
    # NOTE: These defaults are intentionally conservative and can be tuned via env vars.
    # All sizes are in bytes.
    max_request_body_bytes_default: int = 1_000_000  # ~1MB for most endpoints
    max_request_body_bytes_device_reports: int = 10_000_000  # ~10MB for POST /device/reports

    # Basic in-process rate limit for device report ingestion.
    # This is *not* shared across processes/containers; for stronger guarantees, combine with
    # nginx/edge rate limiting.
    rate_limit_enabled: bool = True
    rate_limit_reports_per_minute: int = 60
    rate_limit_reports_burst: int = 10
    rate_limit_reports_ip_per_minute: int = 60
    rate_limit_reports_ip_burst: int = 10


settings = Settings()
