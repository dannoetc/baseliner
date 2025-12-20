from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(str(raw).strip())
    except Exception:
        return default


def local_log_limits() -> int:
    """
    How many per-run log files to retain under <state_dir>\\logs\\runs.

    Env override:
      - BASELINER_LOCAL_LOG_MAX_FILES (default 200)
    """
    v = _env_int("BASELINER_LOCAL_LOG_MAX_FILES", 200)
    return max(10, v)


def ensure_run_log_dir(state_dir: str | Path) -> Path:
    d = Path(state_dir) / "logs" / "runs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_agent_log_dir(state_dir: str | Path) -> Path:
    d = Path(state_dir) / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def agent_log_path(state_dir: str | Path) -> Path:
    return ensure_agent_log_dir(state_dir) / "agent.log"


def _safe_filename(s: str) -> str:
    # Windows-friendly filename sanitation
    bad = '<>:"/\\|?*'
    out = []
    for ch in s:
        if ch in bad or ord(ch) < 32:
            out.append("_")
        else:
            out.append(ch)
    return "".join(out).strip(" .")


def new_run_log_path(state_dir: str | Path, started_at_iso: str, local_run_id: str) -> Path:
    d = ensure_run_log_dir(state_dir)
    base = _safe_filename(started_at_iso.replace(":", "-"))
    return d / f"{base}__{local_run_id}.jsonl"


def _event_to_text_line(event: dict[str, Any]) -> str:
    """Best-effort one-line log for easy tailing."""
    ts = str(event.get("ts") or "").strip()
    lvl = str(event.get("level") or "info").upper()

    # Prefer structured "event" name; fallback to message.
    name = event.get("event") or event.get("message") or "log"
    name = str(name).strip()

    # Compact context that is useful when debugging in the field.
    ctx_parts: list[str] = []
    for k in (
        "local_run_id",
        "correlation_id",
        "request_id",
        "server_run_id",
        "effective_policy_hash",
        "ordinal",
        "resource_type",
        "resource_id",
        "status",
    ):
        v = event.get(k)
        if v is None:
            continue
        s = str(v)
        if not s:
            continue
        ctx_parts.append(f"{k}={s}")

    if event.get("error"):
        ctx_parts.append(f"error={str(event.get('error'))}")

    # Ensure single-line output (no newlines/tabs)
    ctx = " ".join(ctx_parts).replace("\n", " ").replace("\r", " ").replace("\t", " ").strip()

    if ts:
        return f"{ts} {lvl} {name} {ctx}".strip()
    return f"{lvl} {name} {ctx}".strip()


def _append_text(path: Path, line: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(line + "\n")
    except Exception:
        pass


def log_event(path: Path, event: dict[str, Any]) -> None:
    """
    Append one JSONL record to the run log.
    Best-effort: never raise.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")

        # Also append a compact, human-readable line to <state_dir>\logs\agent.log.
        # This is intentionally best-effort and only applies when logging to the run logs directory.
        # (It keeps existing JSONL files as the source of truth for structured logs.)
        try:
            if path.parent.name == "runs" and path.parent.parent.name == "logs":
                _append_text(path.parent.parent / "agent.log", _event_to_text_line(event))
        except Exception:
            pass
    except Exception:
        # Never let logging break the agent.
        pass


def prune_run_logs(state_dir: str | Path, max_files: int | None = None) -> dict[str, int]:
    """
    Keep only the newest N run log files (oldest-first deletion).
    Returns stats: removed_files, kept_files.
    """
    if max_files is None:
        max_files = local_log_limits()
    max_files = max(10, int(max_files))

    d = ensure_run_log_dir(state_dir)
    paths = [p for p in d.glob("*.jsonl") if p.is_file()]
    paths.sort(key=lambda p: p.stat().st_mtime)

    removed = 0
    while len(paths) > max_files:
        p = paths.pop(0)
        try:
            p.unlink()
            removed += 1
        except Exception:
            # If we can't delete something, skip it and keep going
            pass

    return {"removed_files": removed, "kept_files": len(paths)}
