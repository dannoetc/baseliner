from __future__ import annotations

from typing import Any

from baseliner_agent.engine import ItemResult
from baseliner_agent.powershell import run_ps
from baseliner_agent.reporting import truncate, utcnow_iso


def _pick_script(res: dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = res.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _script_source(res: dict[str, Any], *, detect: bool) -> str | None:
    """
    For debugging: tell us which key we ended up using.
    """
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

        # Back-compat:
        # - new style: detect/remediate
        # - old style: script (as detect), remediate_script (as remediate)
        detect_script = _pick_script(res, "detect", "script", "check", "test")
        remediate_script = _pick_script(res, "remediate", "remediation", "fix", "remediate_script")

        detect_src = _script_source(res, detect=True)
        remediate_src = _script_source(res, detect=False)

        logs: list[dict[str, Any]] = []
        started_at = utcnow_iso()

        if not detect_script:
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
                "evidence": {
                    "meta": {
                        "detect_source": detect_src,
                        "remediate_source": remediate_src,
                    }
                },
                "error": {"type": "invalid_resource", "message": "script.powershell missing detect/script"},
            }
            logs.append(
                {
                    "ts": utcnow_iso(),
                    "level": "error",
                    "message": "script.powershell missing detect/script",
                    "data": {"id": rid},
                    "run_item_ordinal": ordinal,
                }
            )
            return ItemResult(item=item, logs=logs, success=False)

        # DETECT
        det = run_ps(detect_script, timeout_s=120)
        compliant_before = det.exit_code == 0
        evidence: dict[str, Any] = {
            "meta": {
                "detect_source": detect_src,
                "remediate_source": remediate_src,
            },
            "detect": {
                "engine": det.engine,
                "exit_code": det.exit_code,
                "stdout": truncate(det.stdout),
                "stderr": truncate(det.stderr),
            },
        }
        status_detect = "ok" if det.exit_code == 0 else "fail"

        status_remediate = "skipped"
        status_validate = "skipped"
        changed = False
        error: dict[str, Any] = {}
        success = True

        # REMEDIATE (only if noncompliant and enforce)
        if not compliant_before and mode != "audit":
            if not remediate_script:
                success = False
                error = {"type": "no_remediate", "message": "Noncompliant but no remediate script provided"}
                logs.append(
                    {
                        "ts": utcnow_iso(),
                        "level": "error",
                        "message": "Noncompliant but no remediate script provided",
                        "data": {"id": rid},
                        "run_item_ordinal": ordinal,
                    }
                )
            else:
                rem = run_ps(remediate_script, timeout_s=300)
                status_remediate = "ok" if rem.exit_code == 0 else "fail"
                evidence["remediate"] = {
                    "engine": rem.engine,
                    "exit_code": rem.exit_code,
                    "stdout": truncate(rem.stdout),
                    "stderr": truncate(rem.stderr),
                }
                changed = rem.exit_code == 0

                if rem.exit_code != 0:
                    success = False
                    error = {"type": "remediate_failed", "message": "Remediate script failed", "exit_code": rem.exit_code}

        # VALIDATE (re-run detect)
        val = run_ps(detect_script, timeout_s=120)
        compliant_after = val.exit_code == 0
        status_validate = "ok" if val.exit_code == 0 else "fail"
        evidence["validate"] = {
            "engine": val.engine,
            "exit_code": val.exit_code,
            "stdout": truncate(val.stdout),
            "stderr": truncate(val.stderr),
        }

        if not compliant_after:
            success = False
            error = error or {"type": "still_noncompliant", "message": "Detect still failing after remediation"}

        ended_at = utcnow_iso()

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
            "ended_at": ended_at,
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
