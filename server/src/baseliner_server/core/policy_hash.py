import hashlib
import json
from typing import Any


def compute_effective_policy_hash(
    *,
    policy_id: str | None,
    policy_name: str | None,
    schema_version: str | None,
    mode: str | None,
    document: dict[str, Any] | None,
    sources: list[dict[str, Any]] | None,
) -> str:
    payload = {
        "policy_id": policy_id,
        "policy_name": policy_name,
        "schema_version": schema_version,
        "mode": mode,
        "document": document or {},
        "sources": sources or [],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
