from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from rich.console import Console
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table

from baseliner_admin.client import BaselinerAdminClient
from baseliner_admin.render import (
    render_assignments_list,
    render_devices_list,
    render_device_tokens_list,
    render_enroll_tokens_list,
    render_policy_detail,
    render_policies_list,
    render_run_detail,
    render_runs_list,
)
from baseliner_admin.util import read_json_file, try_parse_uuid


@dataclass(frozen=True)
class _Pick:
    label: str
    value: Any


def run_tui(
    *,
    client: BaselinerAdminClient,
    console: Console,
) -> None:
    while True:
        console.clear()
        console.print(
            f"[bold]Baseliner Admin TUI[/bold] (tenant={client.cfg.tenant_id})"
        )
        choice = Prompt.ask(
            "Menu",
            choices=["devices", "policies", "runs", "enroll", "audit", "exit"],
            default="devices",
        )

        try:
            if choice == "devices":
                _devices_menu(client=client, console=console)
            elif choice == "policies":
                _policies_menu(client=client, console=console)
            elif choice == "runs":
                _runs_menu(client=client, console=console)
            elif choice == "enroll":
                _enroll_tokens_menu(client=client, console=console)
            elif choice == "audit":
                _audit_menu(client=client, console=console)
            elif choice == "exit":
                raise SystemExit(0)
        except KeyboardInterrupt:
            console.print("\n(back)")
            continue


def _pause(console: Console) -> None:
    Prompt.ask("Press Enter to continue", default="")


def _pick_from_table(
    *,
    console: Console,
    title: str,
    items: list[_Pick],
    columns: list[tuple[str, Callable[[_Pick], str]]],
    allow_back: bool = True,
) -> _Pick | None:
    console.clear()
    console.print(f"[bold]{title}[/bold]")

    if not items:
        console.print("(no items)")
        _pause(console)
        return None

    t = Table(show_header=True, header_style="bold")
    t.add_column("#", justify="right")
    for col, _fn in columns:
        t.add_column(col, overflow="fold")

    for i, item in enumerate(items, start=1):
        row = [str(i)]
        for _col, fn in columns:
            row.append(fn(item))
        t.add_row(*row)

    console.print(t)

    choices = [str(i) for i in range(1, len(items) + 1)]
    if allow_back:
        choices.append("b")

    pick = Prompt.ask("Pick", choices=choices, default="b" if allow_back else choices[0])
    if allow_back and pick == "b":
        return None

    return items[int(pick) - 1]


def _resolve_device(
    *,
    client: BaselinerAdminClient,
    console: Console,
    device_ref: str,
    include_deleted: bool = True,
) -> dict[str, Any] | None:
    device_ref = device_ref.strip()
    payload = client.devices_list(limit=500, offset=0, include_deleted=include_deleted)
    items = list(payload.get("items") or [])

    parsed = try_parse_uuid(device_ref)
    if parsed:
        matches = [d for d in items if str(d.get("id")) == str(parsed)]
    else:
        q = device_ref.lower()
        matches = [
            d
            for d in items
            if q in str(d.get("device_key") or "").lower()
            or q in str(d.get("hostname") or "").lower()
        ]

    if not matches:
        console.print(f"No devices matched '{device_ref}'.")
        _pause(console)
        return None

    if len(matches) == 1:
        return matches[0]

    pick = _pick_from_table(
        console=console,
        title="Matching devices",
        items=[_Pick(label=str(m.get("device_key")), value=m) for m in matches],
        columns=[
            ("device_key", lambda p: str(p.value.get("device_key") or "")),
            ("hostname", lambda p: str(p.value.get("hostname") or "")),
            ("status", lambda p: str(p.value.get("status") or "")),
        ],
    )
    return pick.value if pick else None


