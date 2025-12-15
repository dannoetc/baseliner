from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .state import ensure_queue_dir


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def truncate(s: Any, max_len: int = 4000) -> str:
    if s is None:
        return ""
    s = str(s)
    return s if len(s) <= max_len else (s[:max_len] + "…")


def _atomic_write_text(path: Path, text: str, encoding: str = "utf-8-sig") -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding=encoding)
    os.replace(tmp, path)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(str(raw).strip())
    except Exception:
        return default


def queue_limits() -> tuple[int, int]:
    """
    Returns (max_files, max_bytes) for the offline report queue.

    Env overrides:
      - BASELINER_QUEUE_MAX_FILES (default 200)
      - BASELINER_QUEUE_MAX_BYTES (default 50MB)
    """
    max_files = _env_int("BASELINER_QUEUE_MAX_FILES", 200)
    max_bytes = _env_int("BASELINER_QUEUE_MAX_BYTES", 50 * 1024 * 1024)
    # Clamp to sane minimums
    max_files = max(1, max_files)
    max_bytes = max(1024 * 1024, max_bytes)  # at least 1MB
    return max_files, max_bytes


def queue_report(state_dir: str | Path, payload: dict[str, Any]) -> Path:
    qdir = ensure_queue_dir(state_dir)
    rid = str(uuid.uuid4())
    path = qdir / f"{rid}.json"
    data = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
    _atomic_write_text(path, data, encoding="utf-8-sig")
    return path


def iter_queued_reports(state_dir: str | Path) -> list[Path]:
    qdir = ensure_queue_dir(state_dir)
    paths = [p for p in qdir.glob("*.json") if p.is_file()]
    return sorted(paths, key=lambda p: p.stat().st_mtime)


def delete_queued(path: str | Path) -> None:
    p = Path(path)
    try:
        p.unlink(missing_ok=True)
    except TypeError:
        # For older Python compatibility (if needed)
        if p.exists():
            p.unlink()


def prune_queue(
    state_dir: str | Path,
    *,
    max_files: int | None = None,
    max_bytes: int | None = None,
) -> dict[str, int]:
    """
    Enforce queue bounds by deleting oldest queued reports first.

    Returns stats:
      - removed_files
      - removed_bytes
      - kept_files
      - kept_bytes
    """
    if max_files is None or max_bytes is None:
        mf, mb = queue_limits()
        max_files = mf if max_files is None else max_files
        max_bytes = mb if max_bytes is None else max_bytes

    max_files = max(1, int(max_files))
    max_bytes = max(1024 * 1024, int(max_bytes))

    paths = iter_queued_reports(state_dir)

    sizes: dict[Path, int] = {}
    total_bytes = 0
    for p in paths:
        try:
            sz = int(p.stat().st_size)
        except Exception:
            sz = 0
        sizes[p] = sz
        total_bytes += sz

    removed_files = 0
    removed_bytes = 0

    def _drop(p: Path) -> None:
        nonlocal removed_files, removed_bytes, total_bytes
        sz = sizes.get(p, 0)
        delete_queued(p)
        removed_files += 1
        removed_bytes += sz
        total_bytes = max(0, total_bytes - sz)

    # Enforce max_files first (oldest-first)
    while len(paths) > max_files and paths:
        p = paths.pop(0)
        _drop(p)

    # Enforce max_bytes next (oldest-first)
    while total_bytes > max_bytes and paths:
        p = paths.pop(0)
        _drop(p)

    kept_files = len(paths)
    kept_bytes = total_bytes

    return {
        "removed_files": removed_files,
        "removed_bytes": removed_bytes,
        "kept_files": kept_files,
        "kept_bytes": kept_bytes,
    }
