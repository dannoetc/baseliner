from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from .client import ApiError, BaselinerAdminClient, ClientConfig
from .render import audit_table, devices_table, print_json, runs_table

app = typer.Typer(
    add_completion=False,
    help="Baseliner admin CLI (CLI-first operator/developer tool).",
)


def _console() -> Console:
    return Console(highlight=False)


def _kv_table(title: str, data: dict[str, Any]) -> Table:
    t = Table(title=title, show_lines=False)
    t.add_column("field")
    t.add_column("value", overflow="fold")
    for k in sorted(data.keys()):
        t.add_row(str(k), str(data.get(k)))
    return t


def _ctx_client(ctx: typer.Context) -> BaselinerAdminClient:
    return ctx.obj["client"]


def _ctx_json(ctx: typer.Context) -> bool:
    return bool(ctx.obj.get("json"))


def _resolve_device_id(
    client: BaselinerAdminClient,
    *,
    device_id: str | None,
    device_key: str | None,
    include_deleted: bool = True,
) -> str:
    if device_id:
        return device_id
    if not device_key:
        raise typer.BadParameter("Provide --device-id or --device-key")

    offset = 0
    page = 500

    while True:
        resp = client.list_devices(
            limit=page,
            offset=offset,
            include_deleted=include_deleted,
        )
        items = resp.get("items") if isinstance(resp, dict) else None
        if not isinstance(items, list):
            items = []

        for d in items:
            if not isinstance(d, dict):
                continue
            if d.get("device_key") == device_key or d.get("hostname") == device_key:
                did = d.get("id")
                if did:
                    return str(did)

        if len(items) < page:
            break
        offset += page

    raise typer.BadParameter(f"Device not found for device_key={device_key!r}")


@app.callback()
def main_callback(
    ctx: typer.Context,
    server: str = typer.Option(
        "http://localhost:8000",
        "--server",
        envvar="BASELINER_SERVER_URL",
        help="Baseliner server base URL.",
    ),
    admin_key: str = typer.Option(
        "",
        "--admin-key",
        envvar="BASELINER_ADMIN_KEY",
        help="Admin key (sent as X-Admin-Key).",
    ),
    timeout: float = typer.Option(10.0, "--timeout", help="HTTP timeout seconds."),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Print raw JSON instead of tables.",
    ),
) -> None:
    """Baseliner admin CLI."""

    if not admin_key:
        raise typer.BadParameter(
            "Missing admin key. Pass --admin-key or set BASELINER_ADMIN_KEY."
        )

    cfg = ClientConfig(server=server, admin_key=admin_key, timeout_s=float(timeout))
    client = BaselinerAdminClient(cfg)

    ctx.obj = {
        "client": client,
        "json": bool(json_output),
        "console": _console(),
    }
    ctx.call_on_close(client.close)


# --- Devices ---

devices_app = typer.Typer(help="Manage devices.")
app.add_typer(devices_app, name="devices")


@devices_app.command("list")
def devices_list(
    ctx: typer.Context,
    limit: int = typer.Option(50, "--limit", min=1, max=500),
    offset: int = typer.Option(0, "--offset", min=0),
    include_deleted: bool = typer.Option(False, "--include-deleted"),
    include_health: bool = typer.Option(False, "--include-health"),
) -> None:
    """List devices."""

    c = _ctx_client(ctx)
    con: Console = ctx.obj["console"]

    try:
        resp = c.list_devices(
            limit=limit,
            offset=offset,
            include_deleted=include_deleted,
            include_health=include_health,
        )
    except ApiError as e:
        raise typer.Exit(code=_print_error(con, e))

    if _ctx_json(ctx):
        print_json(con, resp)
        return

    items = resp.get("items") if isinstance(resp, dict) else []
    if not isinstance(items, list):
        items = []

    con.print(devices_table(items))


