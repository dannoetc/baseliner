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
    render_assignments_plan,
    render_devices_list,
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
    """Experimental prompt-driven "TUI".

    This is intentionally not a full-screen, arrow-key UI yet. It's a set of
    interactive prompts + tables that exercise our admin API in a way that feels
    like a small operator console.
    """

    console.print("[bold yellow]EXPERIMENTAL[/bold yellow] baseliner-admin tui")
    console.print(
        "This is a prompt-driven interface (not a full-screen TUI). "
        "Expect breaking changes as we iterate."
    )
    if not Confirm.ask("Continue?", default=True):
        raise SystemExit(0)

    while True:
        console.clear()
        console.print("[bold]Baseliner Admin[/bold]")
        choice = Prompt.ask(
            "Choose",
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
    columns: list[str],
    row_fn: Callable[[_Pick], list[str]],
    allow_cancel: bool = True,
) -> _Pick | None:
    if not items:
        console.print("(no results)")
        return None

    table = Table(title=title)
    table.add_column("#", justify="right")
    for c in columns:
        table.add_column(c)

    for i, it in enumerate(items, start=1):
        table.add_row(str(i), *row_fn(it))

    console.print(table)

    if allow_cancel:
        console.print("Enter 0 to cancel")

    while True:
        n = IntPrompt.ask("Select", default=0 if allow_cancel else 1)
        if allow_cancel and n == 0:
            return None
        if 1 <= n <= len(items):
            return items[n - 1]
        console.print("Invalid selection")




def _enroll_tokens_menu(*, client: BaselinerAdminClient, console: Console) -> None:
    while True:
        console.clear()
        payload = client.enroll_tokens_list(limit=200, offset=0, include_used=True, include_expired=True)
        render_enroll_tokens_list(console, payload, title="Enroll tokens (newest first)")

        action = Prompt.ask(
            "Action",
            choices=["create", "revoke", "refresh", "back"],
            default="create",
        )
        if action == "back":
            return
        if action == "refresh":
            continue

        try:
            if action == "create":
                ttl = IntPrompt.ask("TTL seconds (0 for none)", default=3600)
                note = Prompt.ask("Note (optional)", default="")
                payload = client.enroll_token_create(
                    ttl_seconds=int(ttl) if int(ttl) > 0 else None,
                    note=note or None,
                )
                console.print_json(data=payload)
                _pause(console)

            elif action == "revoke":
                token_id = Prompt.ask("Token ID (uuid)")
                reason = Prompt.ask("Reason (optional)", default="")
                if not Confirm.ask(f"Revoke enroll token {token_id}?", default=False):
                    continue
                payload = client.enroll_token_revoke(token_id, reason=reason or None)
                console.print_json(data=payload)
                _pause(console)

        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            _pause(console)

