from __future__ import annotations

import json
from typing import Any

from rich.console import Console
from rich.table import Table


def print_json(console: Console, obj: Any) -> None:
    console.print_json(json.dumps(obj, default=str))


def _trunc(s: str, n: int = 60) -> str:
    if len(s) <= n:
        return s
    return s[: max(0, n - 1)] + "…"


def render_policies_list(
    console: Console, payload: dict[str, Any], *, title: str = "Policies"
) -> None:
    items = payload.get("items") or []
    t = Table(title=title)
    t.add_column("id", overflow="fold")
    t.add_column("name")
    t.add_column("active")
    t.add_column("schema")
    t.add_column("updated_at", overflow="fold")
    t.add_column("description", overflow="fold")

    for p in items:
        t.add_row(
            str(p.get("id") or ""),
            str(p.get("name") or ""),
            "yes" if p.get("is_active") else "no",
            str(p.get("schema_version") or ""),
            str(p.get("updated_at") or p.get("created_at") or ""),
            _trunc(str(p.get("description") or ""), 80),
        )

    console.print(t)
    console.print(
        f"total={payload.get('total')} limit={payload.get('limit')} offset={payload.get('offset')}"
    )


def render_policy_detail(
    console: Console,
    policy: dict[str, Any],
    *,
    raw: bool = False,
    show_scripts: bool = False,
    title: str = "Policy",
) -> None:
    if raw:
        console.print_json(data=policy.get("document") or {})
        return

    meta = Table(title=title)
    meta.add_column("field")
    meta.add_column("value", overflow="fold")
    for k in (
        "id",
        "name",
        "description",
        "schema_version",
        "is_active",
        "created_at",
        "updated_at",
    ):
        meta.add_row(k, str(policy.get(k)))
    console.print(meta)

    doc = policy.get("document") or {}
    resources = doc.get("resources") if isinstance(doc, dict) else None
    if not isinstance(resources, list) or not resources:
        console.print("(no resources)")
        return

    t = Table(title="Resources")
    t.add_column("#", justify="right")
    t.add_column("type")
    t.add_column("id", overflow="fold")
    t.add_column("name")
    t.add_column("details", overflow="fold")

    for idx, r in enumerate(resources, start=1):
        if not isinstance(r, dict):
            continue
        r_type = str(r.get("type") or "")
        rid = str(r.get("id") or "")
        name = str(r.get("name") or "")
        details = ""

        if r_type == "winget.package":
            pkg = r.get("package_id") or rid
            ensure = r.get("ensure")
            details = f"package_id={pkg} ensure={ensure}"
        elif r_type == "script.powershell":
            timeout = r.get("timeout_seconds")
            details = f"timeout_seconds={timeout}"

        t.add_row(str(idx), r_type, rid, name, _trunc(details, 120))

    console.print(t)

    if show_scripts:
        for idx, r in enumerate(resources, start=1):
            if not isinstance(r, dict):
                continue
            if str(r.get("type") or "") != "script.powershell":
                continue
            console.rule(f"script.powershell {idx}: {r.get('id')}")
            if r.get("script"):
                console.print("[bold]script[/bold]")
                console.print(str(r.get("script")))
            if r.get("remediate"):
                console.print("[bold]remediate[/bold]")
                console.print(str(r.get("remediate")))


def render_devices_list(console: Console, payload: dict[str, Any], *, title: str = "Devices") -> None:
    items = payload.get("items") or []
    t = Table(title=title)
    t.add_column("id", overflow="fold")
    t.add_column("device_key")
    t.add_column("hostname")
    t.add_column("status")
    t.add_column("os")
    t.add_column("agent")
    t.add_column("last_seen_at", overflow="fold")

    for d in items:
        t.add_row(
            str(d.get("id") or ""),
            str(d.get("device_key") or ""),
            str(d.get("hostname") or ""),
            str(d.get("status") or ""),
            str(d.get("os") or ""),
            str(d.get("agent_version") or ""),
            str(d.get("last_seen_at") or ""),
        )

    console.print(t)