def _devices_menu(*, client: BaselinerAdminClient, console: Console) -> None:
    while True:
        console.clear()
        console.print("[bold]Devices[/bold]")
        choice = Prompt.ask(
            "Action",
            choices=["list", "show", "back"],
            default="list",
        )
        if choice == "back":
            return

        if choice == "list":
            limit = IntPrompt.ask("Limit", default=25)
            offset = IntPrompt.ask("Offset", default=0)
            payload = client.devices_list(limit=limit, offset=offset)
            console.clear()
            render_devices_list(console, payload, title=f"Devices (limit={limit}, offset={offset})")
            _pause(console)
            continue

        if choice == "show":
            raw = Prompt.ask("Device ID or device_key")
            dev = _resolve_device(client=client, console=console, device_ref=raw)
            if dev:
                _device_detail_menu(client=client, console=console, device=dev)
            continue


def _device_detail_menu(
    *,
    client: BaselinerAdminClient,
    console: Console,
    device: dict[str, Any],
) -> None:
    device_id = str(device.get("id") or "")
    if not device_id:
        console.print("Selected device missing id")
        _pause(console)
        return

    while True:
        console.clear()
        console.print(f"[bold]Device[/bold] {device.get('device_key')} ({device_id})")
        console.print(f"hostname={device.get('hostname')} status={device.get('status')}")

        action = Prompt.ask(
            "Action",
            choices=["debug", "tokens", "assignments", "delete", "restore", "revoke-token", "back"],
            default="debug",
        )

        if action == "back":
            return

        try:
            if action == "debug":
                payload = client.devices_debug(device_id)
                console.clear()
                console.print_json(data=payload)
                _pause(console)

            elif action == "tokens":
                payload = client.devices_tokens(device_id)
                render_device_tokens_list(
                    console,
                    payload,
                    title=f"Device tokens: {device.get('device_key')} ({device_id})",
                )
                _pause(console)

            elif action == "assignments":
                _device_assignments_menu(
                    client=client,
                    console=console,
                    device_id=device_id,
                    device_key=str(device.get("device_key") or ""),
                )

            elif action == "delete":
                reason = Prompt.ask("Reason (optional)", default="")
                if not Confirm.ask(
                    f"Soft-delete device {device.get('device_key')}?", default=False
                ):
                    continue
                payload = client.devices_delete(device_id, reason=reason or None)
                console.print_json(data=payload)
                _pause(console)

            elif action == "restore":
                if not Confirm.ask(
                    f"Restore device {device.get('device_key')} and mint new token?", default=False
                ):
                    continue
                payload = client.devices_restore(device_id)
                console.print_json(data=payload)
                _pause(console)

            elif action == "revoke-token":
                if not Confirm.ask(
                    f"Revoke token for {device.get('device_key')} and mint new token?",
                    default=False,
                ):
                    continue
                payload = client.devices_revoke_token(device_id)
                console.print_json(data=payload)
                _pause(console)

        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            _pause(console)


def _device_assignments_menu(
    *,
    client: BaselinerAdminClient,
    console: Console,
    device_id: str,
    device_key: str,
) -> None:
    while True:
        console.clear()
        console.print(f"[bold]Assignments[/bold] for {device_key} ({device_id})")

        action = Prompt.ask(
            "Action",
            choices=["list", "set", "remove", "clear", "back"],
            default="list",
        )

        if action == "back":
            return

        try:
            if action == "list":
                payload = client.assignments_list(device_id=device_id)
                console.clear()
                render_assignments_list(console, payload, title=f"Assignments for {device_key}")
                _pause(console)

            elif action == "set":
                policy_name = Prompt.ask("Policy name (or UUID)")
                prio = IntPrompt.ask("Priority", default=100)
                mode = Prompt.ask("Mode (enforce/audit)", default="enforce")
                payload = client.assignment_set(
                    device_id=device_id,
                    policy_name=policy_name,
                    priority=prio,
                    mode=mode,
                )
                console.print_json(data=payload)
                _pause(console)

            elif action == "remove":
                policy_id = Prompt.ask("Policy UUID")
                payload = client.device_assignment_remove(
                    device_id=device_id, policy_id=policy_id
                )
                console.print_json(data=payload)
                _pause(console)

            elif action == "clear":
                if not Confirm.ask(
                    f"Clear all assignments for {device_key}?", default=False
                ):
                    continue
                payload = client.device_assignments_clear(device_id)
                console.print_json(data=payload)
                _pause(console)

        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            _pause(console)


