from __future__ import annotations

import json
import platform
import socket
import subprocess
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_filename(s: str) -> str:
    bad = '<>:"/\\|?*'
    out: list[str] = []
    for ch in str(s or ""):
        if ch in bad or ord(ch) < 32:
            out.append("_")
        else:
            out.append(ch)
    return "".join(out).strip(" .")


def default_bundle_path(state_dir: str | Path) -> Path:
    sd = Path(state_dir)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    host = _safe_filename(socket.gethostname() or "host")
    return sd / f"support-bundle-{host}-{ts}.zip"


def _iter_files_under(dir_path: Path, *, pattern: str = "*") -> Iterable[Path]:
    if not dir_path.exists() or not dir_path.is_dir():
        return []
    return [p for p in dir_path.glob(pattern) if p.is_file()]


def _filter_by_mtime(paths: list[Path], *, since_epoch: float) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        try:
            if p.stat().st_mtime >= since_epoch:
                out.append(p)
        except Exception:
            pass
    return out


def _take_newest(paths: list[Path], *, max_files: int) -> list[Path]:
    max_files = max(1, int(max_files))
    paths2 = list(paths)
    try:
        paths2.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        pass
    return paths2[:max_files]


def _zip_add_file(zf: zipfile.ZipFile, src: Path, arcname: str) -> None:
    try:
        zf.write(src, arcname=arcname)
    except Exception:
        pass


def _write_json_to_zip(zf: zipfile.ZipFile, arcname: str, payload: dict[str, Any]) -> None:
    try:
        data = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")
        zf.writestr(arcname, data)
    except Exception:
        pass


def _read_json_file(path: Path) -> dict[str, Any] | None:
    """Read JSON from disk, tolerant of UTF-8 BOM (common on Windows)."""
    try:
        if not path.exists() or not path.is_file():
            return None

        # Use utf-8-sig to strip BOM if present.
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8-sig")
        except Exception:
            # Fallback: best-effort utf-8
            text = raw.decode("utf-8", errors="replace")

        return json.loads(text)
    except Exception:
        return None


def _find_first_key(obj: Any, keys: set[str]) -> Any | None:
    """Walk a JSON-ish object and return the value of the first matching key."""
    try:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(k, str) and k in keys:
                    return v
            for v in obj.values():
                found = _find_first_key(v, keys)
                if found is not None:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = _find_first_key(item, keys)
                if found is not None:
                    return found
    except Exception:
        return None
    return None


def _norm(v: Any) -> str | None:
    if v is None:
        return None
    try:
        s = str(v).strip()
        return s if s else None
    except Exception:
        return None


def _collect_policy_summary(state_dir: Path) -> dict[str, Any]:
    """
    Derive a policy summary from state.json.

    Your current state.json uses:
      - last_policy_hash
      - last_applied_policy_hash
      - last_reported_policy_hash
    """
    state = _read_json_file(state_dir / "state.json") or {}

    last_policy_hash = _find_first_key(
        state,
        {
            "last_policy_hash",
            "last_effective_policy_hash",
            "effective_policy_hash",
            "effectivePolicyHash",
            "lastEffectivePolicyHash",
        },
    )

    last_applied_policy_hash = _find_first_key(
        state,
        {
            "last_applied_policy_hash",
            "lastAppliedPolicyHash",
        },
    )

    last_reported_policy_hash = _find_first_key(
        state,
        {
            "last_reported_policy_hash",
            "lastReportedPolicyHash",
        },
    )

    last_observed_state_hash = _find_first_key(
        state,
        {
            "last_observed_state_hash",
            "lastObservedStateHash",
        },
    )
    last_run_status = _find_first_key(state, {"last_run_status", "lastRunStatus"})
    last_run_at = _find_first_key(state, {"last_run_at", "lastRunAt"})
    last_server_url = _find_first_key(state, {"last_server_url", "lastServerUrl"})
    agent_version = _find_first_key(state, {"agent_version", "agentVersion"})
    device_key = _find_first_key(state, {"device_key", "deviceKey"})
    device_id = _find_first_key(state, {"device_id", "deviceId"})

    last_effective_policy_hash = (
        _norm(last_policy_hash) or _norm(last_applied_policy_hash) or _norm(last_reported_policy_hash)
    )

    return {
        "last_effective_policy_hash": last_effective_policy_hash,
        "last_policy_hash": _norm(last_policy_hash),
        "last_applied_policy_hash": _norm(last_applied_policy_hash),
        "last_reported_policy_hash": _norm(last_reported_policy_hash),
        "last_observed_state_hash": _norm(last_observed_state_hash),
        "last_run_status": _norm(last_run_status),
        "last_run_at": _norm(last_run_at),
        "last_server_url": _norm(last_server_url),
        "agent_version": _norm(agent_version),
        "device_key": _norm(device_key),
        "device_id": _norm(device_id),
    }


def _try_run(cmd: list[str], timeout_s: float = 5.0) -> tuple[int | None, str, str, str | None]:
    """Run a command and capture stdout/stderr. Returns (code, out, err, error_str)."""
    try:
        cp = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            shell=False,
        )
        return cp.returncode, (cp.stdout or "").strip(), (cp.stderr or "").strip(), None
    except FileNotFoundError:
        return None, "", "", "not_found"
    except subprocess.TimeoutExpired:
        return None, "", "", "timeout"
    except Exception as e:
        return None, "", "", f"error:{type(e).__name__}"


