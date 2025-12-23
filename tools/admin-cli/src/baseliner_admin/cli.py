from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from baseliner_admin.client import BaselinerAdminClient, ClientConfig
from baseliner_admin.render import (
    render_assignments_list,
    render_devices_list,
    render_policy_detail,
    render_policies_list,
    render_run_detail,
    render_runs_list,
)
from baseliner_admin.tui import die_tui_not_supported, run_tui
from baseliner_admin.util import read_json_file, try_parse_uuid

app = typer.Typer(add_completion=False, help="Baseliner admin CLI")
devices_app = typer.Typer(add_completion=False, help="Device administration")
runs_app = typer.Typer(add_completion=False, help="Run inspection")
policies_app = typer.Typer(add_completion=False, help="Policy administration")
assignments_app = typer.Typer(add_completion=False, help="Policy assignment management")

app.add_typer(devices_app, name="devices")
app.add_typer(runs_app, name="runs")
app.add_typer(policies_app, name="policies")
app.add_typer(assignments_app, name="assignments")


@app.callback()
def main_callback(
    ctx: typer.Context,
    server_url: str = typer.Option(
        None,
        "--server",
        envvar="BASELINER_SERVER_URL",
        help="Baseliner server base URL (ex: http://localhost:8000)",
    ),
    admin_key: str = typer.Option(
        None,
        "--admin-key",
        envvar="BASELINER_ADMIN_KEY",
        help="Baseliner admin key",
    ),
    json_out: bool = typer.Option(False, "--json", help="Print machine-readable JSON"),
) -> None:
    if not server_url:
        raise typer.BadParameter("Server URL required (set BASELINER_SERVER_URL or --server)")
    if not admin_key:
        raise typer.BadParameter("Admin key required (set BASELINER_ADMIN_KEY or --admin-key)")

    ctx.obj = {
        "server_url": server_url,
        "admin_key": admin_key,
        "json": bool(json_out),
    }


def _client(ctx: typer.Context) -> BaselinerAdminClient:
    o = ctx.obj or {}
    return BaselinerAdminClient(
        ClientConfig(
            server=o["server_url"],
            admin_key=o["admin_key"],
        )
    )


def _console() -> Console:
    # If output is redirected, avoid rich's color codes.
    no_color = not os.isatty(1)
    return Console(no_color=no_color)


def _resolve_device_id(
    *,
    client: BaselinerAdminClient,
    console: Console,
    device_ref: str,
    include_deleted: bool = True,
) -> str:
    device_ref = device_ref.strip()
    u = try_parse_uuid(device_ref)
    if u:
        return str(u)

    q = device_ref.lower()
    payload = client.devices_list(limit=500, offset=0, include_deleted=include_deleted)
    items = list(payload.get("items") or [])
    matches = [
        d
        for d in items
        if q in str(d.get("device_key") or "").lower()
        or q in str(d.get("hostname") or "").lower()
    ]

    if len(matches) == 1:
        return str(matches[0].get("id"))

    if not matches:
        console.print(f"No devices matched: {device_ref}")
        raise typer.Exit(code=1)

    console.print(f"Ambiguous device reference: {device_ref}")
    render_devices_list(
        console,
        {"items": matches, "total": len(matches), "limit": len(matches), "offset": 0},
        title="Device matches",
    )
    raise typer.Exit(code=2)


def _resolve_policy_name(
    *,
    client: BaselinerAdminClient,
    console: Console,
    policy_ref: str,
    include_inactive: bool = True,
) -> str:
    policy_ref = policy_ref.strip()
    u = try_parse_uuid(policy_ref)
    if u:
        pol = client.policies_show(str(u))
        name = str(pol.get("name") or "").strip()
        if not name:
            console.print(f"Policy {u} missing name")
            raise typer.Exit(code=1)
        return name

    payload = client.policies_list(
        limit=200,
        offset=0,
        include_inactive=include_inactive,
        q=policy_ref,
    )
    items = list(payload.get("items") or [])
    q = policy_ref.lower()

    exact = [p for p in items if str(p.get("name") or "").strip().lower() == q]
    if len(exact) == 1:
        return str(exact[0].get("name"))

    if len(items) == 1:
        return str(items[0].get("name"))

    if not items:
        console.print(f"No policies matched: {policy_ref}")
        raise typer.Exit(code=1)

    console.print(f"Ambiguous policy reference: {policy_ref}")
    render_policies_list(console, payload)
    raise typer.Exit(code=2)