@devices_app.command("show")
def devices_show(
    ctx: typer.Context,
    device_id: str = typer.Argument(..., help="Device UUID"),
) -> None:
    """Show the operator debug bundle for a device."""

    c = _ctx_client(ctx)
    con: Console = ctx.obj["console"]

    try:
        resp = c.get_device_debug(device_id)
    except ApiError as e:
        raise typer.Exit(code=_print_error(con, e))

    if _ctx_json(ctx):
        print_json(con, resp)
        return

    device = resp.get("device") if isinstance(resp, dict) else None
    if isinstance(device, dict):
        con.print(_kv_table("Device", device))

    assignments = resp.get("assignments") if isinstance(resp, dict) else None
    if isinstance(assignments, list) and assignments:
        t = Table(title="Assignments")
        t.add_column("priority")
        t.add_column("mode")
        t.add_column("policy_name")
        t.add_column("policy_id", overflow="fold")
        for a in assignments:
            if not isinstance(a, dict):
                continue
            t.add_row(
                str(a.get("priority") or ""),
                str(a.get("mode") or ""),
                str(a.get("policy_name") or ""),
                str(a.get("policy_id") or ""),
            )
        con.print(t)

    last_run = resp.get("last_run") if isinstance(resp, dict) else None
    if isinstance(last_run, dict) and last_run:
        con.print(_kv_table("Last run", last_run))


@devices_app.command("delete")
def devices_delete(
    ctx: typer.Context,
    device_id: str = typer.Argument(..., help="Device UUID"),
    reason: str | None = typer.Option(None, "--reason", help="Optional reason"),
    yes: bool = typer.Option(False, "-y", "--yes", help="Skip confirmation"),
) -> None:
    """Soft-delete (deactivate) a device and revoke its device token."""

    con: Console = ctx.obj["console"]
    if not yes:
        if not typer.confirm(f"Soft delete device {device_id}?", default=False):
            raise typer.Exit(code=1)

    c = _ctx_client(ctx)

    try:
        resp = c.delete_device(device_id, reason=reason)
    except ApiError as e:
        raise typer.Exit(code=_print_error(con, e))

    if _ctx_json(ctx):
        print_json(con, resp)
        return

    con.print(_kv_table("Delete device", resp if isinstance(resp, dict) else {"result": resp}))


@devices_app.command("restore")
def devices_restore(
    ctx: typer.Context,
    device_id: str = typer.Argument(..., help="Device UUID"),
) -> None:
    """Restore a soft-deleted device and mint a new device token."""

    c = _ctx_client(ctx)
    con: Console = ctx.obj["console"]

    try:
        resp = c.restore_device(device_id)
    except ApiError as e:
        raise typer.Exit(code=_print_error(con, e))

    if _ctx_json(ctx):
        print_json(con, resp)
        return

    # Show the new token prominently (if present)
    token = resp.get("device_token") if isinstance(resp, dict) else None
    if token:
        con.print(f"[bold]New device token:[/bold] {token}")

    con.print(_kv_table("Restore device", resp if isinstance(resp, dict) else {"result": resp}))


@devices_app.command("revoke-token")
def devices_revoke_token(
    ctx: typer.Context,
    device_id: str = typer.Argument(..., help="Device UUID"),
) -> None:
    """Revoke (rotate) the current device token and mint a new one."""

    c = _ctx_client(ctx)
    con: Console = ctx.obj["console"]

    try:
        resp = c.revoke_device_token(device_id)
    except ApiError as e:
        raise typer.Exit(code=_print_error(con, e))

    if _ctx_json(ctx):
        print_json(con, resp)
        return

    token = resp.get("device_token") if isinstance(resp, dict) else None
    if token:
        con.print(f"[bold]New device token:[/bold] {token}")

    con.print(
        _kv_table("Revoke device token", resp if isinstance(resp, dict) else {"result": resp})
    )


# --- Assignments ---

assign_app = typer.Typer(help="Manage policy assignments.")
app.add_typer(assign_app, name="assign")