def _collect_winget_diagnostics(winget_path_hint: str | None) -> dict[str, Any]:
    candidates: list[str] = []
    if winget_path_hint:
        candidates.append(str(winget_path_hint))
    candidates.append("winget")

    diag: dict[str, Any] = {
        "hint": winget_path_hint,
        "attempts": [],
        "resolved_exe": None,
        "version": None,
    }

    for exe in candidates:
        for args in (["--version"], ["-v"]):
            cmd = [exe, *args]
            code, out, err, error = _try_run(cmd, timeout_s=5.0)
            attempt = {
                "cmd": cmd,
                "returncode": code,
                "stdout": out,
                "stderr": err,
                "error": error,
            }
            diag["attempts"].append(attempt)

            if error is None and code == 0:
                diag["resolved_exe"] = exe
                diag["version"] = out or None
                return diag

    for exe in candidates:
        cmd = [exe, "--info"]
        code, out, err, error = _try_run(cmd, timeout_s=5.0)
        attempt = {
            "cmd": cmd,
            "returncode": code,
            "stdout": out,
            "stderr": err,
            "error": error,
        }
        diag["attempts"].append(attempt)
        if error is None and code == 0:
            diag["resolved_exe"] = exe
            diag["version"] = None
            return diag

    return diag


def create_support_bundle(
    *,
    state_dir: str | Path,
    out_path: str | Path | None = None,
    since_hours: int = 24,
    max_run_logs: int = 50,
    include_queue: bool = True,
    include_config_redacted: dict[str, Any] | None = None,
    winget_path_hint: str | None = None,
    extra_manifest: dict[str, Any] | None = None,
) -> Path:
    sd = Path(state_dir)
    sd.mkdir(parents=True, exist_ok=True)

    out = Path(out_path) if out_path else default_bundle_path(sd)
    out.parent.mkdir(parents=True, exist_ok=True)

    since_hours = int(since_hours)
    if since_hours < 0:
        since_hours = 0

    now = time.time()
    since_epoch = now - (since_hours * 3600)

    state_json = sd / "state.json"
    health_json = sd / "health.json"
    agent_log = sd / "logs" / "agent.log"

    run_logs_dir = sd / "logs" / "runs"
    run_logs = list(_iter_files_under(run_logs_dir, pattern="*.jsonl"))
    run_logs = _filter_by_mtime(run_logs, since_epoch=since_epoch) if since_hours else run_logs
    run_logs = _take_newest(run_logs, max_files=max_run_logs)

    queue_dir = sd / "queue"
    queued = list(_iter_files_under(queue_dir, pattern="*.json")) if include_queue else []
    queued = _filter_by_mtime(queued, since_epoch=since_epoch) if include_queue and since_hours else queued

    token_dpapi = sd / "device_token.dpapi"

    policy_summary = _collect_policy_summary(sd)
    winget_diag = _collect_winget_diagnostics(winget_path_hint)

    manifest: dict[str, Any] = {
        "created_at": _utc_now_iso(),
        "state_dir": str(sd),
        "bundle_path": str(out),
        "filters": {
            "since_hours": since_hours,
            "max_run_logs": int(max_run_logs),
            "include_queue": bool(include_queue),
        },
        "host": {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "policy": policy_summary,
        "diagnostics": {
            "winget": {
                "hint": winget_path_hint,
                "resolved_exe": winget_diag.get("resolved_exe"),
                "version": winget_diag.get("version"),
            }
        },
        "files": {"included": [], "skipped": []},
    }

    if extra_manifest:
        try:
            manifest.update(extra_manifest)
        except Exception:
            pass

    included: list[str] = []
    skipped: list[str] = []

    def _maybe_add(src: Path, arc: str) -> None:
        if src.exists() and src.is_file():
            _zip_add_file(zf, src, arc)
            included.append(arc)
        else:
            skipped.append(arc)

    with zipfile.ZipFile(out, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        _maybe_add(state_json, "state.json")
        _maybe_add(health_json, "health.json")
        _maybe_add(agent_log, "logs/agent.log")

        for p in run_logs:
            _zip_add_file(zf, p, f"logs/runs/{p.name}")
            included.append(f"logs/runs/{p.name}")

        for p in queued:
            _zip_add_file(zf, p, f"queue/{p.name}")
            included.append(f"queue/{p.name}")

        if token_dpapi.exists():
            skipped.append("device_token.dpapi (excluded)")

        if include_config_redacted is not None:
            _write_json_to_zip(zf, "config/redacted.json", include_config_redacted)
            included.append("config/redacted.json")
        else:
            skipped.append("config/redacted.json")

        _write_json_to_zip(zf, "policy/summary.json", policy_summary)
        included.append("policy/summary.json")

        _write_json_to_zip(zf, "diagnostics/winget.json", winget_diag)
        included.append("diagnostics/winget.json")

        manifest["files"]["included"] = included
        manifest["files"]["skipped"] = skipped
        _write_json_to_zip(zf, "manifest.json", manifest)

    return out
