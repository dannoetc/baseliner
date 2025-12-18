from __future__ import annotations

import hashlib
import json
import platform
import socket
import uuid
from typing import Any

from .agent_health import write_health
from .http_client import ApiClient
from .local_logging import log_event, new_run_log_path, prune_run_logs
from .reporting import (
    delete_queued,
    iter_queued_reports,
    prune_queue,
    queue_limits,
    queue_report,
    utcnow_iso,
)
from .state import AgentState
from .engine import PolicyEngine
from .resources import default_handlers


def _device_facts() -> dict[str, Any]:
    return {
        "hostname": socket.gethostname(),
        "os": "windows",
        "os_version": platform.version(),
        "arch": platform.machine(),
    }


def _offline_report(*, state: AgentState, started: str, ended: str, error: str) -> dict[str, Any]:
    return {
        "started_at": started,
        "ended_at": ended,
        "status": "failed",
        "agent_version": state.agent_version,
        "effective_policy_hash": "",
        "policy_snapshot": {
            "policy_id": None,
            "policy_name": None,
            "effective_policy_hash": "",
        },
        "summary": {
            "itemsTotal": 0,
            "ok": 0,
            "failed": 0,
            "observed_state_hash": "",
            "reason": "policy_fetch_failed",
            "error": error,
        },
        "items": [],
        "logs": [
            {"ts": ended, "level": "error", "message": "Failed to fetch policy; server unreachable", "data": {"error": error}},
        ],
    }