def _resolve_assignment_policy(
    *,
    console: Console,
    policy_ref: str,
    assignments: list[dict[str, Any]],
) -> tuple[str, str]:
    """Resolve a policy ref (UUID or substring) against a device's assignments.

    Returns (policy_id, policy_name) for a unique match.
    """

    ref = policy_ref.strip()
    if not ref:
        raise typer.BadParameter("policy reference must not be empty")

    u = try_parse_uuid(ref)
    if u:
        u_s = str(u).lower()
        matches = [
            a
            for a in assignments
            if str(a.get("policy_id") or "").strip().lower() == u_s
        ]
    else:
        q = ref.lower()
        matches = [
            a
            for a in assignments
            if q in str(a.get("policy_name") or "").lower()
        ]

        exact = [
            a
            for a in matches
            if str(a.get("policy_name") or "").strip().lower() == q
        ]
        if len(exact) == 1:
            matches = exact

    if len(matches) == 1:
        m = matches[0]
        pol_id = str(m.get("policy_id") or "").strip()
        pol_name = str(m.get("policy_name") or "").strip()
        if not pol_id or not pol_name:
            console.print("Matched assignment is missing policy_id or policy_name")
            raise typer.Exit(code=1)
        return pol_id, pol_name

    if not matches:
        console.print(f"No assignments matched policy ref: {policy_ref}")
        raise typer.Exit(code=1)

    console.print(f"Ambiguous policy ref within assignments: {policy_ref}")
    render_assignments_list(console, {"device_id": "", "assignments": matches}, title="Matches")
    raise typer.Exit(code=2)


def _normalize_mode(v: str | None) -> str | None:
    if v is None:
        return None
    s = v.strip().lower()
    if not s:
        return None
    if s not in ("enforce", "audit"):
        raise typer.BadParameter("--mode must be 'enforce' or 'audit'")
    return s


@app.command("tui", help="EXPERIMENTAL: prompt-driven operator console")
def tui(ctx: typer.Context) -> None:
    if ctx.obj.get("json"):
        raise typer.BadParameter("--json is not supported for the interactive tui")

    console = _console()
    if not (os.isatty(0) and os.isatty(1)):
        die_tui_not_supported(console)

    run_tui(client=_client(ctx), console=console)


@devices_app.command("list")
def devices_list(
    ctx: typer.Context,
    limit: int = typer.Option(50, "--limit"),
    offset: int = typer.Option(0, "--offset"),
    include_deleted: bool = typer.Option(False, "--include-deleted"),
) -> None:
    c = _client(ctx)
    payload = c.devices_list(limit=limit, offset=offset, include_deleted=include_deleted)

    if ctx.obj.get("json"):
        print(c.pretty_json(payload))
        return

    render_devices_list(_console(), payload)


@devices_app.command("find")
def devices_find(
    ctx: typer.Context,
    query: str = typer.Argument(..., help="device_key or hostname (exact match)"),
    include_deleted: bool = typer.Option(False, "--include-deleted"),
) -> None:
    c = _client(ctx)
    payload = c.devices_list(limit=500, offset=0, include_deleted=include_deleted)
    items = payload.get("items") or []

    q = query.strip().lower()
    matches = [
        d
        for d in items
        if str(d.get("device_key") or "").strip().lower() == q
        or str(d.get("hostname") or "").strip().lower() == q
    ]

    if ctx.obj.get("json"):
        print(c.pretty_json({"query": query, "matches": matches}))
        return

    if not matches:
        _console().print(f"No devices matched: {query}")
        raise typer.Exit(code=1)

    render_devices_list(
        _console(), {"items": matches, "total": len(matches), "limit": 500, "offset": 0}
    )