def _devices_menu(*, client: BaselinerAdminClient, console: Console) -> None:
    include_deleted = Confirm.ask("Include deleted devices?", default=False)
    q = Prompt.ask("Search (substring) - blank for all", default="").strip().lower()

    payload = client.devices_list(limit=500, offset=0, include_deleted=include_deleted)
    items: list[dict[str, Any]] = list(payload.get("items") or [])

    if q:
        items = [
            d
            for d in items
            if q in str(d.get("device_key") or "").lower()
            or q in str(d.get("hostname") or "").lower()
        ]

    console.clear()
    render_devices_list(console, {"items": items, "total": len(items), "limit": 500, "offset": 0})

    picks = [
        _Pick(
            label=str(d.get("device_key") or d.get("id") or ""),
            value=d,
        )
        for d in items
    ]

    picked = _pick_from_table(
        console=console,
        title="Pick device",
        items=picks,
        columns=["device_key", "hostname", "status", "id"],
        row_fn=lambda it: [
            str((it.value or {}).get("device_key") or ""),
            str((it.value or {}).get("hostname") or ""),
            str((it.value or {}).get("status") or ""),
            str((it.value or {}).get("id") or ""),
        ],
    )
    if not picked:
        return

    device = picked.value
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
        console, payload, title=f"Device tokens: {device.get('device_key')} ({device_id})"
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
        payload = client.device_assignments_list(device_id)
        render_assignments_list(console, payload, title=f"Assignments for {device_key}")

        assignments = list(payload.get("assignments") or [])
        action = Prompt.ask(
            "Action",
            choices=["set", "edit", "remove", "clone", "apply-file", "clear", "refresh", "back"],
            default="set",
        )

        if action == "back":
            return
        if action == "refresh":
            continue

        if action == "clear":
            if not Confirm.ask("Clear all assignments?", default=False):
                continue
            resp = client.device_assignments_clear(device_id)
            console.print_json(data=resp)
            _pause(console)
            continue

        if action == "edit":
            if not assignments:
                console.print("No assignments to edit.")
                _pause(console)
                continue

            picks = [_Pick(label=str(a.get("policy_name") or ""), value=a) for a in assignments]
            picked = _pick_from_table(
                console=console,
                title="Pick assignment",
                items=picks,
                columns=["policy", "priority", "mode"],
                row_fn=lambda it: [
                    str((it.value or {}).get("policy_name") or ""),
                    str((it.value or {}).get("priority") or ""),
                    str((it.value or {}).get("mode") or ""),
                ],
            )
            if not picked:
                continue

            assn = picked.value or {}
            policy_name = str(assn.get("policy_name") or "").strip()
            if not policy_name:
                console.print("Selected assignment missing policy_name")
                _pause(console)
                continue

            current_mode = str(assn.get("mode") or "enforce").strip().lower()
            if current_mode not in ("enforce", "audit"):
                current_mode = "enforce"
            current_priority = int(assn.get("priority") or 9999)

            mode = Prompt.ask("Mode", choices=["enforce", "audit"], default=current_mode).strip()
            priority = IntPrompt.ask("Priority (lower wins)", default=current_priority)

            resp = client.assignment_set(
                device_id=device_id,
                policy_name=policy_name,
                priority=int(priority),
                mode=mode,
            )
            console.print_json(data=resp)
            _pause(console)
            continue

        if action == "remove":
            if not assignments:
                console.print("No assignments to remove.")
                _pause(console)
                continue

            picks = [_Pick(label=str(a.get("policy_name") or ""), value=a) for a in assignments]
            picked = _pick_from_table(
                console=console,
                title="Pick assignment to remove",
                items=picks,
                columns=["policy", "priority", "mode"],
                row_fn=lambda it: [
                    str((it.value or {}).get("policy_name") or ""),
                    str((it.value or {}).get("priority") or ""),
                    str((it.value or {}).get("mode") or ""),
                ],
            )
            if not picked:
                continue

            assn = picked.value or {}
            policy_id = str(assn.get("policy_id") or "").strip()
            policy_name = str(assn.get("policy_name") or "").strip()
            if not policy_id or not policy_name:
                console.print("Selected assignment missing policy_id or policy_name")
                _pause(console)
                continue

            if not Confirm.ask(f"Remove assignment '{policy_name}'?", default=False):
                continue

            resp = client.device_assignment_remove(device_id, policy_id)
            console.print_json(data=resp)
            _pause(console)
            continue

        if action == "apply-file":
            path_s = Prompt.ask("Assignments file path (json)").strip()
            if not path_s:
                continue

            try:
                obj = read_json_file(Path(path_s))
            except Exception as e:
                console.print(f"[red]Failed to read JSON:[/red] {e}")
                _pause(console)
                continue

            if isinstance(obj, dict) and "assignments" in obj:
                obj = obj.get("assignments")

            if not isinstance(obj, list):
                console.print("Assignments file must be a JSON list or an object with an 'assignments' list")
                _pause(console)
                continue

            desired: list[dict[str, Any]] = []

            for i, spec in enumerate(obj):
                if not isinstance(spec, dict):
                    console.print(f"Entry #{i + 1} is not an object")
                    _pause(console)
                    desired = []
                    break

                pref = (
                    spec.get("policy")
                    or spec.get("policy_ref")
                    or spec.get("policy_name")
                    or spec.get("policy_id")
                )
                if not pref:
                    console.print(f"Entry #{i + 1} is missing 'policy'/'policy_name'/'policy_id'")
                    _pause(console)
                    desired = []
                    break

                policy_id = str(spec.get("policy_id") or "").strip()
                policy_name = str(spec.get("policy_name") or "").strip()

                # Resolve policy if needed.
                if not policy_id or not policy_name:
                    ref = str(pref).strip()
                    pol: dict[str, Any] | None = None

                    uid = try_parse_uuid(ref)
                    if uid:
                        try:
                            pol = client.policies_show(str(uid))
                        except Exception as e:
                            console.print(f"[red]Failed to resolve policy UUID '{ref}':[/red] {e}")
                            _pause(console)
                            desired = []
                            break
                    else:
                        pols = client.policies_list(limit=50, offset=0, include_inactive=True, q=ref)
                        items = list(pols.get("items") or [])
                        if not items:
                            console.print(f"No policies matched '{ref}'")
                            _pause(console)
                            desired = []
                            break
                        if len(items) == 1:
                            pol = items[0]
                        else:
                            picks = [
                                _Pick(label=str(p.get("name") or p.get("id") or ""), value=p)
                                for p in items
                            ]
                            picked = _pick_from_table(
                                console=console,
                                title=f"Pick policy for entry #{i + 1} ({ref})",
                                items=picks,
                                columns=["name", "active", "id"],
                                row_fn=lambda it: [
                                    str((it.value or {}).get("name") or ""),
                                    "yes" if (it.value or {}).get("is_active") else "no",
                                    str((it.value or {}).get("id") or ""),
                                ],
                            )
                            if not picked:
                                desired = []
                                break
                            pol = picked.value

                    if not pol:
                        desired = []
                        break

                    policy_id = str(pol.get("id") or "").strip()
                    policy_name = str(pol.get("name") or "").strip()

                if not policy_id or not policy_name:
                    console.print(f"Entry #{i + 1} could not resolve policy")
                    _pause(console)
                    desired = []
                    break

                mode = str(spec.get("mode") or "enforce").strip().lower()
                if mode not in ("enforce", "audit"):
                    mode = "enforce"

                try:
                    priority = int(spec.get("priority") if spec.get("priority") is not None else 9999)
                except Exception:
                    priority = 9999

                desired.append(
                    {
                        "policy_id": policy_id,
                        "policy_name": policy_name,
                        "priority": int(priority),
                        "mode": mode,
                    }
                )

            if not desired:
                continue

            clear_first = Confirm.ask("Clear existing assignments first?", default=False)
            merge_only = True
            if not clear_first:
                merge_only = Confirm.ask("Merge only (do not remove extras)?", default=True)

            current_payload = client.device_assignments_list(device_id)
            current = list(current_payload.get("assignments") or [])

            def _key(a: dict[str, Any]) -> str:
                pid = str(a.get("policy_id") or "").strip().lower()
                return pid or str(a.get("policy_name") or "").strip().lower()

            cur_by = {_key(a): a for a in current}
            desired_keys = set()
            rows: list[dict[str, Any]] = []

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
                for d in desired:
                    k = _key(d)
                    desired_keys.add(k)
                    cur = cur_by.get(k)
                    if cur:
                        cp = cur.get("priority")
                        cm = str(cur.get("mode") or "").strip().lower()
                        if int(cp or 0) == int(d.get("priority") or 0) and cm == str(d.get("mode") or ""):
                            action_ = "keep"
                        else:
                            action_ = "update"
                        rows.append(
                            {
                                "action": action_,
                                "policy_id": d.get("policy_id"),
                                "policy_name": d.get("policy_name"),
                                "priority": d.get("priority"),
                                "mode": d.get("mode"),
                                "current_priority": cur.get("priority"),
                                "current_mode": cur.get("mode"),
                            }
                        )
                    else:
                        rows.append(
                            {
                                "action": "add",
                                "policy_id": d.get("policy_id"),
                                "policy_name": d.get("policy_name"),
                                "priority": d.get("priority"),
                                "mode": d.get("mode"),
                                "current_priority": None,
                                "current_mode": None,
                            }
                        )

                if not merge_only:
                    for a in current:
                        k = _key(a)
                        if k in desired_keys:
                            continue
                        rows.append(
                            {
                                "action": "remove",
                                "policy_id": a.get("policy_id"),
                                "policy_name": a.get("policy_name"),
                                "priority": None,
                                "mode": None,
                                "current_priority": a.get("priority"),
                                "current_mode": a.get("mode"),
                            }
                        )

            console.print("[bold]Plan[/bold]")
            if clear_first:
                console.print(
                    f"[yellow]Will clear[/yellow] {len(current)} existing assignments, then set {len(desired)} from file."
                )
            render_assignments_plan(console, rows, device_id=device_id)

            if not Confirm.ask("Proceed?", default=False):
                continue

            if clear_first:
                client.device_assignments_clear(device_id)

            removed = 0
            set_count = 0
            for r in rows:
                act = str(r.get("action") or "")
                if act == "remove":
                    pid = str(r.get("policy_id") or "")
                    if pid:
                        client.device_assignment_remove(device_id, pid)
                        removed += 1
                elif act in ("add", "update", "set"):
                    pn = str(r.get("policy_name") or "").strip()
                    if pn:
                        client.assignment_set(
                            device_id=device_id,
                            policy_name=pn,
                            priority=int(r.get("priority") or 0),
                            mode=str(r.get("mode") or "enforce"),
                        )
                        set_count += 1

            console.print(f"Applied: set={set_count} removed={removed}")
            _pause(console)
            continue


        if action == "clone":
            if not assignments:
                console.print("Source device has no assignments to clone.")
                _pause(console)
                continue

            include_deleted = Confirm.ask(
                "Include deleted devices for destination pick?",
                default=False,
            )
            q = Prompt.ask("Destination device search (substring)", default="").strip().lower()

            dp = client.devices_list(limit=500, offset=0, include_deleted=include_deleted)
            devices = list(dp.get("items") or [])
            if q:
                devices = [
                    d
                    for d in devices
                    if q in str(d.get("device_key") or "").lower()
                    or q in str(d.get("hostname") or "").lower()
                ]

            dest_picks = [
                _Pick(label=str(d.get("device_key") or d.get("id") or ""), value=d)
                for d in devices
            ]
            dest = _pick_from_table(
                console=console,
                title="Pick destination device",
                items=dest_picks,
                columns=["device_key", "hostname", "status", "id"],
                row_fn=lambda it: [
                    str((it.value or {}).get("device_key") or ""),
                    str((it.value or {}).get("hostname") or ""),
                    str((it.value or {}).get("status") or ""),
                    str((it.value or {}).get("id") or ""),
                ],
            )
            if not dest:
                continue

            dst_device = dest.value or {}
            dst_id = str(dst_device.get("id") or "")
            if not dst_id:
                console.print("Destination device missing id")
                _pause(console)
                continue
            if dst_id == device_id:
                console.print("Destination must be different from source.")
                _pause(console)
                continue

            clear_first = Confirm.ask("Clear destination assignments first?", default=True)

            # Build a minimal plan so we only call set for assignments that would change.
            dst_payload = client.device_assignments_list(dst_id)
            dst_current = list(dst_payload.get("assignments") or [])
            dst_by_id = {str(a.get("policy_id") or "").strip().lower(): a for a in dst_current}

            desired: list[dict[str, Any]] = []
            for a in assignments:
                pn = str(a.get("policy_name") or "").strip()
                pid = str(a.get("policy_id") or "").strip()
                if not pn:
                    continue
                m = str(a.get("mode") or "enforce").strip().lower()
                if m not in ("enforce", "audit"):
                    m = "enforce"
                pri = int(a.get("priority") or 9999)
                desired.append({"policy_id": pid, "policy_name": pn, "priority": pri, "mode": m})

            rows: list[dict[str, Any]] = []
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
                for d in desired:
                    pid_k = str(d.get("policy_id") or "").strip().lower()
                    cur = dst_by_id.get(pid_k) if pid_k else None
                    if cur:
                        cp = cur.get("priority")
                        cm = str(cur.get("mode") or "").strip().lower()
                        if int(cp or 0) == int(d.get("priority") or 0) and cm == str(d.get("mode") or ""):
                            action_ = "keep"
                        else:
                            action_ = "update"
                        rows.append(
                            {
                                "action": action_,
                                "policy_id": d.get("policy_id"),
                                "policy_name": d.get("policy_name"),
                                "priority": d.get("priority"),
                                "mode": d.get("mode"),
                                "current_priority": cur.get("priority"),
                                "current_mode": cur.get("mode"),
                            }
                        )
                    else:
                        rows.append(
                            {
                                "action": "add",
                                "policy_id": d.get("policy_id"),
                                "policy_name": d.get("policy_name"),
                                "priority": d.get("priority"),
                                "mode": d.get("mode"),
                                "current_priority": None,
                                "current_mode": None,
                            }
                        )

            console.print("[bold]Clone plan[/bold]")
            console.print(f"from {device_key} ({device_id})")
            console.print(f"to   {dst_device.get('device_key')} ({dst_id})")
            if clear_first:
                console.print(
                    f"[yellow]Will clear[/yellow] {len(dst_current)} existing assignments, then set {len(desired)} from source."
                )
            render_assignments_plan(console, rows, device_id=dst_id)

            if not Confirm.ask("Proceed?", default=False):
                continue

            if clear_first:
                client.device_assignments_clear(dst_id)

            set_count = 0
            for r in rows:
                act = str(r.get("action") or "")
                if act in ("add", "update", "set"):
                    pn = str(r.get("policy_name") or "").strip()
                    if not pn:
                        continue
                    client.assignment_set(
                        device_id=dst_id,
                        policy_name=pn,
                        priority=int(r.get("priority") or 0),
                        mode=str(r.get("mode") or "enforce"),
                    )
                    set_count += 1

            console.print(f"Cloned: set={set_count} (kept={sum(1 for r in rows if (r.get('action')=='keep'))})")
            _pause(console)
            continue


        if action == "set":
            q = Prompt.ask("Policy search (substring)", default="").strip()
            pols = client.policies_list(limit=200, offset=0, include_inactive=True, q=q or None)
            items: list[dict[str, Any]] = list(pols.get("items") or [])
            if not items:
                console.print("No policies matched.")
                _pause(console)
                continue

            picks = [_Pick(label=str(p.get("name") or p.get("id") or ""), value=p) for p in items]
            picked = _pick_from_table(
                console=console,
                title="Pick policy",
                items=picks,
                columns=["name", "active", "id"],
                row_fn=lambda it: [
                    str((it.value or {}).get("name") or ""),
                    "yes" if (it.value or {}).get("is_active") else "no",
                    str((it.value or {}).get("id") or ""),
                ],
            )
            if not picked:
                continue

            policy_name = str((picked.value or {}).get("name") or "").strip()
            if not policy_name:
                console.print("Selected policy missing name")
                _pause(console)
                continue

            mode = Prompt.ask("Mode", choices=["enforce", "audit"], default="enforce").strip()
            priority = IntPrompt.ask("Priority (lower wins)", default=9999)

            resp = client.assignment_set(
                device_id=device_id,
                policy_name=policy_name,
                priority=int(priority),
                mode=mode,
            )
            console.print_json(data=resp)
            _pause(console)