def _canonical_policy_hash(pol: dict[str, Any]) -> str:
    payload = {
        "policy_id": pol.get("policy_id"),
        "policy_name": pol.get("policy_name"),
        "schema_version": pol.get("schema_version"),
        "mode": pol.get("mode"),
        "document": pol.get("document") or {},
        "sources": pol.get("sources") or [],
        "compile": pol.get("compile") or {},
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _compute_observed_state_hash(items: list[dict[str, Any]]) -> str:
    fps: list[dict[str, Any]] = []

    for it in items:
        rtype = it.get("resource_type")
        rid = it.get("resource_id")
        ev = it.get("evidence") or {}

        fp: dict[str, Any] = {
            "resource_type": rtype,
            "resource_id": rid,
            "compliant_after": it.get("compliant_after"),
            "changed": bool(it.get("changed")),
        }

        detect = (ev.get("detect") or {}) if isinstance(ev, dict) else {}
        validate = (ev.get("validate") or {}) if isinstance(ev, dict) else {}

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
    prune_run_logs(state_dir)

    state = AgentState.load(state_dir)
    state.last_server_url = server

    token = state.load_device_token(state_dir)
    client = ApiClient(server, device_token=token)

    local_run_id = str(uuid.uuid4())
    started = utcnow_iso()
    run_log = new_run_log_path(state_dir, started, local_run_id)

    log_event(run_log, {
        "ts": started, "level": "info", "event": "run_start",
        "local_run_id": local_run_id, "server": server,
        "device_id": state.device_id, "device_key": state.device_key,
        "agent_version": state.agent_version, "force": bool(force),
    })

    # Best-effort flush; if server is down, don't crash the run
    try:
        _flush_queue(client, state, state_dir, run_log=run_log, local_run_id=local_run_id)
    except Exception as e:
        log_event(run_log, {
            "ts": utcnow_iso(), "level": "warning", "event": "queue_flush_failed",
            "local_run_id": local_run_id, "error": str(e),
        })

    # Fetch effective policy (MUST NOT hard-crash the whole run)
    try:
        pol = client.get_json("/api/v1/device/policy")
    except Exception as e:
        ended = utcnow_iso()
        err = str(e)

        log_event(run_log, {
            "ts": ended, "level": "error", "event": "policy_fetch_failed",
            "local_run_id": local_run_id, "error": err,
        })

        # Update local state + health even though we're offline
        state.last_run_at = ended
        state.last_run_status = "failed"
        state.last_run_exit = 1
        state.last_failed_at = ended
        state.consecutive_failures = int(state.consecutive_failures or 0) + 1
        state.save(state_dir)

        try:
            write_health(state_dir, state=state)
        except Exception:
            pass

        # Queue a minimal offline report so backlog/flush can be tested
        try:
            mf, mb = queue_limits()
            prune_queue(state_dir, max_files=mf, max_bytes=mb)
            path = queue_report(state_dir, _offline_report(state=state, started=started, ended=ended, error=err))
            log_event(run_log, {
                "ts": utcnow_iso(), "level": "warning", "event": "offline_report_queued",
                "local_run_id": local_run_id, "queued_path": str(path),
            })
        except Exception as qe:
            log_event(run_log, {
                "ts": utcnow_iso(), "level": "warning", "event": "offline_report_queue_failed",
                "local_run_id": local_run_id, "error": str(qe),
            })

        print(f"[ERROR] {err}")
        return
    server_hash = pol.get("effective_policy_hash")
    effective_hash = server_hash or _canonical_policy_hash(pol)

    mode = pol.get("mode", "enforce") or "enforce"
    doc = pol.get("document") or {}
    resources = doc.get("resources") or []

    no_policy_assigned = (
        len(resources) == 0
        and not pol.get("policy_name")
        and not pol.get("policy_id")
        and not (pol.get("sources") or [])
    )

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
            "no_policy_assigned": bool(no_policy_assigned),
            "policy_id": pol.get("policy_id"),
            "policy_name": pol.get("policy_name"),
        },
    )

    logs: list[dict[str, Any]] = [
        {
            "level": "info",
            "message": "Run started",
            "data": {
                "mode": mode,
                "resources": len(resources),
                "no_policy_assigned": bool(no_policy_assigned),
            },
        }
    ]

    if no_policy_assigned:
        log_event(
            run_log,
            {
                "ts": utcnow_iso(),
                "level": "info",
                "event": "no_policy_assigned",
                "local_run_id": local_run_id,
            },
        )

    # Execute resources via engine/handlers
    engine = PolicyEngine(default_handlers())
    eng = engine.run(resources, mode=mode)

    items: list[dict[str, Any]] = eng.items
    logs.extend(eng.logs)
    ok = eng.ok
    failed = eng.failed

    items_changed = sum(1 for it in items if bool(it.get("changed")))
    items_failed = int(failed)
    items_total = len(items)

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
    status = "succeeded" if items_failed == 0 else "failed"

    logs.append(
        {
            "ts": utcnow_iso(),
            "level": "info",
            "message": "Run finished",
            "data": {"ok": ok, "failed": items_failed, "status": status},
        }
    )

    observed_state_hash = _compute_observed_state_hash(items)

    # Use snake_case for server + ui; keep a couple legacy keys too.
    summary: dict[str, Any] = {
        "items_total": items_total,
        "items_failed": items_failed,
        "items_changed": items_changed,
        "ok": ok,
        "failed": items_failed,     # legacy
        "itemsTotal": items_total,  # legacy
        "observed_state_hash": observed_state_hash,
    }
    if no_policy_assigned:
        summary.setdefault("reason", "no_policy_assigned")

    log_event(
        run_log,
        {
            "ts": utcnow_iso(),
            "level": "info",
            "event": "run_summary",
            "local_run_id": local_run_id,
            "status": status,
            "ok": ok,
            "items_total": items_total,
            "items_failed": items_failed,
            "items_changed": items_changed,
            "observed_state_hash": observed_state_hash,
            "reason": summary.get("reason"),
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
        "summary": summary,
        "items": items,
        "logs": logs,
    }

    # Update local state regardless of report POST success
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

    # Always write health.json
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

    # Post report (fallback to queue)
    try:
        resp = client.post_json("/api/v1/device/reports", report, retries=1)
        run_id = resp.get("run_id")
        print(f"[OK] Posted report run_id={run_id}")

        state.last_reported_policy_hash = effective_hash
        state.last_http_ok_at = utcnow_iso()
        state.save(state_dir)

        try:
            write_health(state_dir, state=state)
        except Exception:
            pass

        log_event(
            run_log,
            {"ts": utcnow_iso(), "level": "info", "event": "report_posted", "local_run_id": local_run_id, "server_run_id": run_id, "effective_policy_hash": effective_hash},
        )
    except Exception as e:
        mf, mb = queue_limits()
        stats1 = prune_queue(state_dir, max_files=mf, max_bytes=mb)
        if stats1.get("removed_files", 0) > 0:
            print(f"[WARN] Pruned queued reports before enqueue: removed_files={stats1['removed_files']} removed_bytes={stats1['removed_bytes']}")

        path = queue_report(state_dir, report)
        print(f"[WARN] Failed to post report ({e}); queued at {path}")

        log_event(
            run_log,
            {"ts": utcnow_iso(), "level": "warning", "event": "report_queued", "local_run_id": local_run_id, "error": str(e), "queued_path": str(path), "effective_policy_hash": effective_hash},
        )

        stats2 = prune_queue(state_dir, max_files=mf, max_bytes=mb)
        if stats2.get("removed_files", 0) > 0:
            print(f"[WARN] Pruned queued reports after enqueue: removed_files={stats2['removed_files']} removed_bytes={stats2['removed_bytes']}")

        try:
            write_health(state_dir, state=state)
        except Exception:
            pass


def _flush_queue(
    client: ApiClient,
    state: AgentState,
    state_dir: str,
    *,
    run_log=None,
    local_run_id: str | None = None,
) -> None:
    mf, mb = queue_limits()
    stats = prune_queue(state_dir, max_files=mf, max_bytes=mb)
    if stats.get("removed_files", 0) > 0:
        print(f"[WARN] Pruned queued reports: removed_files={stats['removed_files']} removed_bytes={stats['removed_bytes']}")
        if run_log is not None:
            log_event(
                run_log,
                {"ts": utcnow_iso(), "level": "warning", "event": "queue_pruned", "local_run_id": local_run_id, "removed_files": stats.get("removed_files"), "removed_bytes": stats.get("removed_bytes")},
            )

    queued = iter_queued_reports(state_dir)
    if not queued:
        return

    if run_log is not None:
        log_event(
            run_log,
            {"ts": utcnow_iso(), "level": "info", "event": "queue_flush_start", "local_run_id": local_run_id, "queued_count": len(queued)},
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
                    {"ts": utcnow_iso(), "level": "warning", "event": "queue_flush_error", "local_run_id": local_run_id, "error": str(e), "stopped_after_flushed": flushed},
                )
            break

    if run_log is not None:
        log_event(
            run_log,
            {"ts": utcnow_iso(), "level": "info", "event": "queue_flush_end", "local_run_id": local_run_id, "flushed": flushed},
        )

    if changed:
        state.save(state_dir)
        try:
            write_health(state_dir, state=state)
        except Exception:
            pass