@devices_app.command("debug")
def devices_debug(ctx: typer.Context, device_id: str) -> None:
    c = _client(ctx)
    payload = c.devices_debug(device_id)
    if ctx.obj.get("json"):
        print(c.pretty_json(payload))
        return
    _console().print_json(data=payload)


@devices_app.command("delete")
def devices_delete(
    ctx: typer.Context,
    device_id: str,
    reason: str | None = typer.Option(None, "--reason"),
) -> None:
    c = _client(ctx)
    payload = c.devices_delete(device_id, reason=reason)
    if ctx.obj.get("json"):
        print(c.pretty_json(payload))
        return
    _console().print_json(data=payload)


@devices_app.command("restore")
def devices_restore(ctx: typer.Context, device_id: str) -> None:
    c = _client(ctx)
    payload = c.devices_restore(device_id)
    if ctx.obj.get("json"):
        print(c.pretty_json(payload))
        return
    _console().print_json(data=payload)


@devices_app.command("revoke-token")
def devices_revoke_token(ctx: typer.Context, device_id: str) -> None:
    c = _client(ctx)
    payload = c.devices_revoke_token(device_id)
    if ctx.obj.get("json"):
        print(c.pretty_json(payload))
        return
    _console().print_json(data=payload)


@runs_app.command("list")
def runs_list(
    ctx: typer.Context,
    limit: int = typer.Option(50, "--limit"),
    offset: int = typer.Option(0, "--offset"),
    device_id: str | None = typer.Option(None, "--device-id"),
) -> None:
    c = _client(ctx)
    payload = c.runs_list(limit=limit, offset=offset, device_id=device_id)
    if ctx.obj.get("json"):
        print(c.pretty_json(payload))
        return
    render_runs_list(_console(), payload)


@runs_app.command("show")
def runs_show(
    ctx: typer.Context,
    run_id: str,
    full: bool = typer.Option(False, "--full", help="Show run items + logs"),
    logs_limit: int = typer.Option(50, "--logs-limit", help="Max logs to display"),
    logs_all: bool = typer.Option(False, "--logs-all", help="Show all logs"),
) -> None:
    c = _client(ctx)
    payload = c.runs_show(run_id)
    if logs_all:
        logs_limit = 1_000_000
    if ctx.obj.get("json"):
        print(c.pretty_json(payload))
        return
    render_run_detail(_console(), payload, full=full, logs_limit=int(logs_limit))


@policies_app.command("list")
def policies_list(
    ctx: typer.Context,
    limit: int = typer.Option(50, "--limit"),
    offset: int = typer.Option(0, "--offset"),
    include_inactive: bool = typer.Option(False, "--include-inactive"),
) -> None:
    c = _client(ctx)
    payload = c.policies_list(limit=limit, offset=offset, include_inactive=include_inactive)
    if ctx.obj.get("json"):
        print(c.pretty_json(payload))
        return
    render_policies_list(_console(), payload)


@policies_app.command("find")
def policies_find(
    ctx: typer.Context,
    query: str = typer.Argument(..., help="Substring search over policy name/description"),
    include_inactive: bool = typer.Option(True, "--include-inactive/--active-only"),
    limit: int = typer.Option(50, "--limit"),
    offset: int = typer.Option(0, "--offset"),
) -> None:
    c = _client(ctx)
    payload = c.policies_list(
        limit=limit,
        offset=offset,
        include_inactive=include_inactive,
        q=query,
    )
    if ctx.obj.get("json"):
        print(c.pretty_json(payload))
        return
    render_policies_list(_console(), payload)


