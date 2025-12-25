from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from baseliner_admin.client import (
    DEFAULT_TENANT_ID,
    BaselinerAdminClient,
    ClientConfig,
)
from baseliner_admin.render import (
    render_assignments_list,
    render_assignments_plan,
    render_devices_list,
    render_device_tokens_list,
    render_enroll_tokens_list,
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
enroll_app = typer.Typer(add_completion=False, help="Enrollment token management")

app.add_typer(devices_app, name="devices")
app.add_typer(runs_app, name="runs")
app.add_typer(policies_app, name="policies")
app.add_typer(assignments_app, name="assignments")
app.add_typer(enroll_app, name="enroll")


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
    tenant_id: str = typer.Option(
        DEFAULT_TENANT_ID,
        "--tenant-id",
        envvar="BASELINER_TENANT_ID",
        help="Tenant id for the admin key (required by the server)",
    ),
    json_out: bool = typer.Option(False, "--json", help="Print machine-readable JSON"),
) -> None:
    if not server_url:
        raise typer.BadParameter("Server URL required (set BASELINER_SERVER_URL or --server)")
    if not admin_key:
        raise typer.BadParameter("Admin key required (set BASELINER_ADMIN_KEY or --admin-key)")
    if not tenant_id:
        raise typer.BadParameter("Tenant id required (set BASELINER_TENANT_ID or --tenant-id)")

    ctx.obj = {
        "server_url": server_url,
        "admin_key": admin_key,
        "tenant_id": tenant_id,
        "json": bool(json_out),
    }