def _policies_menu(*, client: BaselinerAdminClient, console: Console) -> None:
    include_inactive = Confirm.ask("Include inactive policies?", default=True)
    q = Prompt.ask("Search (substring) - blank for all", default="").strip()

    payload = client.policies_list(
        limit=200,
        offset=0,
        include_inactive=include_inactive,
        q=q or None,
    )
    items: list[dict[str, Any]] = list(payload.get("items") or [])

    console.clear()
    render_policies_list(console, {"items": items, "total": len(items), "limit": 200, "offset": 0})

    picks = [_Pick(label=str(p.get("name") or p.get("id") or ""), value=p) for p in items]
    picked = _pick_from_table(
        console=console,
        title="Pick policy",
        items=picks,
        columns=["name", "active", "id"],
        row_fn=lambda it: [
            str((it.value or {}).get("name") or ""),
            "yes" if (it.value or {}).get("is_active") else "no",
            str((it.value or {}).get("id") or ""),
        ],
    )
    if not picked:
        return

    policy_id = str((picked.value or {}).get("id") or "")
    if not policy_id:
        console.print("Selected policy missing id")
        _pause(console)
        return

    while True:
        console.clear()
        detail = client.policies_show(policy_id)
        render_policy_detail(console, detail, raw=False)
        action = Prompt.ask(
            "Action",
            choices=["raw", "back"],
            default="back",
        )
        if action == "back":
            return
        if action == "raw":
            console.clear()
            render_policy_detail(console, detail, raw=True)
            _pause(console)