@policies_app.command("show")
def policies_show(
    ctx: typer.Context,
    ref: str = typer.Argument(..., help="Policy UUID or policy name"),
    raw: bool = typer.Option(False, "--raw", help="Print only the policy document JSON"),
    include_inactive: bool = typer.Option(True, "--include-inactive/--active-only"),
) -> None:
    c = _client(ctx)

    pol_id: str | None = None
    u = try_parse_uuid(ref)
    if u:
        pol_id = str(u)
    else:
        search = c.policies_list(include_inactive=include_inactive, q=ref, limit=200, offset=0)
        items = search.get("items") or []

        exact = [
            p for p in items if str(p.get("name") or "").strip().lower() == ref.strip().lower()
        ]
        if len(exact) == 1:
            pol_id = str(exact[0].get("id"))
        elif len(items) == 1:
            pol_id = str(items[0].get("id"))
        else:
            if ctx.obj.get("json"):
                print(c.pretty_json({"ref": ref, "matches": items}))
                return
            console = _console()
            console.print(f"Ambiguous policy reference: {ref}")
            if items:
                render_policies_list(console, search)
            else:
                console.print("No policies matched.")
            raise typer.Exit(code=2)

    payload = c.policies_show(pol_id)
    if ctx.obj.get("json"):
        print(c.pretty_json(payload))
        return
    render_policy_detail(_console(), payload, raw=raw)


@policies_app.command("upsert")
def policies_upsert(
    ctx: typer.Context,
    policy_file: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    name: str | None = typer.Option(None, "--name", help="Override/force policy name"),
    description: str | None = typer.Option(None, "--description"),
    schema_version: str | None = typer.Option(None, "--schema-version"),
    is_active: bool | None = typer.Option(
        None,
        "--active/--inactive",
        help="Override policy active flag",
    ),
) -> None:
    c = _client(ctx)
    obj = read_json_file(policy_file)

    if not isinstance(obj, dict):
        raise typer.BadParameter("Policy file must contain a JSON object")

    wrapper_doc = obj.get("document") if "document" in obj else None
    if isinstance(wrapper_doc, dict):
        doc = wrapper_doc
        inferred = {
            "name": obj.get("name"),
            "description": obj.get("description"),
            "schema_version": obj.get("schema_version"),
            "is_active": obj.get("is_active"),
        }
    else:
        doc = obj
        inferred = {
            "name": None,
            "description": None,
            "schema_version": None,
            "is_active": None,
        }

    final_name = name or inferred.get("name")
    if not final_name:
        raise typer.BadParameter("Policy name missing (provide --name or use a wrapper file)")

    payload: dict[str, Any] = {
        "name": final_name,
        "description": description if description is not None else inferred.get("description"),
        "schema_version": schema_version
        if schema_version is not None
        else (inferred.get("schema_version") or "1.0"),
        "is_active": (
            bool(is_active) if is_active is not None else bool(inferred.get("is_active", True))
        ),
        "document": doc,
    }

    resp = c.policies_upsert(payload)
    if ctx.obj.get("json"):
        print(c.pretty_json(resp))
        return
    _console().print_json(data=resp)


@assignments_app.command("list")
def assignments_list(
    ctx: typer.Context,
    device: str = typer.Argument(
        ..., help="Device UUID, device_key, or hostname substring"
    ),
    include_deleted: bool = typer.Option(True, "--include-deleted/--active-only"),
) -> None:
    c = _client(ctx)
    console = _console()
    device_id = _resolve_device_id(
        client=c,
        console=console,
        device_ref=device,
        include_deleted=include_deleted,
    )
    payload = c.device_assignments_list(device_id)

    if ctx.obj.get("json"):
        print(c.pretty_json(payload))
        return

    render_assignments_list(console, payload)


