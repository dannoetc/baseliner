import platform
import socket
from typing import Any
import hashlib
import json

from .http_client import ApiClient
from .reporting import utcnow_iso, truncate, queue_report, iter_queued_reports, delete_queued
from .state import AgentState
from .powershell import run_ps
from .winget import list_package, install_package, upgrade_package, installed_from_list_output, parse_version_from_list_output


def _device_facts() -> dict[str, Any]:
    return {
        "hostname": socket.gethostname(),
        "os": "windows",
        "os_version": platform.version(),
        "arch": platform.machine(),
    }

def _canonical_policy_hash(pol: dict[str, Any]) -> str:
    """
    Fallback hash when server returns effective_policy_hash = null.
    Hash a stable subset of the policy response.
    """
    payload = {
        "policy_id": pol.get("policy_id"),
        "policy_name": pol.get("policy_name"),
        "schema_version": pol.get("schema_version"),
        "mode": pol.get("mode"),
        "document": pol.get("document") or {},
        "sources": pol.get("sources") or [],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

def enroll_device(server: str, enroll_token: str, device_key: str, tags: dict[str, Any], state_dir: str) -> None:
    state = AgentState.load(state_dir)
    client = ApiClient(server)

    payload = {
        "enroll_token": enroll_token,
        "device_key": device_key,
        **_device_facts(),
        "agent_version": state.agent_version,
        "tags": tags or {},
    }

    resp = client.post_json("/api/v1/enroll", payload)
    state.device_id = resp.get("device_id")
    state.device_key = device_key
    device_token = resp.get("device_token")
    if not device_token:
        raise RuntimeError("Enroll succeeded but device_token missing in response")

    state.save_device_token(state_dir, device_token)
    state.save(state_dir)
    print(f"[OK] Enrolled device_id={state.device_id} device_key={state.device_key}")


def run_once(server: str, state_dir: str, force: bool = False) -> None:
    state = AgentState.load(state_dir)
    token = state.load_device_token(state_dir)
    client = ApiClient(server, device_token=token)

    _flush_queue(client, state_dir)

    pol = client.get_json("/api/v1/device/policy")
    server_hash = pol.get("effective_policy_hash")
    effective_hash = server_hash or _canonical_policy_hash(pol)
    mode = pol.get("mode", "enforce")
    doc = pol.get("document") or {}
    resources = doc.get("resources") or []

    if not force and effective_hash and state.last_policy_hash == effective_hash:
        print("[OK] Policy hash unchanged; skipping run (use --force to override).")
        return

    started = utcnow_iso()
    logs: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    logs.append({"level": "info", "message": "Run started", "data": {"mode": mode, "resources": len(resources)}})

    ordinal = 0
    ok = 0
    failed = 0

    for res in resources:
        rtype = (res.get("type") or "").strip()
        rid = (res.get("id") or "").strip()
        name = res.get("name")

        if not rtype or not rid:
            continue

        if rtype == "winget.package":
            item, item_logs, success = _run_winget_package(res, ordinal, mode)
        elif rtype == "script.powershell":
            item, item_logs, success = _run_script_powershell(res, ordinal, mode)
        else:
            item = {
                "resource_type": rtype,
                "resource_id": rid,
                "name": name,
                "ordinal": ordinal,
                "changed": False,
                "reboot_required": False,
                "status_detect": "skipped",
                "status_remediate": "skipped",
                "status_validate": "skipped",
                "evidence": {},
                "error": {"message": "Unsupported resource type (MVP)", "type": "unsupported_resource"},
            }
            item_logs = [{"level": "warning", "message": "Unsupported resource type", "data": {"type": rtype, "id": rid}, "run_item_ordinal": ordinal}]
            success = False

        items.append(item)
        logs.extend(item_logs)

        if success:
            ok += 1
        else:
            failed += 1

        ordinal += 1

    ended = utcnow_iso()
    status = "succeeded" if failed == 0 else "failed"
    logs.append({"ts": utcnow_iso(),"level": "info", "message": "Run finished", "data": {"ok": ok, "failed": failed, "status": status}})

    report = {
        "started_at": started,
        "ended_at": ended,
        "status": status,
        "agent_version": state.agent_version,
        "effective_policy_hash": effective_hash,
        "policy_snapshot": {
            "policy_id": pol.get("policy_id"),
            "policy_name": pol.get("policy_name"),
            "effective_policy_hash": effective_hash,
        },
        "summary": {"itemsTotal": len(items), "ok": ok, "failed": failed},
        "items": items,
        "logs": logs,
    }

    try:
        resp = client.post_json("/api/v1/device/reports", report, retries=1)
        run_id = resp.get("run_id")
        print(f"[OK] Posted report run_id={run_id}")
        state.last_policy_hash = effective_hash
        state.save(state_dir)
    except Exception as e:
        path = queue_report(state_dir, report)
        print(f"[WARN] Failed to post report ({e}); queued at {path}")


def _flush_queue(client: ApiClient, state_dir: str) -> None:
    queued = iter_queued_reports(state_dir)
    if not queued:
        return
    for path in queued[:20]:
        try:
            import json
            report = json.loads(path.read_text(encoding="utf-8"))
            client.post_json("/api/v1/device/reports", report, retries=1)
            delete_queued(path)
            print(f"[OK] Flushed queued report: {path.name}")
        except Exception:
            break

def _run_script_powershell(res: dict[str, Any], ordinal: int, mode: str) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
    rid = str(res.get("id"))
    name = res.get("name") or rid
    detect_script = (res.get("detect") or "").strip()
    remediate_script = (res.get("remediate") or "").strip()

    logs: list[dict[str, Any]] = []
    started_at = utcnow_iso()

    if not detect_script:
        item = {
            "resource_type": "script.powershell",
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
            "evidence": {},
            "error": {"type": "invalid_resource", "message": "script.powershell missing detect"},
        }
        logs.append({"ts": utcnow_iso(), "level": "error", "message": "script.powershell missing detect", "data": {"id": rid}, "run_item_ordinal": ordinal})
        return item, logs, False

    # DETECT
    det = run_ps(detect_script, timeout_s=120)
    compliant_before = (det.exit_code == 0)
    evidence: dict[str, Any] = {
        "detect": {
            "engine": det.engine,
            "exit_code": det.exit_code,
            "stdout": truncate(det.stdout),
            "stderr": truncate(det.stderr),
        }
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
            logs.append({"ts": utcnow_iso(), "level": "error", "message": "Noncompliant but no remediate script provided", "data": {"id": rid}, "run_item_ordinal": ordinal})
        else:
            rem = run_ps(remediate_script, timeout_s=300)
            status_remediate = "ok" if rem.exit_code == 0 else "fail"
            evidence["remediate"] = {
                "engine": rem.engine,
                "exit_code": rem.exit_code,
                "stdout": truncate(rem.stdout),
                "stderr": truncate(rem.stderr),
            }
            changed = (rem.exit_code == 0)

            if rem.exit_code != 0:
                success = False
                error = {"type": "remediate_failed", "message": "Remediate script failed", "exit_code": rem.exit_code}

    # VALIDATE (re-run detect)
    val = run_ps(detect_script, timeout_s=120)
    compliant_after = (val.exit_code == 0)
    status_validate = "ok" if val.exit_code == 0 else "fail"
    evidence["validate"] = {
        "engine": val.engine,
        "exit_code": val.exit_code,
        "stdout": truncate(val.stdout),
        "stderr": truncate(val.stderr),
    }

    if mode == "audit":
        # In audit mode we did detect + validate (same thing) effectively.
        # "changed" remains False.
        pass

    if not compliant_after:
        success = False
        error = error or {"type": "still_noncompliant", "message": "Detect still failing after remediation"}

    ended_at = utcnow_iso()

    item = {
        "resource_type": "script.powershell",
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

    logs.append({"ts": utcnow_iso(), "level": "info" if success else "error", "message": "script.powershell processed", "data": {"id": rid, "success": success, "changed": changed}, "run_item_ordinal": ordinal})
    return item, logs, success

def _run_winget_package(res: dict[str, Any], ordinal: int, mode: str) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
    package_id = str(res.get("id"))
    ensure = (res.get("ensure") or "present").lower()
    allow_upgrade = bool(res.get("allowUpgrade") or res.get("allow_upgrade") or False)
    min_version = res.get("minVersion") or res.get("min_version")

    logs: list[dict[str, Any]] = []
    started_at = utcnow_iso()

    detect = list_package(package_id)

    installed = installed_from_list_output(detect.stdout, package_id) and detect.exit_code == 0
    installed_ver = parse_version_from_list_output(detect.stdout, package_id)

    compliant_before = installed if ensure == "present" else (not installed)

    evidence = {
        "detect": {
            "exit_code": detect.exit_code,
            "stdout": truncate(detect.stdout),
            "stderr": truncate(detect.stderr),
            "installed": installed,
            "version": installed_ver,
        }
    }

    status_detect = "ok" if detect.exit_code == 0 else "fail"
    status_remediate = "skipped"
    status_validate = "skipped"
    changed = False
    reboot_required = False
    error: dict[str, Any] = {}

    # If winget couldn't even run (common under SYSTEM), stop here but report it.
    if detect.exit_code != 0 and (detect.stderr or "").strip():
        err_text = detect.stderr.strip()
        error = {
            "type": "winget_unavailable",
            "message": "winget failed to execute (often happens under SYSTEM/session 0)",
            "detail": truncate(err_text),
            "exit_code": detect.exit_code,
        }
        ended_at = utcnow_iso()
        item = {
            "resource_type": "winget.package",
            "resource_id": package_id,
            "name": res.get("name") or package_id,
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
                "data": {"id": package_id, "stderr": truncate(err_text), "exit_code": detect.exit_code},
                "run_item_ordinal": ordinal,
            }
        )
        return item, logs, False

    def need_remediate() -> bool:
        if ensure != "present":
            return False
        if not installed:
            return True
        if allow_upgrade and min_version and installed_ver:
            return str(installed_ver) < str(min_version)  # MVP compare
        return False

    success = True

    if mode == "audit":
        logs.append({"ts": utcnow_iso(), "level": "info", "message": "Audit mode; skipping remediation", "data": {"id": package_id}, "run_item_ordinal": ordinal})
        status_remediate = "skipped"
    else:
        if need_remediate():
            if not installed:
                rem = install_package(package_id)
                action = "install"
            else:
                rem = upgrade_package(package_id)
                action = "upgrade"

            status_remediate = "ok" if rem.exit_code == 0 else "fail"
            evidence["remediate"] = {"action": action, "exit_code": rem.exit_code, "stdout": truncate(rem.stdout), "stderr": truncate(rem.stderr)}
            changed = rem.exit_code == 0

            if rem.exit_code != 0:
                success = False
                error = {"type": "winget_failed", "message": f"winget {action} failed", "exit_code": rem.exit_code, "detail": truncate(rem.stderr)}
        else:
            status_remediate = "skipped"

    val = list_package(package_id)
    installed_after = installed_from_list_output(val.stdout, package_id) and val.exit_code == 0
    ver_after = parse_version_from_list_output(val.stdout, package_id)

    compliant_after = installed_after if ensure == "present" else (not installed_after)
    status_validate = "ok" if val.exit_code == 0 else "fail"
    evidence["validate"] = {"exit_code": val.exit_code, "stdout": truncate(val.stdout), "stderr": truncate(val.stderr), "installed": installed_after, "version": ver_after}

    if ensure == "present" and not installed_after:
        success = False
        error = error or {"type": "not_installed_after", "message": "Package still not installed after remediation"}

    ended_at = utcnow_iso()

    item = {
        "resource_type": "winget.package",
        "resource_id": package_id,
        "name": res.get("name") or package_id,
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

    logs.append({"ts": utcnow_iso(), "level": "info" if success else "error", "message": "winget.package processed", "data": {"id": package_id, "success": success, "changed": changed}, "run_item_ordinal": ordinal})
    return item, logs, success