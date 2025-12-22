from __future__ import annotations

import json
from typing import Any

from rich.console import Console
from rich.table import Table


def print_json(console: Console, obj: Any) -> None:
    console.print_json(json.dumps(obj, default=str))


def devices_table(items: list[dict[str, Any]]) -> Table:
    t = Table(title="Devices", show_lines=False)
    t.add_column("id", overflow="fold")
    t.add_column("device_key")
    t.add_column("status")
    t.add_column("hostname")
    t.add_column("os")
    t.add_column("agent")
    t.add_column("last_seen", overflow="fold")

    for d in items:
        t.add_row(
            str(d.get("id") or ""),
            str(d.get("device_key") or ""),
            str(d.get("status") or ""),
            str(d.get("hostname") or ""),
            str(d.get("os") or ""),
            str(d.get("agent_version") or ""),
            str(d.get("last_seen_at") or ""),
        )

    return t


def audit_table(items: list[dict[str, Any]]) -> Table:
    t = Table(title="Audit", show_lines=False)
    t.add_column("ts", overflow="fold")
    t.add_column("actor")
    t.add_column("action")
    t.add_column("target")
    t.add_column("correlation_id", overflow="fold")

    for e in items:
        actor = f"{e.get('actor_type')}/{e.get('actor_id')}".strip("/")
        target = f"{e.get('target_type')}:{e.get('target_id')}".strip(":")
        t.add_row(
            str(e.get("ts") or ""),
            actor,
            str(e.get("action") or ""),
            target,
            str(e.get("correlation_id") or ""),
        )

    return t


def runs_table(items: list[dict[str, Any]]) -> Table:
    t = Table(title="Runs", show_lines=False)
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

    return t