@assignments_app.command("set")
def assignments_set(
    ctx: typer.Context,
    device: str = typer.Argument(
        ..., help="Device UUID, device_key, or hostname substring"
    ),
    policy: str = typer.Argument(..., help="Policy UUID or name (substring ok)"),
    priority: int = typer.Option(9999, "--priority"),
    mode: str = typer.Option("enforce", "--mode", help="enforce or audit"),
    include_deleted: bool = typer.Option(True, "--include-deleted/--active-only"),
    include_inactive_policies: bool = typer.Option(True, "--include-inactive-policies/--active-only"),
) -> None:
    c = _client(ctx)
    console = _console()

    mode_n = _normalize_mode(mode)
    assert mode_n is not None

    device_id = _resolve_device_id(
        client=c,
        console=console,
        device_ref=device,
        include_deleted=include_deleted,
    )
    policy_name = _resolve_policy_name(
        client=c,
        console=console,
        policy_ref=policy,
        include_inactive=include_inactive_policies,
    )

    payload = c.assignment_set(
        device_id=device_id,
        policy_name=policy_name,
        priority=int(priority),
        mode=mode_n,
    )

    if ctx.obj.get("json"):
        print(c.pretty_json(payload))
        return

    console.print_json(data=payload)


@assignments_app.command("update")
def assignments_update(
    ctx: typer.Context,
    device: str = typer.Argument(
        ..., help="Device UUID, device_key, or hostname substring"
    ),
    policy: str = typer.Argument(..., help="Policy UUID or name (substring ok)"),
    priority: int | None = typer.Option(None, "--priority", help="New priority (lower wins)"),
    mode: str | None = typer.Option(None, "--mode", help="enforce or audit"),
    include_deleted: bool = typer.Option(True, "--include-deleted/--active-only"),
    include_inactive_policies: bool = typer.Option(True, "--include-inactive-policies/--active-only"),
) -> None:
    """Edit an existing assignment (update mode/priority).

    This reads the current assignments for the device and updates the matching
    policy assignment while preserving unspecified fields.
    """

    c = _client(ctx)
    console = _console()

    device_id = _resolve_device_id(
        client=c,
        console=console,
        device_ref=device,
        include_deleted=include_deleted,
    )
    policy_name = _resolve_policy_name(
        client=c,
        console=console,
        policy_ref=policy,
        include_inactive=include_inactive_policies,
    )

    current = c.device_assignments_list(device_id)
    assignments = list(current.get("assignments") or [])
    match = None
    for a in assignments:
        if str(a.get("policy_name") or "").strip().lower() == policy_name.strip().lower():
            match = a
            break

    if not match:
        console.print(f"No existing assignment found for policy: {policy_name}")
        raise typer.Exit(code=1)

    current_mode = _normalize_mode(str(match.get("mode") or "enforce")) or "enforce"
    new_mode = _normalize_mode(mode) or current_mode
    new_priority = int(priority) if priority is not None else int(match.get("priority") or 9999)

    payload = c.assignment_set(
        device_id=device_id,
        policy_name=policy_name,
        priority=int(new_priority),
        mode=str(new_mode),
    )

    if ctx.obj.get("json"):
        print(c.pretty_json(payload))
        return

    console.print_json(data=payload)


@assignments_app.command("remove")
def assignments_remove(
    ctx: typer.Context,
    device: str = typer.Argument(
        ..., help="Device UUID, device_key, or hostname substring"
    ),
    policy: str = typer.Argument(
        ...,
        help="Policy UUID or name substring (must match an assigned policy)",
    ),
    include_deleted: bool = typer.Option(True, "--include-deleted/--active-only"),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation prompt"),
) -> None:
    """Remove a single policy assignment from a device."""

    c = _client(ctx)
    console = _console()

    device_id = _resolve_device_id(
        client=c,
        console=console,
        device_ref=device,
        include_deleted=include_deleted,
    )

    current = c.device_assignments_list(device_id)
    assignments = list(current.get("assignments") or [])

    policy_id, policy_name = _resolve_assignment_policy(
        console=console,
        policy_ref=policy,
        assignments=assignments,
    )

    if not yes:
        if not typer.confirm(
            f"Remove assignment '{policy_name}' from device {device_id}?",
            default=False,
        ):
            raise typer.Exit(code=2)

    payload = c.device_assignment_remove(device_id, policy_id)

    if ctx.obj.get("json"):
        print(c.pretty_json(payload))
        return

    console.print_json(data=payload)