def render_device_tokens_list(
    console: Console,
    payload: dict[str, Any],
    *,
    title: str = "Device tokens",
) -> None:
    items = payload.get("items") or []
    t = Table(title=title)
    t.add_column("id", overflow="fold")
    t.add_column("hash_prefix", overflow="fold")
    t.add_column("created_at", overflow="fold")
    t.add_column("revoked_at", overflow="fold")
    t.add_column("last_used_at", overflow="fold")
    t.add_column("active")
    t.add_column("replaced_by_id", overflow="fold")

    for it in items:
        t.add_row(
            str(it.get("id") or ""),
            str(it.get("token_hash_prefix") or ""),
            str(it.get("created_at") or ""),
            str(it.get("revoked_at") or ""),
            str(it.get("last_used_at") or ""),
            "yes" if it.get("is_active") else "no",
            str(it.get("replaced_by_id") or ""),
        )
    console.print(t)


def render_enroll_tokens_list(
    console: Console,
    payload: dict[str, Any],
    *,
    title: str = "Enroll tokens",
) -> None:
    items = payload.get("items") or []
    t = Table(title=title)
    t.add_column("id", overflow="fold")
    t.add_column("created_at", overflow="fold")
    t.add_column("expires_at", overflow="fold")
    t.add_column("used_at", overflow="fold")
    t.add_column("used_by_device_id", overflow="fold")
    t.add_column("used")
    t.add_column("expired")
    t.add_column("note", overflow="fold")

    for tok in items:
        t.add_row(
            str(tok.get("id") or ""),
            str(tok.get("created_at") or ""),
            str(tok.get("expires_at") or ""),
            str(tok.get("used_at") or ""),
            str(tok.get("used_by_device_id") or ""),
            "yes" if tok.get("is_used") else "no",
            "yes" if tok.get("is_expired") else "no",
            _trunc(str(tok.get("note") or ""), 80),
        )

    console.print(t)
    console.print(
        f"total={payload.get('total')} limit={payload.get('limit')} offset={payload.get('offset')}"
    )



def render_assignments_list(
    console: Console,
    payload: dict[str, Any],
    *,
    title: str = "Assignments",
) -> None:
    device_id = payload.get("device_id")
    items = payload.get("assignments") or []

    t = Table(title=f"{title} ({device_id})" if device_id else title)
    t.add_column("policy_name")
    t.add_column("policy_id", overflow="fold")
    t.add_column("priority", justify="right")
    t.add_column("mode")
    t.add_column("policy_active")

    for a in items:
        t.add_row(
            str(a.get("policy_name") or ""),
            str(a.get("policy_id") or ""),
            str(a.get("priority") or ""),
            str(a.get("mode") or ""),
            "yes" if a.get("is_active") else "no",
        )

    console.print(t)
    if not items:
        console.print("(no assignments)")




def render_assignments_plan(
    console: Console,
    rows: list[dict[str, Any]],
    *,
    title: str = "Assignment plan",
    device_id: str | None = None,
) -> None:
    t = Table(title=f"{title} ({device_id})" if device_id else title)
    t.add_column("action")
    t.add_column("policy_name")
    t.add_column("policy_id", overflow="fold")
    t.add_column("priority", justify="right")
    t.add_column("mode")
    t.add_column("current_priority", justify="right")
    t.add_column("current_mode")

    for r in rows:
        t.add_row(
            str(r.get("action") or ""),
            str(r.get("policy_name") or ""),
            str(r.get("policy_id") or ""),
            str(r.get("priority") or ""),
            str(r.get("mode") or ""),
            str(r.get("current_priority") or ""),
            str(r.get("current_mode") or ""),
        )

    console.print(t)
    if not rows:
        console.print("(no changes)")


