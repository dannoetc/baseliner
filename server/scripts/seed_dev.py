#!/usr/bin/env python3
"""
Baseliner server dev seeding utility (Issue #27).

This script uses the server's Admin API to:
- create an enrollment token (optional)
- upsert a policy from a JSON file
- assign that policy to a device (by device_key) (optional)

It is intentionally "ops-friendly": it prints JSON you can paste into issues.

Usage (from repo root):

  # One-shot seed (token + policy + assignment)
  python server/scripts/seed_dev.py seed --device-key DESKTOP-FTVVO4A --create-token

  # Only create token
  python server/scripts/seed_dev.py create-enroll-token --expires-hours 24 --note "dev token"

  # Upsert a policy from a JSON file
  python server/scripts/seed_dev.py upsert-policy --file policies/baseliner-windows-core.json

  # Assign a policy to a device (by device_key)
  python server/scripts/seed_dev.py assign-policy --device-key DESKTOP-FTVVO4A --policy-name baseliner-windows-core


# Restore a soft-deleted device (mints a new device token)
python server/scripts/seed_dev.py restore-device --device-id <device_uuid>

# Revoke/rotate a device token (mints a new device token)
python server/scripts/seed_dev.py revoke-device-token --device-id <device_uuid>

# List newest admin audit events
python server/scripts/seed_dev.py audit --limit 20

Notes:
- Global args like --server/--admin-key/--timeout are accepted either BEFORE or AFTER the subcommand.
  (We normalize argv to make this forgiving.)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import httpx


DEFAULT_SERVER = "http://localhost:8000"
DEFAULT_POLICY_FILE = "policies/baseliner-windows-core.json"
DEFAULT_POLICY_NAME = "baseliner-windows-core"
DEFAULT_PRIORITY = 9999

REPO_ROOT = Path(__file__).resolve().parents[2]


def _utc_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _load_json(path: Path) -> dict[str, Any]:
    candidates = [path]
    if not path.is_absolute():
        candidates.append(REPO_ROOT / path)

    chosen: Path | None = None
    for p in candidates:
        if p.exists():
            chosen = p
            break

    if chosen is None:
        raise FileNotFoundError(f"File not found: {path} (also tried {REPO_ROOT / path})")

    # utf-8-sig handles Windows BOM if present
    text = chosen.read_text(encoding="utf-8-sig")
    return json.loads(text)


@dataclass
class Ctx:
    server: str
    admin_key: str
    timeout_s: float = 20.0


def _client(ctx: Ctx) -> httpx.Client:
    headers = {"X-Admin-Key": ctx.admin_key, "Accept": "application/json"}
    return httpx.Client(base_url=ctx.server.rstrip("/"), headers=headers, timeout=ctx.timeout_s)


def _raise_for_status(resp: httpx.Response) -> None:
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError:
        try:
            payload = resp.json()
        except Exception:
            payload = resp.text
        raise RuntimeError(f"HTTP {resp.status_code} {resp.request.method} {resp.request.url}\n{payload}") from None


def create_enroll_token(
    ctx: Ctx,
    *,
    expires_at: str | None,
    expires_hours: int | None,
    note: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if note:
        payload["note"] = note

    if expires_at:
        payload["expires_at"] = expires_at
    elif expires_hours is not None:
        dt = datetime.now(timezone.utc) + timedelta(hours=int(expires_hours))
        payload["expires_at"] = _utc_iso(dt)

    with _client(ctx) as c:
        r = c.post("/api/v1/admin/enroll-tokens", json=payload)
        _raise_for_status(r)
        return r.json()


def upsert_policy(ctx: Ctx, *, policy_file: Path) -> dict[str, Any]:
    payload = _load_json(policy_file)

    required = ["name", "schema_version", "is_active", "document"]
    missing = [k for k in required if k not in payload]
    if missing:
        raise RuntimeError(f"Policy file missing keys: {missing}. Expected {required} (+ optional description).")

    with _client(ctx) as c:
        r = c.post("/api/v1/admin/policies", json=payload)
        _raise_for_status(r)
        return r.json()


def _find_device_id_by_key(ctx: Ctx, *, device_key: str, limit: int = 500) -> str:
    with _client(ctx) as c:
        r = c.get("/api/v1/admin/devices", params={"limit": limit, "offset": 0, "include_health": "false"})
        _raise_for_status(r)
        data = r.json()

    items = data.get("items") or []
    for d in items:
        if str(d.get("device_key") or "") == device_key:
            return str(d.get("id"))

    raise RuntimeError(f"Device not found for device_key={device_key!r}. (Is it enrolled yet?)")


def assign_policy(
    ctx: Ctx,
    *,
    device_key: str,
    policy_name: str,
    mode: str,
    priority: int,
) -> dict[str, Any]:
    device_id = _find_device_id_by_key(ctx, device_key=device_key)
    payload = {
        "device_id": device_id,
        "policy_name": policy_name,
        "mode": mode,
        "priority": int(priority),
    }
    with _client(ctx) as c:
        r = c.post("/api/v1/admin/assign-policy", json=payload)
        _raise_for_status(r)
        return {"ok": True, "device_id": device_id, "policy_name": policy_name, "mode": mode, "priority": int(priority)}



def restore_device(ctx: Ctx, *, device_id: str) -> dict[str, Any]:
    """Restore (reactivate) a soft-deleted device and mint a new device token."""
    with _client(ctx) as c:
        r = c.post(f"/api/v1/admin/devices/{device_id}/restore")
        _raise_for_status(r)
        return r.json()


def revoke_device_token(ctx: Ctx, *, device_id: str) -> dict[str, Any]:
    """Revoke the current device token and mint a new one."""
    with _client(ctx) as c:
        r = c.post(f"/api/v1/admin/devices/{device_id}/revoke-token")
        _raise_for_status(r)
        return r.json()


def list_audit_events(
    ctx: Ctx,
    *,
    limit: int = 20,
    cursor: str | None = None,
    action: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
) -> dict[str, Any]:
    """List admin audit events (newest first)."""
    params: dict[str, Any] = {"limit": int(limit)}
    if cursor:
        params["cursor"] = cursor
    if action:
        params["action"] = action
    if target_type:
        params["target_type"] = target_type
    if target_id:
        params["target_id"] = target_id

    with _client(ctx) as c:
        r = c.get("/api/v1/admin/audit", params=params)
        _raise_for_status(r)
        return r.json()

def _print_json(obj: Any) -> None:
    print(json.dumps(obj, indent=2, sort_keys=True))


def cmd_seed(args: argparse.Namespace) -> int:
    ctx = Ctx(server=args.server, admin_key=args.admin_key, timeout_s=float(args.timeout))
    out: dict[str, Any] = {"server": ctx.server}

    if args.create_token:
        tok = create_enroll_token(ctx, expires_at=args.expires_at or None, expires_hours=args.expires_hours, note=args.note)
        out["enroll_token"] = tok

    pol = upsert_policy(ctx, policy_file=Path(args.policy_file))
    out["policy"] = pol

    if args.device_key:
        asg = assign_policy(ctx, device_key=args.device_key, policy_name=args.policy_name, mode=args.mode, priority=int(args.priority))
        out["assignment"] = asg
    else:
        out["assignment"] = None
        out["next"] = "Enroll a device, then re-run with --device-key to assign the policy."

    _print_json(out)
    return 0


def cmd_create_token(args: argparse.Namespace) -> int:
    ctx = Ctx(server=args.server, admin_key=args.admin_key, timeout_s=float(args.timeout))
    tok = create_enroll_token(ctx, expires_at=args.expires_at or None, expires_hours=args.expires_hours, note=args.note)
    _print_json(tok)
    return 0


def cmd_upsert_policy(args: argparse.Namespace) -> int:
    ctx = Ctx(server=args.server, admin_key=args.admin_key, timeout_s=float(args.timeout))
    pol = upsert_policy(ctx, policy_file=Path(args.file))
    _print_json(pol)
    return 0


def cmd_assign_policy(args: argparse.Namespace) -> int:
    ctx = Ctx(server=args.server, admin_key=args.admin_key, timeout_s=float(args.timeout))
    res = assign_policy(ctx, device_key=args.device_key, policy_name=args.policy_name, mode=args.mode, priority=int(args.priority))
    _print_json(res)
    return 0



def cmd_restore_device(args: argparse.Namespace) -> int:
    ctx = Ctx(server=args.server, admin_key=args.admin_key, timeout_s=float(args.timeout))
    res = restore_device(ctx, device_id=str(args.device_id))
    _print_json(res)
    return 0


def cmd_revoke_device_token(args: argparse.Namespace) -> int:
    ctx = Ctx(server=args.server, admin_key=args.admin_key, timeout_s=float(args.timeout))
    res = revoke_device_token(ctx, device_id=str(args.device_id))
    _print_json(res)
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    ctx = Ctx(server=args.server, admin_key=args.admin_key, timeout_s=float(args.timeout))
    res = list_audit_events(
        ctx,
        limit=int(args.limit),
        cursor=args.cursor or None,
        action=args.action or None,
        target_type=args.target_type or None,
        target_id=args.target_id or None,
    )
    _print_json(res)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="seed_dev", description="Baseliner server dev seeding utilities (Issue #27)")
    p.add_argument(
        "--server",
        default=os.environ.get("BASELINER_SERVER_URL", DEFAULT_SERVER),
        help=f"Server base URL (env: BASELINER_SERVER_URL) (default: {DEFAULT_SERVER})",
    )
    p.add_argument(
        "--admin-key",
        default=os.environ.get("BASELINER_ADMIN_KEY", ""),
        help="Admin key (env: BASELINER_ADMIN_KEY). Required.",
    )
    p.add_argument("--timeout", default="20", help="HTTP timeout seconds (default: 20)")

    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("seed", help="One-shot: optionally create token + upsert policy + optionally assign to device")
    s.add_argument("--create-token", action="store_true", help="Also create an enrollment token and print it")
    s.add_argument("--expires-at", default="", help="Enroll token expires_at ISO8601 (optional)")
    s.add_argument("--expires-hours", type=int, default=24, help="Enroll token TTL in hours if --expires-at not set (default: 24)")
    s.add_argument("--note", default="dev seed token", help="Optional note attached to the enroll token")
    s.add_argument("--policy-file", default=DEFAULT_POLICY_FILE, help=f"Policy JSON file to upsert (default: {DEFAULT_POLICY_FILE})")
    s.add_argument("--policy-name", default=DEFAULT_POLICY_NAME, help=f"Policy name to assign (default: {DEFAULT_POLICY_NAME})")
    s.add_argument("--device-key", default="", help="Device key to assign policy to (optional; requires device already enrolled)")
    s.add_argument("--mode", default="enforce", choices=["enforce", "audit"], help="Assignment mode (default: enforce)")
    s.add_argument("--priority", type=int, default=DEFAULT_PRIORITY, help=f"Assignment priority (default: {DEFAULT_PRIORITY})")
    s.set_defaults(func=cmd_seed)

    t = sub.add_parser("create-enroll-token", help="Create a one-time enrollment token")
    t.add_argument("--expires-at", default="", help="expires_at ISO8601 (optional)")
    t.add_argument("--expires-hours", type=int, default=24, help="TTL in hours if --expires-at not set (default: 24)")
    t.add_argument("--note", default="dev token", help="Optional note")
    t.set_defaults(func=cmd_create_token)

    u = sub.add_parser("upsert-policy", help="Upsert a policy from a JSON file")
    u.add_argument("--file", required=True, help="Path to policy JSON file (see ./policies/)")
    u.set_defaults(func=cmd_upsert_policy)

    a = sub.add_parser("assign-policy", help="Assign an existing policy to a device (by device_key)")
    a.add_argument("--device-key", required=True, help="Device key (must already be enrolled)")
    a.add_argument("--policy-name", required=True, help="Policy name (must exist / be active)")
    a.add_argument("--mode", default="enforce", choices=["enforce", "audit"], help="Assignment mode (default: enforce)")
    a.add_argument("--priority", type=int, default=DEFAULT_PRIORITY, help=f"Assignment priority (default: {DEFAULT_PRIORITY})")
    a.set_defaults(func=cmd_assign_policy)

    r = sub.add_parser("restore-device", help="Restore a soft-deleted device and mint a new device token")
    r.add_argument("--device-id", required=True, help="Device UUID to restore")
    r.set_defaults(func=cmd_restore_device)

    v = sub.add_parser("revoke-device-token", help="Revoke a device token and mint a new token")
    v.add_argument("--device-id", required=True, help="Device UUID to revoke/rotate token for")
    v.set_defaults(func=cmd_revoke_device_token)

    au = sub.add_parser("audit", help="List admin audit events (newest first)")
    au.add_argument("--limit", type=int, default=20, help="Max events to return (default: 20)")
    au.add_argument("--cursor", default="", help="Pagination cursor (from a previous response)")
    au.add_argument("--action", default="", help="Filter by action (e.g., device.delete)")
    au.add_argument("--target-type", default="", help="Filter by target_type (e.g., device, policy)")
    au.add_argument("--target-id", default="", help="Filter by target_id (UUID or string id)")
    au.set_defaults(func=cmd_audit)

_GLOBAL_FLAGS_WITH_VALUE = {"--server", "--admin-key", "--timeout"}


def _normalize_global_args(argv: list[str]) -> list[str]:
    """Allow global args to appear after the subcommand."""
    if not argv:
        return argv

    moved: list[str] = []
    rest: list[str] = []
    i = 0
    while i < len(argv):
        tok = argv[i]

        # Handle --flag=value forms
        if any(tok.startswith(f"{k}=") for k in _GLOBAL_FLAGS_WITH_VALUE):
            moved.append(tok)
            i += 1
            continue

        if tok in _GLOBAL_FLAGS_WITH_VALUE:
            moved.append(tok)
            if i + 1 < len(argv):
                moved.append(argv[i + 1])
                i += 2
            else:
                i += 1
            continue

        rest.append(tok)
        i += 1

    return moved + rest


def main(argv: Optional[list[str]] = None) -> int:
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    argv2 = _normalize_global_args(raw_argv)

    p = build_parser()
    args = p.parse_args(argv2)

    if not args.admin_key:
        print("ERROR: admin key missing. Set --admin-key or env BASELINER_ADMIN_KEY.", file=sys.stderr)
        return 2

    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130
    except Exception as e:
        print(str(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