@assign_app.command("set")
def assign_set(
    ctx: typer.Context,
    policy_name: str = typer.Option(..., "--policy-name", help="Policy name"),
    device_id: str | None = typer.Option(None, "--device-id", help="Device UUID"),
    device_key: str | None = typer.Option(
        None,
        "--device-key",
        help="Device key (will resolve device id via devices list)",
    ),
    mode: str = typer.Option("enforce", "--mode", help="enforce|audit"),
    priority: int = typer.Option(9999, "--priority", help="Lower wins"),
) -> None:
    """Assign a policy to a device."""

    c = _ctx_client(ctx)
    con: Console = ctx.obj["console"]

    did = _resolve_device_id(c, device_id=device_id, device_key=device_key)

    payload = {
        "device_id": did,
        "policy_name": policy_name,
        "mode": mode,
        "priority": int(priority),
    }

    try:
        resp = c.assign_policy(payload)
    except ApiError as e:
        raise typer.Exit(code=_print_error(con, e))

    if _ctx_json(ctx):
        print_json(con, resp)
        return

    con.print(_kv_table("Assign policy", resp if isinstance(resp, dict) else {"result": resp}))


@assign_app.command("list")
def assign_list(
    ctx: typer.Context,
    device_id: str | None = typer.Option(None, "--device-id"),
    device_key: str | None = typer.Option(None, "--device-key"),
) -> None:
    """List policy assignments for a device."""

    c = _ctx_client(ctx)
    con: Console = ctx.obj["console"]

    did = _resolve_device_id(c, device_id=device_id, device_key=device_key)

    try:
        resp = c.list_device_assignments(did)
    except ApiError as e:
        raise typer.Exit(code=_print_error(con, e))

    if _ctx_json(ctx):
        print_json(con, resp)
        return

    assignments = resp.get("assignments") if isinstance(resp, dict) else None
    if not isinstance(assignments, list):
        assignments = []

    t = Table(title="Assignments")
    t.add_column("priority")
    t.add_column("mode")
    t.add_column("policy_name")
    t.add_column("policy_id", overflow="fold")

    for a in assignments:
        if not isinstance(a, dict):
            continue
        t.add_row(
            str(a.get("priority") or ""),
            str(a.get("mode") or ""),
            str(a.get("policy_name") or ""),
            str(a.get("policy_id") or ""),
        )

    con.print(t)


@assign_app.command("clear")
def assign_clear(
    ctx: typer.Context,
    device_id: str | None = typer.Option(None, "--device-id"),
    device_key: str | None = typer.Option(None, "--device-key"),
    yes: bool = typer.Option(False, "-y", "--yes"),
) -> None:
    """Clear all assignments for a device."""

    c = _ctx_client(ctx)
    con: Console = ctx.obj["console"]

    did = _resolve_device_id(c, device_id=device_id, device_key=device_key)

    if not yes:
        if not typer.confirm(f"Clear assignments for device {did}?", default=False):
            raise typer.Exit(code=1)

    try:
        resp = c.clear_device_assignments(did)
    except ApiError as e:
        raise typer.Exit(code=_print_error(con, e))

    if _ctx_json(ctx):
        print_json(con, resp)
        return

    con.print(_kv_table("Clear assignments", resp if isinstance(resp, dict) else {"result": resp}))


# --- Policies ---

policies_app = typer.Typer(help="Manage policies.")
app.add_typer(policies_app, name="policies")


@policies_app.command("upsert")
def policies_upsert(
    ctx: typer.Context,
    file: Path = typer.Option(..., "--file", exists=True, dir_okay=False, readable=True),
    name: str | None = typer.Option(None, "--name", help="Policy name (default: file stem)"),
    description: str = typer.Option("Upserted via baseliner-admin", "--description"),
    schema_version: str = typer.Option("1", "--schema-version"),
    active: bool = typer.Option(True, "--active/--inactive", help="Whether policy is active"),
) -> None:
    """Upsert a policy from a JSON file."""

    c = _ctx_client(ctx)
    con: Console = ctx.obj["console"]

    try:
        doc = json.loads(file.read_text(encoding="utf-8"))
    except Exception as e:
        raise typer.BadParameter(f"Failed to read policy file: {e}")

    policy_name = name or file.stem

    payload = {
        "name": policy_name,
        "description": description,
        "schema_version": schema_version,
        "document": doc,
        "is_active": bool(active),
    }

    try:
        resp = c.upsert_policy(payload)
    except ApiError as e:
        raise typer.Exit(code=_print_error(con, e))

    if _ctx_json(ctx):
        print_json(con, resp)
        return

    con.print(_kv_table("Upsert policy", resp if isinstance(resp, dict) else {"result": resp}))