def _policies_menu(*, client: BaselinerAdminClient, console: Console) -> None:
    while True:
        console.clear()
        console.print("[bold]Policies[/bold]")
        choice = Prompt.ask(
            "Action",
            choices=["list", "show", "create", "back"],
            default="list",
        )
        if choice == "back":
            return

        try:
            if choice == "list":
                limit = IntPrompt.ask("Limit", default=25)
                offset = IntPrompt.ask("Offset", default=0)
                payload = client.policies_list(limit=limit, offset=offset)
                console.clear()
                render_policies_list(
                    console, payload, title=f"Policies (limit={limit}, offset={offset})"
                )
                _pause(console)

            elif choice == "show":
                raw = Prompt.ask("Policy UUID")
                payload = client.policies_show(raw)
                console.clear()
                render_policy_detail(console, payload, title=f"Policy {raw}")
                _pause(console)

            elif choice == "create":
                path = Prompt.ask("Path to policy JSON")
                data = read_json_file(Path(path))
                payload = client.policies_upsert(data)
                console.print_json(data=payload)
                _pause(console)

        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            _pause(console)


def _runs_menu(*, client: BaselinerAdminClient, console: Console) -> None:
    while True:
        console.clear()
        console.print("[bold]Runs[/bold]")
        choice = Prompt.ask(
            "Action",
            choices=["list", "show", "back"],
            default="list",
        )
        if choice == "back":
            return

        try:
            if choice == "list":
                limit = IntPrompt.ask("Limit", default=25)
                offset = IntPrompt.ask("Offset", default=0)
                payload = client.runs_list(limit=limit, offset=offset)
                console.clear()
                render_runs_list(console, payload, title=f"Runs (limit={limit}, offset={offset})")
                _pause(console)

            elif choice == "show":
                raw = Prompt.ask("Run UUID")
                payload = client.runs_show(raw)
                console.clear()
                render_run_detail(console, payload, title=f"Run {raw}")
                _pause(console)

        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            _pause(console)


def _enroll_tokens_menu(*, client: BaselinerAdminClient, console: Console) -> None:
    while True:
        console.clear()
        console.print("[bold]Enroll tokens[/bold]")
        choice = Prompt.ask(
            "Action",
            choices=["list", "create", "revoke", "back"],
            default="list",
        )
        if choice == "back":
            return

        try:
            if choice == "list":
                limit = IntPrompt.ask("Limit", default=25)
                offset = IntPrompt.ask("Offset", default=0)
                include_used = Confirm.ask("Include used?", default=True)
                include_expired = Confirm.ask("Include expired?", default=True)
                payload = client.enroll_tokens_list(
                    limit=limit,
                    offset=offset,
                    include_used=include_used,
                    include_expired=include_expired,
                )
                console.clear()
                render_enroll_tokens_list(console, payload)
                _pause(console)

            elif choice == "create":
                ttl = IntPrompt.ask("TTL seconds (0 = none)", default=3600)
                note = Prompt.ask("Note (optional)", default="")
                payload = client.enroll_token_create(
                    ttl_seconds=ttl if ttl > 0 else None, note=note or None
                )
                console.print_json(data=payload)
                _pause(console)

            elif choice == "revoke":
                raw = Prompt.ask("Token UUID")
                reason = Prompt.ask("Reason (optional)", default="")
                payload = client.enroll_token_revoke(raw, reason=reason or None)
                console.print_json(data=payload)
                _pause(console)

        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            _pause(console)


def _audit_menu(*, client: BaselinerAdminClient, console: Console) -> None:
    while True:
        console.clear()
        console.print("[bold]Audit log[/bold]")
        choice = Prompt.ask(
            "Action",
            choices=["list", "back"],
            default="list",
        )
        if choice == "back":
            return

        try:
            if choice == "list":
                limit = IntPrompt.ask("Limit", default=50)
                cursor = Prompt.ask("Cursor (blank for none)", default="")
                payload = client.audit_list(limit=limit, cursor=cursor or None)
                console.clear()
                console.print_json(data=payload)
                _pause(console)

        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            _pause(console)


def die_tui_not_supported() -> None:
    raise SystemExit("TUI is not supported in this environment.")
