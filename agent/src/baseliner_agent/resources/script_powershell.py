from __future__ import annotations

import os
from typing import Any

from baseliner_agent.engine import ItemResult
from baseliner_agent.powershell import run_ps, run_ps_file
from baseliner_agent.reporting import truncate, utcnow_iso


def _coerce_int(v: Any) -> int | None:
    try:
        if v is None or isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            return int(v)
        if isinstance(v, str) and v.strip():
            return int(float(v.strip()))
    except Exception:
        return None
    return None


def _timeout_seconds(res: dict[str, Any]) -> int:
    """
    Per-resource timeout for PowerShell remediation.

    Supported keys:
      - timeout_seconds / timeoutSeconds
      - remediation_timeout_seconds / remediationTimeoutSeconds
      - timeout_s / timeout

    Fallback env: BASELINER_POWERSHELL_TIMEOUT_SECONDS
    """
    for k in (
        "remediation_timeout_seconds",
        "remediationTimeoutSeconds",
        "timeout_seconds",
        "timeoutSeconds",
        "timeout_s",
        "timeout",
    ):
        n = _coerce_int(res.get(k))
        if n is not None:
            return max(10, min(7200, n))

    n = _coerce_int(os.environ.get("BASELINER_POWERSHELL_TIMEOUT_SECONDS"))
    if n is not None:
        return max(10, min(7200, n))

    return 300


