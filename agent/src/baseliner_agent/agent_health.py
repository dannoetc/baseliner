from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .reporting import queue_limits, iter_queued_reports
from .state import AgentState


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_utc(dt: datetime | None) -> datetime | None:
    """
    Normalize datetimes to tz-aware UTC.
    Treat naive datetimes as UTC (common when coming from sqlite/test contexts).
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_utc_iso(v: Any) -> Any:
    """
    Make values JSON-safe and timezone-consistent:
      - datetime -> ISO8601 in UTC
      - ISO strings pass through (optionally normalized if parsable)
      - everything else unchanged
    """
    if v is None:
        return None

    if isinstance(v, datetime):
        dt = _as_utc(v)
        return dt.isoformat() if dt else None

    if isinstance(v, str):
        # Attempt to normalize common ISO variants (including trailing 'Z')
        s = v.strip()
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            dt = _as_utc(dt)
            return dt.isoformat() if dt else v
        except Exception:
            return v

    return v


def _atomic_write_text(path: Path, text: str, encoding: str = "utf-8-sig") -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding=encoding)
    os.replace(tmp, path)


def _queue_stats(state_dir: str | Path) -> dict[str, Any]:
    paths = iter_queued_reports(state_dir)
    total_bytes = 0
    for p in paths:
        try:
            total_bytes += int(p.stat().st_size)
        except Exception:
            pass

    max_files, max_bytes = queue_limits()
    return {
        "files": len(paths),
        "bytes": total_bytes,
        "max_files": max_files,
        "max_bytes": max_bytes,
    }


def _latest_run_log(state_dir: str | Path) -> dict[str, Any]:
    sd = Path(state_dir)
    runs_dir = sd / "logs" / "runs"
    if not runs_dir.exists():
        return {"latest_path": None, "latest_mtime": None}

    candidates = [p for p in runs_dir.glob("*.jsonl") if p.is_file()]
    if not candidates:
        return {"latest_path": None, "latest_mtime": None}

    latest = max(candidates, key=lambda p: p.stat().st_mtime)
    try:
        mtime = datetime.fromtimestamp(latest.stat().st_mtime, tz=timezone.utc).isoformat()
    except Exception:
        mtime = None

    return {"latest_path": str(latest), "latest_mtime": mtime}


def build_health(state_dir: str | Path, state: AgentState | None = None) -> dict[str, Any]:
    st = state or AgentState.load(state_dir)

    return {
        "ts": utcnow_iso(),
        "device_id": st.device_id,
        "device_key": st.device_key,
        "agent_version": st.agent_version,
        "server_url": st.last_server_url,
        "run": {
            "last_run_at": _to_utc_iso(st.last_run_at),
            "last_success_at": _to_utc_iso(st.last_success_at),
            "last_failed_at": _to_utc_iso(st.last_failed_at),
            "consecutive_failures": int(st.consecutive_failures or 0),
            "last_run_status": st.last_run_status,
            "last_run_exit": st.last_run_exit,
            "last_http_ok_at": _to_utc_iso(st.last_http_ok_at),
        },
        "policy": {
            "last_applied_policy_hash": st.last_applied_policy_hash,
            "last_reported_policy_hash": st.last_reported_policy_hash,
            "last_policy_hash_legacy": st.last_policy_hash,
        },
        "observed_state_hash": st.last_observed_state_hash,
        "queue": _queue_stats(state_dir),
        "logging": _latest_run_log(state_dir),
    }


def write_health(state_dir: str | Path, state: AgentState | None = None, *, path: str | Path | None = None) -> Path:
    sd = Path(state_dir)
    out_path = Path(path) if path else (sd / "health.json")
    payload = build_health(sd, state=state)
    _atomic_write_text(out_path, json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    return out_path
