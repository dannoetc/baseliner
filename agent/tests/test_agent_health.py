from __future__ import annotations

import os
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

# Stub Windows-only DPAPI bindings so imports succeed on non-Windows test hosts.
sys.modules.setdefault(
    "baseliner_agent.security.dpapi",
    types.SimpleNamespace(protect_bytes=lambda b: b, unprotect_bytes=lambda b: b),
)

from baseliner_agent.agent_health import _latest_run_log


def test_latest_run_log_prefers_jsonl(tmp_path: Path) -> None:
    runs_dir = tmp_path / "logs" / "runs"
    runs_dir.mkdir(parents=True)

    old_log = runs_dir / "2024-01-01__abc.jsonl"
    new_log = runs_dir / "2024-02-01__xyz.jsonl"
    ignored_log = runs_dir / "should_ignore.log"

    old_log.write_text("{}\n", encoding="utf-8")
    new_log.write_text("{}\n", encoding="utf-8")
    ignored_log.write_text("legacy\n", encoding="utf-8")

    now = time.time()
    os.utime(old_log, (now - 10, now - 10))
    os.utime(new_log, (now - 1, now - 1))
    os.utime(ignored_log, (now, now))

    latest = _latest_run_log(tmp_path)

    assert latest["latest_path"] == str(new_log)
    assert latest["latest_mtime"] is not None