def _runs_menu(*, client: BaselinerAdminClient, console: Console) -> None:
    device_ref = Prompt.ask("Device filter (uuid) - blank for all", default="").strip()
    device_id: str | None = None
    if device_ref:
        u = try_parse_uuid(device_ref)
        if not u:
            console.print("Device filter must be a UUID")
            _pause(console)
            return
        device_id = str(u)

    payload = client.runs_list(limit=100, offset=0, device_id=device_id)
    runs: list[dict[str, Any]] = list(payload.get("items") or [])

    console.clear()
    render_runs_list(console, {"items": runs, "total": len(runs), "limit": 100, "offset": 0})

    picks = [_Pick(label=str(r.get("id") or ""), value=r) for r in runs]
    picked = _pick_from_table(
        console=console,
        title="Pick run",
        items=picks,
        columns=["status", "device_id", "started", "id"],
        row_fn=lambda it: [
            str((it.value or {}).get("status") or ""),
            str((it.value or {}).get("device_id") or ""),
            str((it.value or {}).get("started_at") or ""),
            str((it.value or {}).get("id") or ""),
        ],
    )
    if not picked:
        return

    run_id = str((picked.value or {}).get("id") or "")
    if not run_id:
        console.print("Selected run missing id")
        _pause(console)
        return

    full = Confirm.ask("Show full run (items + logs)?", default=True)
    logs_limit = IntPrompt.ask("Logs limit", default=50)
    detail = client.runs_show(run_id)
    console.clear()
    render_run_detail(console, detail, full=bool(full), logs_limit=int(logs_limit))
    _pause(console)


