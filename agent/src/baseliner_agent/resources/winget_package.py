from __future__ import annotations

import re
import os
from typing import Any

from baseliner_agent.engine import ItemResult
from baseliner_agent.reporting import truncate, utcnow_iso
from baseliner_agent.winget import (
    install_package,
    list_package,
    package_id_exists_ex,
    parse_version_from_list_output,
    uninstall_package,
    upgrade_package,
)

_VERSION_RE = re.compile(r"\d+(?:\.\d+)*")

_DEFAULT_REMEDIATE_TIMEOUT_S = 900


def _get_timeout_seconds(res: dict[str, Any]) -> int:
    """Get per-resource remediation timeout.

    Policy keys supported (first match wins):
      - timeout_seconds / timeoutSeconds
      - remediation_timeout_seconds / remediationTimeoutSeconds
      - timeout_s / timeout

    Fallback: env BASELINER_WINGET_TIMEOUT_SECONDS, else 900s.
    """
    candidates = [
        res.get("remediation_timeout_seconds"),
        res.get("remediationTimeoutSeconds"),
        res.get("timeout_seconds"),
        res.get("timeoutSeconds"),
        res.get("timeout_s"),
        res.get("timeout"),
    ]

    v = None
    for c in candidates:
        if c is None:
            continue
        v = c
        break

    if v is None:
        env = (os.environ.get("BASELINER_WINGET_TIMEOUT_SECONDS") or "").strip()
        if env:
            v = env

    try:
        s = int(float(v)) if v is not None else _DEFAULT_REMEDIATE_TIMEOUT_S
    except Exception:
        s = _DEFAULT_REMEDIATE_TIMEOUT_S

    # Clamp to sane bounds.
    if s < 30:
        s = 30
    if s > 7200:
        s = 7200
    return s


def _normalize_version_str(v: str | None) -> str | None:
    if not v:
        return None
    s = str(v).strip()
    if not s:
        return None
    # Extract first version-ish token when winget outputs extra text
    m = _VERSION_RE.search(s)
    return m.group(0) if m else s


def _version_eq(a: str | None, b: str | None) -> bool:
    a_n = _normalize_version_str(a)
    b_n = _normalize_version_str(b)
    if not a_n or not b_n:
        return False
    return a_n == b_n


def _version_lt(a: str | None, b: str | None) -> bool:
    """
    True iff version a < version b using semantic-ish comparison.
    Uses packaging.version when available; falls back to numeric tuple compare.
    """
    a_n = _normalize_version_str(a)
    b_n = _normalize_version_str(b)
    if not a_n or not b_n:
        return False

    # Preferred: packaging.version (PEP 440)
    try:
        from packaging.version import Version  # type: ignore

        return Version(a_n) < Version(b_n)
    except Exception:
        # Fallback: numeric tuple compare (good for 0.83.0.0, 25.01, etc.)
        def tup(s: str) -> tuple[int, ...]:
            parts: list[int] = []
            for p in s.split("."):
                try:
                    parts.append(int(p))
                except Exception:
                    parts.append(0)
            return tuple(parts)

        ta = tup(a_n)
        tb = tup(b_n)
        n = max(len(ta), len(tb))
        ta = ta + (0,) * (n - len(ta))
        tb = tb + (0,) * (n - len(tb))
        return ta < tb


def _get_winget_catalog_id(res: dict[str, Any]) -> str:
    """
    Policy conventions:
      - res["id"]         = stable Baseliner resource id (e.g. "7zip")
      - res["package_id"] = winget catalog id (e.g. "7zip.7zip")

    Fall back to res["id"] for older policies that don't have package_id yet.
    """
    for k in ("package_id", "packageId", "winget_id", "wingetId", "package"):
        v = res.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    v = res.get("id")
    return str(v).strip() if v is not None else ""


def _get_policy_source_hint(res: dict[str, Any]) -> str | None:
    # Optional policy hint: "winget" or "msstore"
    v = res.get("source")
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None


