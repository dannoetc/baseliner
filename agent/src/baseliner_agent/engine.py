from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ItemResult:
    """Single resource execution result.

    This mirrors the shape expected by the server's SubmitReportRequest:
      - item: ReportRunItem-like dict
      - logs: list[ReportLogEvent-like dicts]
    """

    item: dict[str, Any]
    logs: list[dict[str, Any]]
    success: bool


class ResourceHandler(Protocol):
    """A handler for a resource type (e.g. winget.package)."""

    resource_type: str

    def run(self, res: dict[str, Any], *, ordinal: int, mode: str) -> ItemResult: ...


@dataclass
class EngineResult:
    items: list[dict[str, Any]]
    logs: list[dict[str, Any]]
    ok: int
    failed: int
    # Per-item success flag, aligned to items/logs contribution.
    results: list[ItemResult]


def _unsupported(res: dict[str, Any], *, ordinal: int) -> ItemResult:
    rtype = (res.get("type") or "").strip() or "unknown"
    rid = (res.get("id") or "").strip() or "unknown"
    name = res.get("name")

    started_at = utcnow_iso()
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
        "started_at": started_at,
        "ended_at": utcnow_iso(),
        "evidence": {},
        "error": {"message": "Unsupported resource type (MVP)", "type": "unsupported_resource"},
    }
    logs = [
        {
            "ts": utcnow_iso(),
            "level": "warning",
            "message": "Unsupported resource type",
            "data": {"type": rtype, "id": rid},
            "run_item_ordinal": ordinal,
        }
    ]
    return ItemResult(item=item, logs=logs, success=False)


def _invalid_resource(res: dict[str, Any], *, ordinal: int) -> ItemResult:
    """Record an invalid resource instead of silently skipping it."""
    rtype = (res.get("type") or "").strip() or "invalid"
    rid_raw = (res.get("id") or "").strip()
    rid = rid_raw or f"missing_id_{ordinal}"
    name = res.get("name")

    started_at = utcnow_iso()
    item = {
        "resource_type": rtype,
        "resource_id": rid,
        "name": name,
        "ordinal": ordinal,
        "changed": False,
        "reboot_required": False,
        "status_detect": "fail",
        "status_remediate": "skipped",
        "status_validate": "skipped",
        "started_at": started_at,
        "ended_at": utcnow_iso(),
        "evidence": {"resource": res},
        "error": {"type": "invalid_resource", "message": "Resource missing required fields: type/id"},
    }
    logs = [
        {
            "ts": utcnow_iso(),
            "level": "error",
            "message": "Invalid resource (missing type/id)",
            "data": {"type": rtype, "id": rid_raw or None},
            "run_item_ordinal": ordinal,
        }
    ]
    return ItemResult(item=item, logs=logs, success=False)


class PolicyEngine:
    """Executes a policy document (resources list) using registered handlers."""

    def __init__(self, handlers: dict[str, ResourceHandler]):
        self._handlers = dict(handlers or {})

    def run(self, resources: list[dict[str, Any]], *, mode: str) -> EngineResult:
        results: list[ItemResult] = []
        items: list[dict[str, Any]] = []
        logs: list[dict[str, Any]] = []

        ok = 0
        failed = 0
        ordinal = 0

        for res in resources or []:
            rtype = (res.get("type") or "").strip()
            rid = (res.get("id") or "").strip()
            if not rtype or not rid:
                ir = _invalid_resource(res, ordinal=ordinal)
                results.append(ir)
                items.append(ir.item)
                logs.extend(ir.logs)
                failed += 1
                ordinal += 1
                continue

            handler = self._handlers.get(rtype)
            try:
                if handler:
                    ir = handler.run(res, ordinal=ordinal, mode=mode)
                else:
                    ir = _unsupported(res, ordinal=ordinal)
            except Exception as e:
                # Never let a single resource crash the run; record it as failed.
                started_at = utcnow_iso()
                ir = ItemResult(
                    item={
                        "resource_type": rtype,
                        "resource_id": rid,
                        "name": res.get("name"),
                        "ordinal": ordinal,
                        "changed": False,
                        "reboot_required": False,
                        "status_detect": "fail",
                        "status_remediate": "skipped",
                        "status_validate": "skipped",
                        "started_at": started_at,
                        "ended_at": utcnow_iso(),
                        "evidence": {},
                        "error": {"type": "exception", "message": str(e)},
                    },
                    logs=[
                        {
                            "ts": utcnow_iso(),
                            "level": "error",
                            "message": "Resource exception",
                            "data": {"type": rtype, "id": rid, "error": str(e)},
                            "run_item_ordinal": ordinal,
                        }
                    ],
                    success=False,
                )

            results.append(ir)
            items.append(ir.item)
            logs.extend(ir.logs)

            if ir.success:
                ok += 1
            else:
                failed += 1

            ordinal += 1

        return EngineResult(items=items, logs=logs, ok=ok, failed=failed, results=results)