def render_runs_list(
    console: Console, payload: dict[str, Any], *, title: str = "Runs"
) -> None:
    items = payload.get("items") or []
    t = Table(title=title)
    t.add_column("id", overflow="fold")
    t.add_column("device_id", overflow="fold")
    t.add_column("status")
    t.add_column("started_at", overflow="fold")
    t.add_column("ended_at", overflow="fold")
    t.add_column("correlation_id", overflow="fold")

    for r in items:
        t.add_row(
            str(r.get("id") or ""),
            str(r.get("device_id") or ""),
            str(r.get("status") or ""),
            str(r.get("started_at") or ""),
            str(r.get("ended_at") or ""),
            str(r.get("correlation_id") or ""),
        )
    console.print(t)
    console.print(
        f"total={payload.get('total')} limit={payload.get('limit')} offset={payload.get('offset')}"
    )


def render_run_detail(
    console: Console,
    payload: dict[str, Any],
    *,
    full: bool = True,
    items_limit: int = 200,
    logs_limit: int = 50,
    title: str = "Run",
) -> None:
    meta = Table(title=title)
    meta.add_column("field")
    meta.add_column("value", overflow="fold")
    for k in (
        "id",
        "device_id",
        "status",
        "started_at",
        "ended_at",
        "correlation_id",
        "agent_version",
    ):
        meta.add_row(k, str(payload.get(k)))
    console.print(meta)

    if not full:
        return

    items = payload.get("items") or []
    logs = payload.get("logs") or []

    t_items = Table(title=f"Items (showing up to {items_limit})")
    t_items.add_column("#", justify="right")
    t_items.add_column("type")
    t_items.add_column("id", overflow="fold")
    t_items.add_column("name")
    t_items.add_column("changed")
    t_items.add_column("detect")
    t_items.add_column("remediate")
    t_items.add_column("validate")
    t_items.add_column("error", overflow="fold")

    for it in items[: max(0, int(items_limit))]:
        err = it.get("error") or {}
        err_type = err.get("type") if isinstance(err, dict) else ""
        t_items.add_row(
            str(it.get("ordinal") or ""),
            str(it.get("resource_type") or ""),
            str(it.get("resource_id") or ""),
            _trunc(str(it.get("name") or ""), 40),
            "yes" if it.get("changed") else "no",
            str(it.get("status_detect") or ""),
            str(it.get("status_remediate") or ""),
            str(it.get("status_validate") or ""),
            _trunc(str(err_type or ""), 40),
        )
    console.print(t_items)

    t_logs = Table(title=f"Logs (showing up to {logs_limit})")
    t_logs.add_column("ts", overflow="fold")
    t_logs.add_column("level")
    t_logs.add_column("message", overflow="fold")
    t_logs.add_column("run_item_id", overflow="fold")

    for lg in logs[: max(0, int(logs_limit))]:
        t_logs.add_row(
            str(lg.get("ts") or ""),
            str(lg.get("level") or ""),
            _trunc(str(lg.get("message") or ""), 160),
            str(lg.get("run_item_id") or ""),
        )
    console.print(t_logs)


def render_tenants_list(console: Console, payload: dict[str, Any], *, title: str = "Tenants") -> None:
    items = payload.get("items") or []
    t = Table(title=title)
    t.add_column("id", overflow="fold")
    t.add_column("name")
    t.add_column("active")
    t.add_column("created_at", overflow="fold")

    for it in items:
        t.add_row(
            str(it.get("id") or ""),
            str(it.get("name") or ""),
            "yes" if it.get("is_active") else "no",
            str(it.get("created_at") or ""),
        )
    console.print(t)


def render_admin_keys_list(
    console: Console, payload: dict[str, Any], *, title: str = "Admin keys"
) -> None:
    items = payload.get("items") or []
    t = Table(title=title)
    t.add_column("id", overflow="fold")
    t.add_column("tenant_id", overflow="fold")
    t.add_column("scope")
    t.add_column("created_at", overflow="fold")
    t.add_column("note", overflow="fold")

    for it in items:
        t.add_row(
            str(it.get("id") or ""),
            str(it.get("tenant_id") or ""),
            str(it.get("scope") or ""),
            str(it.get("created_at") or ""),
            _trunc(str(it.get("note") or ""), 80),
        )
    console.print(t)