class WingetPackageHandler:
    resource_type = "winget.package"

    def run(self, res: dict[str, Any], *, ordinal: int, mode: str) -> ItemResult:
        # Stable identifier (for reports / hashing / debugging)
        rid = str(res.get("id") or "").strip() or "winget"
        name = res.get("name") or rid

        # Actual winget catalog identifier
        package_id = _get_winget_catalog_id(res)
        if not package_id:
            started_at = utcnow_iso()
            ended_at = utcnow_iso()
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
                "ended_at": ended_at,
                "evidence": {},
                "error": {"type": "invalid_resource", "message": "winget.package missing package_id"},
            }
            logs = [
                {
                    "ts": ended_at,
                    "level": "error",
                    "message": "winget.package missing package_id",
                    "data": {"id": rid},
                    "run_item_ordinal": ordinal,
                }
            ]
            return ItemResult(item=item, logs=logs, success=False)

        ensure = (res.get("ensure") or "present").lower().strip()
        if ensure not in ("present", "absent"):
            ensure = "present"

        allow_upgrade = bool(res.get("allowUpgrade") or res.get("allow_upgrade") or False)
        min_version = res.get("minVersion") or res.get("min_version")
        min_version = str(min_version).strip() if min_version is not None else None
        if min_version == "":
            min_version = None

        pinned_version = res.get("version") or res.get("pin_version") or res.get("pinned_version")
        pinned_version = str(pinned_version).strip() if pinned_version is not None else None
        if pinned_version == "":
            pinned_version = None

        # Determine which catalog source to use (winget vs msstore).
        # Policy can override; otherwise try preflight.
        source = _get_policy_source_hint(res)
        if not source:
            exists, src, _pre = package_id_exists_ex(package_id)
            if exists and src:
                source = src
            else:
                source = src or "winget"

        logs: list[dict[str, Any]] = []
        started_at = utcnow_iso()

        remediate_timeout_s = _get_timeout_seconds(res)
        detect_timeout_s = min(120, remediate_timeout_s)
        validate_timeout_s = detect_timeout_s

        detect = list_package(package_id, source=source, timeout_s=detect_timeout_s)

        installed_ver = parse_version_from_list_output(detect.stdout, package_id)
        installed = bool(installed_ver) and detect.exit_code == 0
        # NOTE: for some packages, list output may not include a version even when installed.
        # Fall back to a presence check by scanning tokens if parse returns None.
        if not installed and detect.exit_code == 0:
            pid = package_id.strip().lower()
            installed = any(pid == (tok.lower()) for ln in (detect.stdout or "").splitlines() for tok in ln.split())

        if ensure == "present":
            if pinned_version:
                compliant_before = bool(installed) and _version_eq(installed_ver, pinned_version)
            elif allow_upgrade and min_version and installed and installed_ver:
                compliant_before = not _version_lt(installed_ver, min_version)
            else:
                compliant_before = bool(installed)
        else:
            compliant_before = not bool(installed)

        evidence: dict[str, Any] = {
            "detect": {
                "requested_package_id": package_id,
                "source": source,
                "exit_code": detect.exit_code,
                "stdout": truncate(detect.stdout),
                "stderr": truncate(detect.stderr),
                "installed": installed,
                "version": installed_ver,
                "pinned_version": pinned_version,
                "min_version": min_version,
                "allow_upgrade": allow_upgrade,
                "timeout_seconds": detect_timeout_s,
            }
        }

        status_detect = "ok" if detect.exit_code == 0 else "fail"
        status_remediate = "skipped"
        status_validate = "skipped"
        changed = False
        reboot_required = False
        error: dict[str, Any] = {}
        success = True

        # If winget couldn't even run, stop here but report it.
        if detect.exit_code != 0 and (detect.stderr or "").strip():
            err_text = detect.stderr.strip()
            err_type = "timeout" if detect.exit_code == 124 else "winget_unavailable"
            error = {
                "type": err_type,
                "message": "winget detect timed out" if err_type == "timeout" else "winget failed to execute (often happens under SYSTEM/session 0)",
                "detail": truncate(err_text),
                "exit_code": detect.exit_code,
            }
            ended_at = utcnow_iso()
            item = {
                "resource_type": self.resource_type,
                "resource_id": rid,
                "name": name,
                "ordinal": ordinal,
                "compliant_before": compliant_before,
                "compliant_after": None,
                "changed": False,
                "reboot_required": reboot_required,
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
                    "level": "error",
                    "message": "winget.package detect failed",
                    "data": {
                        "id": rid,
                        "package_id": package_id,
                        "source": source,
                        "stderr": truncate(err_text),
                        "exit_code": detect.exit_code,
                        "timeout_seconds": detect_timeout_s,
                    },
                    "run_item_ordinal": ordinal,
                }
            )
            return ItemResult(item=item, logs=logs, success=False)

        def need_remediate_present() -> tuple[bool, str | None]:
            if not installed:
                return (True, "install_pinned" if pinned_version else "install")

            if pinned_version:
                # Installed, but we require an exact version
                if not _version_eq(installed_ver, pinned_version):
                    return (True, "reinstall_pinned")  # uninstall -> install --version --force
                return (False, None)

            if allow_upgrade and min_version and installed_ver:
                if _version_lt(installed_ver, min_version):
                    return (True, "upgrade")

            return (False, None)

        def need_remediate_absent() -> tuple[bool, str | None]:
            if installed:
                return (True, "uninstall")
            return (False, None)

        need, action = (need_remediate_present() if ensure == "present" else need_remediate_absent())

        if mode == "audit":
            logs.append(
                {
                    "ts": utcnow_iso(),
                    "level": "info",
                    "message": "Audit mode; skipping remediation",
                    "data": {"id": rid, "package_id": package_id, "source": source, "ensure": ensure},
                    "run_item_ordinal": ordinal,
                }
            )
            status_remediate = "skipped"
        else:
            if need and action:
                if action == "install":
                    rem = install_package(package_id, source=source, timeout_s=remediate_timeout_s)

                elif action == "install_pinned":
                    rem = install_package(
                        package_id,
                        source=source,
                        version=pinned_version,
                        force=True,
                        timeout_s=remediate_timeout_s,
                    )

                elif action == "reinstall_pinned":
                    rem1 = uninstall_package(package_id, source=source, timeout_s=remediate_timeout_s)
                    rem2 = install_package(
                        package_id,
                        source=source,
                        version=pinned_version,
                        force=True,
                        timeout_s=remediate_timeout_s,
                    )

                    class _Combo:
                        exit_code = 0 if (rem1.exit_code == 0 and rem2.exit_code == 0) else (rem2.exit_code or rem1.exit_code or 1)
                        stdout = (rem1.stdout or "") + ("\n---\n" if (rem1.stdout and rem2.stdout) else "") + (rem2.stdout or "")
                        stderr = (rem1.stderr or "") + ("\n---\n" if (rem1.stderr and rem2.stderr) else "") + (rem2.stderr or "")

                    rem = _Combo()
                    evidence["remediate_steps"] = [
                        {
                            "requested_package_id": package_id,
                            "source": source,
                            "action": "uninstall",
                            "exit_code": rem1.exit_code,
                            "stdout": truncate(rem1.stdout),
                            "stderr": truncate(rem1.stderr),
                        },
                        {
                            "requested_package_id": package_id,
                            "source": source,
                            "action": f"install --version {pinned_version}",
                            "exit_code": rem2.exit_code,
                            "stdout": truncate(rem2.stdout),
                            "stderr": truncate(rem2.stderr),
                        },
                    ]

                elif action == "upgrade":
                    rem = upgrade_package(package_id, source=source, timeout_s=remediate_timeout_s)

                elif action == "uninstall":
                    rem = uninstall_package(package_id, source=source, timeout_s=remediate_timeout_s)

                else:
                    rem = None

                if rem is None:
                    success = False
                    status_remediate = "fail"
                    error = {"type": "invalid_action", "message": f"Unknown remediation action: {action}"}
                else:
                    status_remediate = "ok" if rem.exit_code == 0 else "fail"
                    evidence["remediate"] = {
                        "requested_package_id": package_id,
                        "source": source,
                        "action": action,
                        "exit_code": rem.exit_code,
                        "stdout": truncate(getattr(rem, "stdout", "")),
                        "stderr": truncate(getattr(rem, "stderr", "")),
                        "pinned_version": pinned_version,
                        "timeout_seconds": remediate_timeout_s,
                    }
                    changed = rem.exit_code == 0

                    if rem.exit_code != 0:
                        success = False
                        if rem.exit_code == 124:
                            error = {
                                "type": "timeout",
                                "message": f"winget {action} timed out",
                                "exit_code": rem.exit_code,
                                "detail": truncate(getattr(rem, "stderr", "")),
                            }
                        else:
                            error = {
                                "type": "winget_failed",
                                "message": f"winget {action} failed",
                                "exit_code": rem.exit_code,
                                "detail": truncate(getattr(rem, "stderr", "")),
                            }
            else:
                status_remediate = "skipped"

        # Validate (re-list)
        val = list_package(package_id, source=source, timeout_s=validate_timeout_s)
        ver_after = parse_version_from_list_output(val.stdout, package_id)
        installed_after = bool(ver_after) and val.exit_code == 0
        if not installed_after and val.exit_code == 0:
            pid = package_id.strip().lower()
            installed_after = any(pid == (tok.lower()) for ln in (val.stdout or "").splitlines() for tok in ln.split())

        if ensure == "present":
            if pinned_version:
                compliant_after = bool(installed_after) and _version_eq(ver_after, pinned_version)
            elif allow_upgrade and min_version and installed_after and ver_after:
                compliant_after = not _version_lt(ver_after, min_version)
            else:
                compliant_after = bool(installed_after)
        else:
            compliant_after = not bool(installed_after)

        status_validate = "ok" if val.exit_code == 0 else "fail"
        evidence["validate"] = {
            "requested_package_id": package_id,
            "source": source,
            "exit_code": val.exit_code,
            "stdout": truncate(val.stdout),
            "stderr": truncate(val.stderr),
            "installed": installed_after,
            "version": ver_after,
            "pinned_version": pinned_version,
            "min_version": min_version,
            "allow_upgrade": allow_upgrade,
            "timeout_seconds": validate_timeout_s,
        }

        # Final success gate
        if ensure == "present":
            if not installed_after:
                success = False
                error = error or {"type": "not_installed_after", "message": "Package still not installed after remediation"}
            elif pinned_version and not _version_eq(ver_after, pinned_version):
                success = False
                error = error or {
                    "type": "wrong_version_after",
                    "message": f"Package version '{ver_after}' does not match pinned '{pinned_version}' after remediation",
                }
            elif allow_upgrade and min_version and ver_after and _version_lt(ver_after, min_version):
                success = False
                error = error or {
                    "type": "below_min_version_after",
                    "message": f"Package version '{ver_after}' is below min_version '{min_version}' after remediation",
                }

        if ensure == "absent" and installed_after:
            success = False
            error = error or {"type": "still_installed_after", "message": "Package still installed after remediation"}

        ended_at = utcnow_iso()

        item = {
            "resource_type": self.resource_type,
            "resource_id": rid,
            "name": name,
            "ordinal": ordinal,
            "compliant_before": compliant_before,
            "compliant_after": compliant_after,
            "changed": changed,
            "reboot_required": reboot_required,
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
                "message": "winget.package processed",
                "data": {
                    "id": rid,
                    "package_id": package_id,
                    "source": source,
                    "ensure": ensure,
                    "success": success,
                    "changed": changed,
                    "pinned_version": pinned_version,
                    "min_version": min_version,
                    "allow_upgrade": allow_upgrade,
                },
                "run_item_ordinal": ordinal,
            }
        )

        return ItemResult(item=item, logs=logs, success=success)
