import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .state import ensure_queue_dir


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def truncate(s: str, max_len: int = 4000) -> str:
    if s is None:
        return ""
    s = str(s)
    return s if len(s) <= max_len else (s[:max_len] + "…")


def queue_report(state_dir: str, payload: dict[str, Any]) -> Path:
    qdir = ensure_queue_dir(state_dir)
    rid = str(uuid.uuid4())
    path = qdir / f"{rid}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def iter_queued_reports(state_dir: str) -> list[Path]:
    qdir = ensure_queue_dir(state_dir)
    return sorted(qdir.glob("*.json"), key=lambda p: p.stat().st_mtime)


def delete_queued(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