def _pick_script(res: dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = res.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _pick_path(res: dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = res.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _script_source(res: dict[str, Any], *, detect: bool) -> str | None:
    if detect:
        for k in ("detect", "script", "check", "test"):
            v = res.get(k)
            if isinstance(v, str) and v.strip():
                return k
        return None

    for k in ("remediate", "remediation", "fix", "remediate_script"):
        v = res.get(k)
        if isinstance(v, str) and v.strip():
            return k
    return None


class PowerShellScriptHandler:
    resource_type = "script.powershell"

    def run(self, res: dict[str, Any], *, ordinal: int, mode: str) -> ItemResult:
        rid = str(res.get("id") or "").strip() or "powershell"
        name = (res.get("name") or rid)

        # Detect can be inline script or a script path.
        detect_script = _pick_script(res, "detect", "script", "check", "test")
        detect_path = _pick_path(res, "detect_path", "detectPath", "path")

        # Remediate can be inline script or a script path.
        remediate_script = _pick_script(res, "remediate", "remediation", "fix", "remediate_script")
        remediate_path = _pick_path(
            res,
            "remediate_path",
            "remediatePath",
            "remediation_path",
            "remediationPath",
            "fix_path",
            "fixPath",
        )

        detect_src = _script_source(res, detect=True)
        remediate_src = _script_source(res, detect=False)

        logs: list[dict[str, Any]] = []
        started_at = utcnow_iso()

        remediate_timeout_s = _timeout_seconds(res)
        detect_timeout_s = min(120, remediate_timeout_s)
        validate_timeout_s = detect_timeout_s

        if not detect_script and not detect_path:
            item = {
                "resource_type": self.resource_type,
                "resource_id": rid,
                "name": name,
                "ordinal": ordinal,
                "compliant_before": None,
                "compliant_after": None,
                "changed": False,
                "reboot_required": False,
                "status_detect": "failed",
                "status_remediate": "skipped",
                "status_validate": "skipped",
                "started_at": started_at,
                "ended_at": utcnow_iso(),
                "evidence": {"meta": {"detect_source": detect_src, "remediate_source": remediate_src}},
                "error": {"type": "invalid_resource", "message": "script.powershell missing detect/script or path"},
            }
            logs.append(
                {
                    "ts": utcnow_iso(),
                    "level": "error",
                    "message": "script.powershell missing detect/script or path",
                    "data": {"id": rid},
                    "run_item_ordinal": ordinal,
                }
            )
            return ItemResult(item=item, logs=logs, success=False)

        # DETECT
        if detect_script:
            det = run_ps(detect_script, timeout_s=detect_timeout_s)
            detect_kind = "inline"
        else:
            det = run_ps_file(detect_path, timeout_s=detect_timeout_s)
            detect_kind = "file"
        compliant_before = det.exit_code == 0

        evidence: dict[str, Any] = {
            "meta": {
                "detect_source": detect_src,
                "remediate_source": remediate_src,
                "detect_kind": detect_kind,
                "timeouts": {
                    "detect_seconds": detect_timeout_s,
                    "remediate_seconds": remediate_timeout_s,
                    "validate_seconds": validate_timeout_s,
                },
            },
            "detect": {
                "engine": det.engine,
                "exit_code": det.exit_code,
                "stdout": truncate(det.stdout),
                "stderr": truncate(det.stderr),
            },
        }
        status_detect = "ok" if det.exit_code == 0 else "fail"

        if det.exit_code == 124:
            item = {
                "resource_type": self.resource_type,
                "resource_id": rid,
                "name": name,
                "ordinal": ordinal,
                "compliant_before": None,
                "compliant_after": None,
                "changed": False,
                "reboot_required": False,
                "status_detect": "fail",
                "status_remediate": "skipped",
                "status_validate": "skipped",
                "started_at": started_at,
                "ended_at": utcnow_iso(),
                "evidence": evidence,
                "error": {"type": "timeout", "message": f"Detect timed out after {detect_timeout_s}s"},
            }
            logs.append(
                {
                    "ts": utcnow_iso(),
                    "level": "error",
                    "message": "script.powershell detect timed out",
                    "data": {"id": rid, "timeout_s": detect_timeout_s},
                    "run_item_ordinal": ordinal,
                }
            )
            return ItemResult(item=item, logs=logs, success=False)

        status_remediate = "skipped"
        status_validate = "skipped"
        changed = False
        error: dict[str, Any] = {}
        success = True

        # REMEDIATE
        if not compliant_before and mode != "audit":
            if not remediate_script and not remediate_path:
                success = False
                error = {"type": "no_remediate", "message": "Noncompliant but no remediate script/path provided"}
            else:
                if remediate_script:
                    rem = run_ps(remediate_script, timeout_s=remediate_timeout_s)
                    remediate_kind = "inline"
                else:
                    rem = run_ps_file(remediate_path, timeout_s=remediate_timeout_s)
                    remediate_kind = "file"
                status_remediate = "ok" if rem.exit_code == 0 else "fail"
                evidence["remediate"] = {
                    "engine": rem.engine,
                    "exit_code": rem.exit_code,
                    "stdout": truncate(rem.stdout),
                    "stderr": truncate(rem.stderr),
                    "kind": remediate_kind,
                }
                changed = rem.exit_code == 0

                if rem.exit_code == 124:
                    success = False
                    error = {"type": "timeout", "message": f"Remediate timed out after {remediate_timeout_s}s"}
                elif rem.exit_code != 0:
                    success = False
                    error = {
                        "type": "remediate_failed",
                        "message": "Remediate script failed",
                        "exit_code": rem.exit_code,
                    }

        # VALIDATE (re-run detect)
        if detect_script:
            val = run_ps(detect_script, timeout_s=validate_timeout_s)
        else:
            val = run_ps_file(detect_path, timeout_s=validate_timeout_s)
        compliant_after = val.exit_code == 0
        status_validate = "ok" if val.exit_code == 0 else "fail"
        evidence["validate"] = {
            "engine": val.engine,
            "exit_code": val.exit_code,
            "stdout": truncate(val.stdout),
            "stderr": truncate(val.stderr),
        }

        if val.exit_code == 124:
            success = False
            error = {"type": "timeout", "message": f"Validate timed out after {validate_timeout_s}s"}
        elif not compliant_after:
            success = False
            error = error or {"type": "still_noncompliant", "message": "Detect still failing after remediation"}
        else:
            # If remediation timed out but validate proves compliance, clear the timeout error.
            if error.get("type") == "timeout":
                error = {}
                success = True

        item = {
            "resource_type": self.resource_type,
            "resource_id": rid,
            "name": name,
            "ordinal": ordinal,
            "compliant_before": compliant_before,
            "compliant_after": compliant_after,
            "changed": changed,
            "reboot_required": False,
            "status_detect": status_detect,
            "status_remediate": status_remediate,
            "status_validate": status_validate,
            "started_at": started_at,
            "ended_at": utcnow_iso(),
            "evidence": evidence,
            "error": error,
        }

        logs.append(
            {
                "ts": utcnow_iso(),
                "level": "info" if success else "error",
                "message": "script.powershell processed",
                "data": {"id": rid, "success": success, "changed": changed},
                "run_item_ordinal": ordinal,
            }
        )
        return ItemResult(item=item, logs=logs, success=success)
