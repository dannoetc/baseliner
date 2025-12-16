import platform
import socket
from typing import Any
import hashlib
import json
import os
import uuid

from .http_client import ApiClient
from .reporting import (
    utcnow_iso,
    truncate,
    queue_report,
    iter_queued_reports,
    delete_queued,
    prune_queue,
    queue_limits,
)
from .local_logging import prune_run_logs, new_run_log_path, log_event
from .agent_health import write_health
from .state import AgentState
from .powershell import run_ps
from .winget import (
    list_package,
    install_package,
    upgrade_package,
    installed_from_list_output,
    parse_version_from_list_output,
)

from .engine import PolicyEngine
from .resources import default_handlers


def _device_facts() -> dict[str, Any]:
    os_name = (platform.system() or "").lower() or "unknown"
    return {
        "hostname": socket.gethostname(),
        "os": os_name,
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


def _compute_observed_state_hash(items: list[dict[str, Any]]) -> str:
    """Compute a stable hash of the locally-observed state.

    This intentionally avoids hashing raw stdout/stderr (often noisy). Instead we
    hash a small, stable fingerprint per resource.
    """
    fps: list[dict[str, Any]] = []
    for it in items:
        rtype = it.get("resource_type")
        rid = it.get("resource_id")
        ev = it.get("evidence") or {}

        fp: dict[str, Any] = {
            "resource_type": rtype,
            "resource_id": rid,
            "compliant_after": it.get("compliant_after"),
        }

        detect = (ev.get("detect") or {})
        validate = (ev.get("validate") or {})

        if rtype == "winget.package":
            fp["installed"] = validate.get("installed", detect.get("installed"))
            fp["version"] = validate.get("version", detect.get("version"))
        elif rtype == "script.powershell":
            fp["exit_code"] = validate.get("exit_code", detect.get("exit_code"))
        else:
            fp["status_validate"] = it.get("status_validate")

        fps.append(fp)

    fps_sorted = sorted(fps, key=lambda x: (str(x.get("resource_type")), str(x.get("resource_id"))))
    canonical = json.dumps(fps_sorted, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
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
    # Keep local run logs bounded
    prune_run_logs(state_dir)

    state = AgentState.load(state_dir)
    state.last_server_url = server
    token = state.load_device_token(state_dir)
    client = ApiClient(server, device_token=token)

    local_run_id = str(uuid.uuid4())
    started = utcnow_iso()
    run_log = new_run_log_path(state_dir, started, local_run_id)

    log_event(
        run_log,
        {
            "ts": started,
            "level": "info",
            "event": "run_start",
            "local_run_id": local_run_id,
            "server": server,
            "device_id": state.device_id,
            "device_key": state.device_key,
            "agent_version": state.agent_version,
            "force": bool(force),
        },
    )

    _flush_queue(client, state, state_dir, run_log=run_log, local_run_id=local_run_id)

    pol = client.get_json("/api/v1/device/policy")
    server_hash = pol.get("effective_policy_hash")
    effective_hash = server_hash or _canonical_policy_hash(pol)
    mode = pol.get("mode", "enforce")
    doc = pol.get("document") or {}
    resources = doc.get("resources") or []

    log_event(
        run_log,
        {
            "ts": utcnow_iso(),
            "level": "info",
            "event": "policy_fetched",
            "local_run_id": local_run_id,
            "mode": mode,
            "effective_policy_hash": effective_hash,
            "resources_count": len(resources),
            "policy_id": pol.get("policy_id"),
            "policy_name": pol.get("policy_name"),
        },
    )

    logs: list[dict[str, Any]] = []
    logs.append({"level": "info", "message": "Run started", "data": {"mode": mode, "resources": len(resources)}})

    engine = PolicyEngine(default_handlers())
    eng = engine.run(resources, mode=mode)

    items: list[dict[str, Any]] = eng.items
    logs.extend(eng.logs)
    ok = eng.ok
    failed = eng.failed

    for ir in eng.results:
        item = ir.item
        success = ir.success
        ordinal = int(item.get("ordinal") or 0)

        log_event(
            run_log,
            {
                "ts": utcnow_iso(),
                "level": "info" if success else "error",
                "event": "run_item_result",
                "local_run_id": local_run_id,
                "ordinal": ordinal,
                "resource_type": item.get("resource_type"),
                "resource_id": item.get("resource_id"),
                "status_detect": item.get("status_detect"),
                "status_remediate": item.get("status_remediate"),
                "status_validate": item.get("status_validate"),
                "changed": bool(item.get("changed")),
                "compliant_before": item.get("compliant_before"),
                "compliant_after": item.get("compliant_after"),
            },
        )

    ended = utcnow_iso()
    status = "succeeded" if failed == 0 else "failed"
    logs.append({"ts": utcnow_iso(), "level": "info", "message": "Run finished", "data": {"ok": ok, "failed": failed, "status": status}})

    observed_state_hash = _compute_observed_state_hash(items)

    log_event(
        run_log,
        {
            "ts": utcnow_iso(),
            "level": "info",
            "event": "run_summary",
            "local_run_id": local_run_id,
            "status": status,
            "ok": ok,
            "failed": failed,
            "items_total": len(items),
            "observed_state_hash": observed_state_hash,
        },
    )

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
        "summary": {"itemsTotal": len(items), "ok": ok, "failed": failed, "observed_state_hash": observed_state_hash},
        "items": items,
        "logs": logs,
    }

    # Update local state as soon as we finish a run, regardless of reporting success.
    state.last_run_at = ended
    state.last_applied_policy_hash = effective_hash
    state.last_observed_state_hash = observed_state_hash
    state.last_run_status = status
    state.last_run_exit = 0 if status == "succeeded" else 1

    if status == "succeeded":
        state.last_success_at = ended
        state.consecutive_failures = 0
    else:
        state.last_failed_at = ended
        state.consecutive_failures = int(state.consecutive_failures or 0) + 1

    state.save(state_dir)

    # Always write health.json at end of run (even if reporting fails)
    try:
        hp = write_health(state_dir, state=state)
        log_event(
            run_log,
            {"ts": utcnow_iso(), "level": "info", "event": "health_written", "local_run_id": local_run_id, "path": str(hp)},
        )
    except Exception as e:
        log_event(
            run_log,
            {"ts": utcnow_iso(), "level": "warning", "event": "health_write_failed", "local_run_id": local_run_id, "error": str(e)},
        )

    try:
        resp = client.post_json("/api/v1/device/reports", report, retries=1)
        run_id = resp.get("run_id")
        print(f"[OK] Posted report run_id={run_id}")

        state.last_reported_policy_hash = effective_hash
        state.last_http_ok_at = utcnow_iso()
        state.save(state_dir)

        # refresh health after successful POST
        try:
            write_health(state_dir, state=state)
        except Exception:
            pass

        log_event(
            run_log,
            {
                "ts": utcnow_iso(),
                "level": "info",
                "event": "report_posted",
                "local_run_id": local_run_id,
                "server_run_id": run_id,
                "effective_policy_hash": effective_hash,
            },
        )
    except Exception as e:
        # Bound the queue before and after adding a new report.
        mf, mb = queue_limits()
        stats1 = prune_queue(state_dir, max_files=mf, max_bytes=mb)
        if stats1.get("removed_files", 0) > 0:
            print(f"[WARN] Pruned queued reports before enqueue: removed_files={stats1['removed_files']} removed_bytes={stats1['removed_bytes']}")

        path = queue_report(state_dir, report)
        print(f"[WARN] Failed to post report ({e}); queued at {path}")

        log_event(
            run_log,
            {
                "ts": utcnow_iso(),
                "level": "warning",
                "event": "report_queued",
                "local_run_id": local_run_id,
                "error": str(e),
                "queued_path": str(path),
                "effective_policy_hash": effective_hash,
            },
        )

        stats2 = prune_queue(state_dir, max_files=mf, max_bytes=mb)
        if stats2.get("removed_files", 0) > 0:
            print(f"[WARN] Pruned queued reports after enqueue: removed_files={stats2['removed_files']} removed_bytes={stats2['removed_bytes']}")

        # refresh health after enqueue attempt
        try:
            write_health(state_dir, state=state)
        except Exception:
            pass


def _flush_queue(client: ApiClient, state: AgentState, state_dir: str, *, run_log=None, local_run_id: str | None = None) -> None:
    # Always bound the queue first (oldest-first deletion).
    mf, mb = queue_limits()
    stats = prune_queue(state_dir, max_files=mf, max_bytes=mb)
    if stats.get("removed_files", 0) > 0:
        print(f"[WARN] Pruned queued reports: removed_files={stats['removed_files']} removed_bytes={stats['removed_bytes']}")

        if run_log is not None:
            log_event(
                run_log,
                {
                    "ts": utcnow_iso(),
                    "level": "warning",
                    "event": "queue_pruned",
                    "local_run_id": local_run_id,
                    "removed_files": stats.get("removed_files"),
                    "removed_bytes": stats.get("removed_bytes"),
                },
            )

    queued = iter_queued_reports(state_dir)
    if not queued:
        return

    if run_log is not None:
        log_event(
            run_log,
            {
                "ts": utcnow_iso(),
                "level": "info",
                "event": "queue_flush_start",
                "local_run_id": local_run_id,
                "queued_count": len(queued),
            },
        )

    changed = False
    flushed = 0
    for path in queued[:20]:
        try:
            report = json.loads(path.read_text(encoding="utf-8-sig"))
            client.post_json("/api/v1/device/reports", report, retries=1)
            delete_queued(path)
            flushed += 1
            print(f"[OK] Flushed queued report: {path.name}")

            effective_hash = report.get("effective_policy_hash")
            if effective_hash:
                state.last_reported_policy_hash = str(effective_hash)
                state.last_http_ok_at = utcnow_iso()
                changed = True
        except Exception as e:
            if run_log is not None:
                log_event(
                    run_log,
                    {
                        "ts": utcnow_iso(),
                        "level": "warning",
                        "event": "queue_flush_error",
                        "local_run_id": local_run_id,
                        "error": str(e),
                        "stopped_after_flushed": flushed,
                    },
                )
            break

    if run_log is not None:
        log_event(
            run_log,
            {
                "ts": utcnow_iso(),
                "level": "info",
                "event": "queue_flush_end",
                "local_run_id": local_run_id,
                "flushed": flushed,
            },
        )

    if changed:
        state.save(state_dir)
        try:
            write_health(state_dir, state=state)
        except Exception:
            pass


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