def _audit_menu(*, client: BaselinerAdminClient, console: Console) -> None:
    limit = IntPrompt.ask("Limit", default=50)
    action = Prompt.ask("Filter action (exact) - blank for all", default="").strip() or None
    target_type = Prompt.ask("Filter target_type - blank for all", default="").strip() or None

    payload = client.audit_list(limit=int(limit), action=action, target_type=target_type)
    items: list[dict[str, Any]] = list(payload.get("items") or [])

    table = Table(title="Audit")
    table.add_column("ts")
    table.add_column("actor")
    table.add_column("action")
    table.add_column("target")
    table.add_column("corr")

    for ev in items:
        actor = f"{ev.get('actor_type')}/{ev.get('actor_id')}".strip("/")
        target = f"{ev.get('target_type')}:{ev.get('target_id')}".strip(":")
        table.add_row(
            str(ev.get("ts") or ""),
            actor,
            str(ev.get("action") or ""),
            target,
            str(ev.get("correlation_id") or ""),
        )

    console.clear()
    console.print(table)
    if payload.get("next_cursor"):
        console.print(f"next_cursor={payload.get('next_cursor')}")
    _pause(console)


def die_tui_not_supported(console: Console) -> None:
    console.print("[red]Interactive TUI requires a TTY.[/red]")
    console.print("Try running from a real terminal (not redirected output).")
    raise SystemExit(2)