# --- Audit ---

audit_app = typer.Typer(help="View admin audit events.")
app.add_typer(audit_app, name="audit")


@audit_app.command("tail")
def audit_tail(
    ctx: typer.Context,
    limit: int = typer.Option(20, "--limit", min=1, max=500),
    cursor: str | None = typer.Option(None, "--cursor"),
    action: str | None = typer.Option(None, "--action"),
    target_type: str | None = typer.Option(None, "--target-type"),
    target_id: str | None = typer.Option(None, "--target-id"),
) -> None:
    """List newest audit events."""

    c = _ctx_client(ctx)
    con: Console = ctx.obj["console"]

    try:
        resp = c.list_audit(
            limit=limit,
            cursor=cursor,
            action=action,
            target_type=target_type,
            target_id=target_id,
        )
    except ApiError as e:
        raise typer.Exit(code=_print_error(con, e))

    if _ctx_json(ctx):
        print_json(con, resp)
        return

    items = resp.get("items") if isinstance(resp, dict) else []
    if not isinstance(items, list):
        items = []

    con.print(audit_table(items))
    next_cursor = resp.get("next_cursor") if isinstance(resp, dict) else None
    if next_cursor:
        con.print(f"next_cursor: {next_cursor}")


# --- Runs ---

runs_app = typer.Typer(help="View runs.")
app.add_typer(runs_app, name="runs")


@runs_app.command("list")
def runs_list(
    ctx: typer.Context,
    device_id: str | None = typer.Option(None, "--device-id"),
    limit: int = typer.Option(50, "--limit", min=1, max=500),
    offset: int = typer.Option(0, "--offset", min=0),
) -> None:
    """List runs (optionally filtered by device_id)."""

    c = _ctx_client(ctx)
    con: Console = ctx.obj["console"]

    try:
        resp = c.list_runs(device_id=device_id, limit=limit, offset=offset)
    except ApiError as e:
        raise typer.Exit(code=_print_error(con, e))

    if _ctx_json(ctx):
        print_json(con, resp)
        return

    items = resp.get("items") if isinstance(resp, dict) else []
    if not isinstance(items, list):
        items = []

    con.print(runs_table(items))


@runs_app.command("show")
def runs_show(
    ctx: typer.Context,
    run_id: str = typer.Argument(..., help="Run UUID"),
) -> None:
    """Show run detail (items + logs)."""

    c = _ctx_client(ctx)
    con: Console = ctx.obj["console"]

    try:
        resp = c.get_run_detail(run_id)
    except ApiError as e:
        raise typer.Exit(code=_print_error(con, e))

    if _ctx_json(ctx):
        print_json(con, resp)
        return

    # Show a small summary by default.
    if isinstance(resp, dict):
        meta_keys = [
            "id",
            "device_id",
            "correlation_id",
            "started_at",
            "ended_at",
            "status",
            "agent_version",
            "effective_policy_hash",
        ]
        summary = {k: resp.get(k) for k in meta_keys if k in resp}
        con.print(_kv_table("Run", summary))

        items = resp.get("items")
        logs = resp.get("logs")

        if isinstance(items, list):
            con.print(f"items: {len(items)}")
        if isinstance(logs, list):
            con.print(f"logs: {len(logs)}")


# --- Helpers ---

def _print_error(console: Console, e: ApiError) -> int:
    console.print(f"[red]Request failed[/red] (HTTP {e.status_code})")
    try:
        console.print_json(json.dumps(e.detail, default=str))
    except Exception:
        console.print(str(e.detail))
    return 1


def main() -> None:
    app()