def _client(ctx: typer.Context) -> BaselinerAdminClient:
    o = ctx.obj or {}
    return BaselinerAdminClient(
        ClientConfig(
            server=o["server_url"],
            admin_key=o["admin_key"],
            tenant_id=o["tenant_id"],
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



def _resolve_policy_id_and_name(
    *,
    client: BaselinerAdminClient,
    console: Console,
    policy_ref: str,
    include_inactive: bool = True,
) -> tuple[str, str]:
    """Resolve a policy ref to (policy_id, policy_name).

    policy_ref may be:
      - exact UUID
      - exact policy name
      - substring (must uniquely match)
    """

    policy_ref = policy_ref.strip()
    u = try_parse_uuid(policy_ref)
    if u:
        pol = client.policies_show(str(u))
        pid = str(pol.get("id") or "").strip()
        name = str(pol.get("name") or "").strip()
        if not pid or not name:
            console.print(f"Policy {u} missing id or name")
            raise typer.Exit(code=1)
        return pid, name

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
        pid = str(exact[0].get("id") or "").strip()
        name = str(exact[0].get("name") or "").strip()
        if not pid or not name:
            console.print(f"Policy matched but missing id/name: {policy_ref}")
            raise typer.Exit(code=1)
        return pid, name

    if len(items) == 1:
        pid = str(items[0].get("id") or "").strip()
        name = str(items[0].get("name") or "").strip()
        if not pid or not name:
            console.print(f"Policy matched but missing id/name: {policy_ref}")
            raise typer.Exit(code=1)
        return pid, name

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



def _assignment_key(a: dict[str, Any]) -> str:
    pid = str(a.get("policy_id") or "").strip().lower()
    if pid:
        return f"id:{pid}"
    name = str(a.get("policy_name") or "").strip().lower()
    return f"name:{name}"


def _load_assignments_file(path: Path) -> list[dict[str, Any]]:
    """Load an assignments JSON file.

    Supported formats:
      1) A JSON list of assignment objects
      2) A JSON object with an 'assignments' list

    Each assignment object should contain:
      - policy (policy name/uuid/substr) OR policy_id OR policy_name
      - priority (int)
      - mode (enforce|audit)
    """

    obj = read_json_file(path)
    if isinstance(obj, dict) and "assignments" in obj:
        obj = obj.get("assignments")

    if not isinstance(obj, list):
        raise typer.BadParameter(
            "Assignments file must be a JSON list, or an object with an 'assignments' list"
        )

    out: list[dict[str, Any]] = []
    for idx, item in enumerate(obj, start=1):
        if not isinstance(item, dict):
            raise typer.BadParameter(f"Assignment entry #{idx} must be an object")
        out.append(item)

    return out


def _normalize_assignment_spec(
    *,
    client: BaselinerAdminClient,
    console: Console,
    spec: dict[str, Any],
) -> dict[str, Any]:
    policy_ref = spec.get("policy") or spec.get("policy_ref")
    policy_id = spec.get("policy_id")
    policy_name = spec.get("policy_name")

    if policy_id and policy_name:
        pid = str(policy_id).strip()
        name = str(policy_name).strip()
        if not pid or not name:
            raise typer.BadParameter("policy_id/policy_name must not be empty")
    else:
        ref = str(policy_ref or policy_id or policy_name or "").strip()
        if not ref:
            raise typer.BadParameter("Each assignment must include policy/policy_id/policy_name")
        pid, name = _resolve_policy_id_and_name(client=client, console=console, policy_ref=ref)

    prio_raw = spec.get("priority")
    try:
        priority = int(prio_raw) if prio_raw is not None else 100
    except Exception:
        raise typer.BadParameter(f"Invalid priority: {prio_raw}")

    mode = _normalize_mode(str(spec.get("mode") or "enforce")) or "enforce"

    return {
        "policy_id": pid,
        "policy_name": name,
        "priority": priority,
        "mode": mode,
    }


def _plan_assignment_changes(
    *,
    current: list[dict[str, Any]],
    desired: list[dict[str, Any]],
    merge: bool,
) -> list[dict[str, Any]]:
    current_by_key = {_assignment_key(a): a for a in current}

    desired_keys: set[str] = set()
    rows: list[dict[str, Any]] = []

    for d in desired:
        k = _assignment_key(d)
        desired_keys.add(k)

        cur = current_by_key.get(k)
        desired_prio = int(d.get("priority") or 0)
        desired_mode = str(d.get("mode") or "").strip().lower()

        if cur:
            cur_prio_raw = cur.get("priority")
            try:
                cur_prio = int(cur_prio_raw) if cur_prio_raw is not None else 0
            except Exception:
                cur_prio = 0
            cur_mode = str(cur.get("mode") or "").strip().lower()

            action = "keep"
            if cur_prio != desired_prio or cur_mode != desired_mode:
                action = "update"

            rows.append(
                {
                    "action": action,
                    "policy_id": d.get("policy_id") or cur.get("policy_id"),
                    "policy_name": d.get("policy_name") or cur.get("policy_name"),
                    "priority": desired_prio,
                    "mode": desired_mode,
                    "current_priority": cur_prio,
                    "current_mode": cur_mode,
                }
            )
        else:
            rows.append(
                {
                    "action": "add",
                    "policy_id": d.get("policy_id"),
                    "policy_name": d.get("policy_name"),
                    "priority": desired_prio,
                    "mode": desired_mode,
                    "current_priority": None,
                    "current_mode": None,
                }
            )

    if not merge:
        for cur in current:
            k = _assignment_key(cur)
            if k in desired_keys:
                continue
            rows.append(
                {
                    "action": "remove",
                    "policy_id": cur.get("policy_id"),
                    "policy_name": cur.get("policy_name"),
                    "priority": None,
                    "mode": None,
                    "current_priority": cur.get("priority"),
                    "current_mode": cur.get("mode"),
                }
            )

    order = {"remove": 0, "update": 1, "add": 2, "keep": 3}
    rows.sort(
        key=lambda r: (
            int(order.get(str(r.get("action") or ""), 9)),
            str(r.get("policy_name") or ""),
        )
    )

    return rows


def _plan_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    out = {"add": 0, "update": 0, "remove": 0, "keep": 0}
    for r in rows:
        a = str(r.get("action") or "")
        if a == "set":
            out["add"] += 1
            continue
        if a in out:
            out[a] += 1
    return out


@app.command("tui", help="EXPERIMENTAL: prompt-driven operator console")
def tui(ctx: typer.Context) -> None:
    if ctx.obj.get("json"):
        raise typer.BadParameter("--json is not supported for the interactive tui")

    console = _console()
    if not (os.isatty(0) and os.isatty(1)):
        die_tui_not_supported(console)

    run_tui(client=_client(ctx), console=console)



@enroll_app.command("create")
def enroll_create(
    ctx: typer.Context,
    ttl_seconds: int | None = typer.Option(
        None, "--ttl-seconds", help="If set, server computes expires_at = now + ttl_seconds"
    ),
    expires_at: str | None = typer.Option(
        None,
        "--expires-at",
        help="Absolute expiry timestamp (ISO 8601). Overrides --ttl-seconds.",
    ),
    note: str | None = typer.Option(None, "--note"),
) -> None:
    c = _client(ctx)
    payload = c.enroll_token_create(ttl_seconds=ttl_seconds, expires_at=expires_at, note=note)
    if ctx.obj.get("json"):
        print(c.pretty_json(payload))
        return
    _console().print_json(data=payload)


@enroll_app.command("list")
def enroll_list(
    ctx: typer.Context,
    limit: int = typer.Option(50, "--limit"),
    offset: int = typer.Option(0, "--offset"),
    include_used: bool = typer.Option(False, "--include-used"),
    include_expired: bool = typer.Option(True, "--include-expired"),
) -> None:
    c = _client(ctx)
    payload = c.enroll_tokens_list(
        limit=limit,
        offset=offset,
        include_used=include_used,
        include_expired=include_expired,
    )
    if ctx.obj.get("json"):
        print(c.pretty_json(payload))
        return
    render_enroll_tokens_list(_console(), payload)


@enroll_app.command("revoke")
def enroll_revoke(
    ctx: typer.Context,
    token_id: str = typer.Argument(..., help="Enroll token UUID"),
    reason: str | None = typer.Option(None, "--reason"),
) -> None:
    c = _client(ctx)
    payload = c.enroll_token_revoke(token_id, reason=reason)
    if ctx.obj.get("json"):
        print(c.pretty_json(payload))
        return
    _console().print_json(data=payload)


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


@devices_app.command("tokens")
def devices_tokens(ctx: typer.Context, device_id: str) -> None:
    """Show device auth token history (hash prefixes + timestamps)."""
    c = _client(ctx)
    payload = c.devices_tokens(device_id)
    if ctx.obj.get("json"):
        print(c.pretty_json(payload))
        return
    render_device_tokens_list(_console(), payload, title=f"Device tokens: {device_id}")

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


@assignments_app.command("apply")
def assignments_apply(
    ctx: typer.Context,
    device_ref: str = typer.Argument(..., help="device UUID or substring match on device_key/hostname"),
    file: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True, help="JSON assignments file"),
    merge: bool = typer.Option(
        False,
        "--merge",
        help="Only add/update desired assignments; do not remove existing extra assignments",
    ),
    clear_first: bool = typer.Option(
        False,
        "--clear-first",
        help="Clear all existing assignments before applying the file",
    ),
    plan: bool = typer.Option(False, "--plan", help="Show the plan and exit (no changes)"),
    yes: bool = typer.Option(False, "--yes", help="Do not prompt for confirmation"),
) -> None:
    c = _client(ctx)
    console = _console()

    device_id = _resolve_device_id(
        client=c, console=console, device_ref=device_ref, include_deleted=True
    )

    specs = _load_assignments_file(file)
    desired = [
        _normalize_assignment_spec(client=c, console=console, spec=s)
        for s in specs
    ]

    current_payload = c.device_assignments_list(device_id)
    current = list(current_payload.get("assignments") or [])

    if clear_first:
        rows = [
            {
                "action": "set",
                "policy_id": d.get("policy_id"),
                "policy_name": d.get("policy_name"),
                "priority": d.get("priority"),
                "mode": d.get("mode"),
                "current_priority": None,
                "current_mode": None,
            }
            for d in desired
        ]
    else:
        rows = _plan_assignment_changes(current=current, desired=desired, merge=bool(merge))

    counts = _plan_counts(rows)

    if ctx.obj.get("json"):
        print(
            c.pretty_json(
                {
                    "device_id": device_id,
                    "clear_first": bool(clear_first),
                    "merge": bool(merge),
                    "file": str(file),
                    "plan": rows,
                    "counts": counts,
                    "dry_run": bool(plan),
                }
            )
        )
        if plan:
            return

    if not ctx.obj.get("json"):
        console.print(f"Device: {device_id}")
        if clear_first:
            console.print(
                f"[yellow]Will clear[/yellow] {len(current)} existing assignments, then set {len(desired)} from file."
            )
        render_assignments_plan(console, rows, device_id=device_id)
        console.print(
            f"add={counts['add']} update={counts['update']} remove={counts['remove']} keep={counts['keep']}"
        )

    if plan:
        return

    if clear_first and merge:
        raise typer.BadParameter("--clear-first and --merge are mutually exclusive")

    if not yes:
        msg = "Apply these changes?"
        if counts.get("remove"):
            msg = f"Apply these changes? (includes {counts['remove']} removals)"
        if not typer.confirm(msg, default=False):
            raise typer.Exit(code=0)

    if clear_first:
        c.device_assignments_clear(device_id)
        for d in desired:
            c.assignment_set(
                device_id=device_id,
                policy_name=str(d.get("policy_name")),
                priority=int(d.get("priority") or 0),
                mode=str(d.get("mode") or "enforce"),
            )
    else:
        for r in rows:
            a = str(r.get("action") or "")
            if a == "remove":
                c.device_assignment_remove(device_id, str(r.get("policy_id")))
            elif a in ("add", "update"):
                c.assignment_set(
                    device_id=device_id,
                    policy_name=str(r.get("policy_name")),
                    priority=int(r.get("priority") or 0),
                    mode=str(r.get("mode") or "enforce"),
                )

    if ctx.obj.get("json"):
        print(
            c.pretty_json(
                {
                    "ok": True,
                    "device_id": device_id,
                    "applied": True,
                    "counts": counts,
                }
            )
        )
        return

    console.print("[green]OK[/green]")


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
    """Clone policy assignments from one device to another.

    Behavior:
      - --clear-first: replace destination assignments with source assignments
      - --merge: add/update source assignments on destination, leaving extras untouched

    In merge mode, this command is drift-aware: it only calls the server for
    assignments that would change (add/update), and shows a plan with actions.
    """

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

    desired: list[dict[str, Any]] = []
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
        desired.append(
            {
                "policy_name": pn,
                "policy_id": a.get("policy_id"),
                "priority": pri,
                "mode": m,
                "is_active": a.get("is_active"),
            }
        )

    current_payload = c.device_assignments_list(dst_id)
    current = list(current_payload.get("assignments") or [])

    if clear_first:
        rows = [
            {
                "action": "set",
                "policy_id": d.get("policy_id"),
                "policy_name": d.get("policy_name"),
                "priority": d.get("priority"),
                "mode": d.get("mode"),
                "current_priority": None,
                "current_mode": None,
            }
            for d in desired
        ]
    else:
        # merge behavior (do not remove extras)
        rows = _plan_assignment_changes(current=current, desired=desired, merge=True)

    counts = _plan_counts(rows)

    if ctx.obj.get("json"):
        print(
            c.pretty_json(
                {
                    "source_device_id": src_id,
                    "dest_device_id": dst_id,
                    "clear_first": bool(clear_first),
                    "priority_offset": int(priority_offset),
                    "mode_override": mode_override,
                    "plan": rows,
                    "counts": counts,
                    "dry_run": bool(dry_run),
                }
            )
        )
        if dry_run:
            return

    if not ctx.obj.get("json"):
        console.print("[bold]Clone plan[/bold]")
        console.print(f"source={src_id}")
        console.print(f"dest={dst_id}")
        if clear_first:
            console.print(
                f"[yellow]Will clear[/yellow] {len(current)} existing assignments, then set {len(desired)} from source."
            )
        render_assignments_plan(console, rows, device_id=dst_id)
        console.print(
            f"add={counts['add']} update={counts['update']} remove={counts['remove']} keep={counts['keep']}"
        )

    if dry_run:
        return

    # No-op fast path.
    if not clear_first and (counts.get("add", 0) + counts.get("update", 0)) == 0:
        console.print("No changes needed.")
        return

    if not yes:
        msg = "Apply assignments to destination device?"
        if clear_first:
            msg = "Clear destination assignments and apply source assignments?"
        if not typer.confirm(msg, default=False):
            raise typer.Exit(code=2)

    if clear_first:
        c.device_assignments_clear(dst_id)
        for d in desired:
            c.assignment_set(
                device_id=dst_id,
                policy_name=str(d["policy_name"]),
                priority=int(d["priority"]),
                mode=str(d["mode"]),
            )
    else:
        for r in rows:
            a = str(r.get("action") or "")
            if a not in ("add", "update"):
                continue
            c.assignment_set(
                device_id=dst_id,
                policy_name=str(r.get("policy_name")),
                priority=int(r.get("priority") or 0),
                mode=str(r.get("mode") or "enforce"),
            )

    console.print(f"Applied assignments to {dst_id}.")



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