@assignments_app.command("clone")
def assignments_clone(
    ctx: typer.Context,
    source_device: str = typer.Argument(..., help="Source device UUID/device_key/hostname substring"),
    dest_device: str = typer.Argument(..., help="Destination device UUID/device_key/hostname substring"),
    clear_first: bool = typer.Option(
        True,
        "--clear-first/--merge",
        help="If true, clear destination assignments before applying source assignments",
    ),
    priority_offset: int = typer.Option(0, "--priority-offset", help="Add N to each source priority"),
    mode: str | None = typer.Option(
        None,
        "--mode",
        help="Override mode for all cloned assignments (enforce or audit)",
    ),
    include_deleted: bool = typer.Option(True, "--include-deleted/--active-only"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would happen without changing anything"),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation prompt"),
) -> None:
    """Clone policy assignments from one device to another."""

    c = _client(ctx)
    console = _console()

    src_id = _resolve_device_id(
        client=c,
        console=console,
        device_ref=source_device,
        include_deleted=include_deleted,
    )
    dst_id = _resolve_device_id(
        client=c,
        console=console,
        device_ref=dest_device,
        include_deleted=include_deleted,
    )
    if src_id == dst_id:
        raise typer.BadParameter("source and destination devices must be different")

    mode_override = _normalize_mode(mode)

    src_payload = c.device_assignments_list(src_id)
    src_items = list(src_payload.get("assignments") or [])

    if not src_items:
        console.print(f"Source device {src_id} has no assignments.")
        raise typer.Exit(code=1)

    plan_items: list[dict[str, Any]] = []
    for a in src_items:
        pn = str(a.get("policy_name") or "").strip()
        if not pn:
            continue
        pri = int(a.get("priority") or 9999) + int(priority_offset)
        if pri < 0:
            pri = 0
        m_raw = mode_override or str(a.get("mode") or "enforce").strip().lower()
        try:
            m = _normalize_mode(m_raw) or "enforce"
        except typer.BadParameter:
            m = "enforce"
        plan_items.append(
            {
                "policy_name": pn,
                "policy_id": a.get("policy_id"),
                "priority": pri,
                "mode": m,
                "is_active": a.get("is_active"),
            }
        )

    console.print("[bold]Clone plan[/bold]")
    console.print(f"source={src_id}")
    console.print(f"dest={dst_id}")
    render_assignments_list(
        console,
        {"device_id": dst_id, "assignments": plan_items},
        title="Assignments to apply",
    )

    if dry_run:
        return

    if not yes:
        msg = "Apply assignments to destination device?"
        if clear_first:
            msg = "Clear destination assignments and apply source assignments?"
        if not typer.confirm(msg, default=False):
            raise typer.Exit(code=2)

    if clear_first:
        c.device_assignments_clear(dst_id)

    applied = 0
    for it in plan_items:
        c.assignment_set(
            device_id=dst_id,
            policy_name=str(it["policy_name"]),
            priority=int(it["priority"]),
            mode=str(it["mode"]),
        )
        applied += 1

    console.print(f"Applied {applied} assignments to {dst_id}.")


@assignments_app.command("clear")
def assignments_clear(
    ctx: typer.Context,
    device: str = typer.Argument(
        ..., help="Device UUID, device_key, or hostname substring"
    ),
    include_deleted: bool = typer.Option(True, "--include-deleted/--active-only"),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation prompt"),
) -> None:
    c = _client(ctx)
    console = _console()
    device_id = _resolve_device_id(
        client=c,
        console=console,
        device_ref=device,
        include_deleted=include_deleted,
    )

    if not yes:
        if not typer.confirm(f"Clear all assignments for device {device_id}?", default=False):
            raise typer.Exit(code=2)

    payload = c.device_assignments_clear(device_id)

    if ctx.obj.get("json"):
        print(c.pretty_json(payload))
        return

    console.print_json(data=payload)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
