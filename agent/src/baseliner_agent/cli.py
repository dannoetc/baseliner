import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agent import enroll_device, heartbeat_once, run_once
from .agent_health import build_health, write_health
from .config import default_config_path, load_config, merge_tags
from .state import AgentState, default_state_dir
from .support_bundle import create_support_bundle, default_bundle_path
from .winget import configure_winget


def main(argv: list[str] | None = None) -> int:
    # Pre-parse only to capture --config early
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", default=os.environ.get("BASELINER_CONFIG", ""))
    pre_args, _ = pre.parse_known_args(argv)

    cfg_path = Path(pre_args.config).expanduser() if pre_args.config else default_config_path()
    cfg = load_config(cfg_path)

    # Apply winget config ASAP so agent run uses SYSTEM-safe winget path if configured.
    configure_winget(getattr(cfg, "winget_path", None))

    parser = argparse.ArgumentParser(
        prog="baseliner-agent", description="Baseliner Windows agent (MVP)"
    )
    parser.add_argument(
        "--config",
        default=str(cfg_path),
        help="Config file path (default: %ProgramData%\\Baseliner\\agent.toml)",
    )
    parser.add_argument(
        "--state-dir",
        default=str(cfg.state_dir or default_state_dir()),
        help="State directory (default: %ProgramData%\\Baseliner)",
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    # CONFIG
    p_cfg = sub.add_parser("config", help="Configuration utilities (show resolved config)")
    cfg_sub = p_cfg.add_subparsers(dest="config_cmd", required=True)
    cfg_sub.add_parser("show", help="Print resolved configuration (secrets redacted)")

    # HEALTH
    p_h = sub.add_parser("health", help="Agent health utilities (health.json)")
    h_sub = p_h.add_subparsers(dest="health_cmd", required=True)
    h_sub.add_parser("show", help="Print current agent health JSON (computed locally)")
    h_write = h_sub.add_parser("write", help="Write health.json to state dir (atomic)")
    h_write.add_argument(
        "--path", default="", help="Optional output path (default: <state-dir>\\health.json)"
    )

    # ENROLL
    p_enroll = sub.add_parser(
        "enroll", help="Enroll this device using a one-time enrollment token"
    )
    p_enroll.add_argument(
        "--server",
        required=(cfg.server_url is None),
        default=cfg.server_url,
        help="Baseliner server base URL (e.g. http://localhost:8000)",
    )
    p_enroll.add_argument(
        "--enroll-token",
        required=(cfg.enroll_token is None),
        default=cfg.enroll_token,
        help="One-time enroll token minted by admin endpoint",
    )
    p_enroll.add_argument(
        "--device-key", required=True, help="Stable unique device key (e.g. hostname or asset tag)"
    )
    p_enroll.add_argument(
        "--tags",
        default="",
        help="Comma-separated tags as key=value pairs (e.g. env=dev,site=denver)",
    )

    # RUN-ONCE
    p_run = sub.add_parser("run-once", help="Fetch effective policy and execute it once")
    p_run.add_argument(
        "--server",
        required=(cfg.server_url is None),
        default=cfg.server_url,
        help="Baseliner server base URL (e.g. http://localhost:8000)",
    )
    p_run.add_argument(
        "--force", action="store_true", help="Run even if effectivePolicyHash unchanged"
    )

    # RUN-LOOP
    p_loop = sub.add_parser(
        "run-loop", help="Run continuously: apply on an interval (optional heartbeat)"
    )
    p_loop.add_argument(
        "--server",
        required=(cfg.server_url is None),
        default=cfg.server_url,
        help="Baseliner server base URL (e.g. http://localhost:8000)",
    )
    p_loop.add_argument(
        "--interval",
        type=int,
        default=cfg.poll_interval_seconds,
        help="Apply interval in seconds (default: %(default)s)",
    )
    p_loop.add_argument(
        "--heartbeat-interval",
        type=int,
        default=cfg.heartbeat_interval_seconds,
        help="If set > 0, post heartbeat runs on this interval in seconds (default: %(default)s)",
    )
    p_loop.add_argument(
        "--jitter",
        type=int,
        default=cfg.jitter_seconds,
        help="Random extra sleep added each cycle in seconds (default: %(default)s)",
    )
    p_loop.add_argument(
        "--force", action="store_true", help="Run even if effectivePolicyHash unchanged"
    )

    # SUPPORT-BUNDLE
    p_sb = sub.add_parser(
        "support-bundle",
        help="Create a zip support bundle for troubleshooting (logs/state/redacted config)",
    )
    p_sb.add_argument(
        "--out",
        default="",
        help="Output zip path (default: <state-dir>\\support-bundle-<host>-<timestamp>.zip)",
    )
    p_sb.add_argument(
        "--since-hours",
        type=int,
        default=24,
        help=(
            "Include run logs / queued reports modified within the last N hours (default: %(default)s)"
        ),
    )
    p_sb.add_argument(
        "--max-run-logs",
        type=int,
        default=50,
        help="Max number of per-run JSONL logs to include (default: %(default)s)",
    )
    p_sb.add_argument(
        "--no-queue",
        action="store_true",
        help="Exclude queued reports from the bundle",
    )

    args = parser.parse_args(argv)
    state_dir = os.path.abspath(args.state_dir)

    try:
        if args.cmd == "config" and args.config_cmd == "show":
            cfg2 = load_config(Path(args.config).expanduser())
            if not cfg2.state_dir:
                cfg2.state_dir = str(default_state_dir())
            configure_winget(getattr(cfg2, "winget_path", None))
            print(json.dumps(_redact_config_for_print(cfg2), indent=2, sort_keys=True))
            return 0

        if args.cmd == "health":
            st = AgentState.load(state_dir)
            if args.health_cmd == "show":
                print(json.dumps(build_health(state_dir, state=st), indent=2, sort_keys=True))
                return 0
            if args.health_cmd == "write":
                out = args.path.strip() or None
                path = write_health(state_dir, state=st, path=out)
                print(str(path))
                return 0

        if args.cmd == "enroll":
            tags_cli = _parse_tags(args.tags)
            tags = merge_tags(cfg.tags, tags_cli)
            enroll_device(
                server=args.server,
                enroll_token=args.enroll_token,
                device_key=args.device_key,
                tags=tags,
                state_dir=state_dir,
            )
            return 0

        if args.cmd == "run-once":
            run_once(server=args.server, state_dir=state_dir, force=bool(args.force))
            return 0

        if args.cmd == "run-loop":
            _run_loop(
                server=args.server,
                state_dir=state_dir,
                apply_interval=int(args.interval),
                heartbeat_interval=int(args.heartbeat_interval),
                jitter=int(args.jitter),
                force=bool(args.force),
            )
            return 0

        if args.cmd == "support-bundle":
            cfg2 = load_config(Path(args.config).expanduser())
            if not cfg2.state_dir:
                cfg2.state_dir = str(default_state_dir())

            out_path = args.out.strip() or ""
            out = Path(out_path).expanduser() if out_path else default_bundle_path(state_dir)

            bundle = create_support_bundle(
                state_dir=state_dir,
                out_path=str(out),
                since_hours=int(args.since_hours),
                max_run_logs=int(args.max_run_logs),
                include_queue=(not bool(args.no_queue)),
                include_config_redacted=_redact_config_for_print(cfg2),
                winget_path_hint=getattr(cfg2, "winget_path", None),
            )
            print(str(bundle))
            return 0

        parser.print_help()
        return 2
    except KeyboardInterrupt:
        print("Cancelled.")
        return 130
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1


def _run_loop(
    *,
    server: str,
    state_dir: str,
    apply_interval: int,
    heartbeat_interval: int,
    jitter: int,
    force: bool,
) -> None:
    apply_interval = max(1, int(apply_interval))
    heartbeat_interval = max(0, int(heartbeat_interval))
    jitter = max(0, int(jitter))

    print(
        f"[baseliner-agent] run-loop: apply_interval={apply_interval}s "
        f"heartbeat_interval={heartbeat_interval}s jitter={jitter}s server={server}"
    )

    # One-time startup jitter (helps avoid thundering herd at boot)
    if jitter > 0:
        startup = random.randint(0, jitter)
        if startup > 0:
            print(f"[baseliner-agent] run-loop: startup_jitter_sleep={startup}s")
            time.sleep(startup)


    next_apply = time.time()
    next_hb: float | None = time.time() if heartbeat_interval > 0 else None

    while True:
        now = time.time()

        # Heartbeat: keeps server last_seen fresh and can trigger an immediate apply.
        if next_hb is not None and now >= next_hb:
            res = heartbeat_once(server=server, state_dir=state_dir, log_console=True)
            if bool(res.get("policy_changed")):
                next_apply = min(next_apply, time.time())
            next_hb = time.time() + _sleep_with_jitter(heartbeat_interval, jitter)

        now = time.time()

        if now >= next_apply:
            run_once(server=server, state_dir=state_dir, force=force)
            next_apply = time.time() + _sleep_with_jitter(apply_interval, jitter)

        # Update scheduler metadata for local visibility (health.json, support bundles, etc.)
        st = AgentState.load(state_dir)
        st.apply_interval_seconds = apply_interval
        st.heartbeat_interval_seconds = heartbeat_interval
        st.next_apply_due_at = datetime.fromtimestamp(next_apply, tz=timezone.utc).isoformat()
        if next_hb is not None:
            st.next_heartbeat_due_at = datetime.fromtimestamp(next_hb, tz=timezone.utc).isoformat()
        else:
            st.next_heartbeat_due_at = None

        # Persist state first (so health references stable values), then write health.json.
        st.save(state_dir)
        try:
            write_health(state_dir, state=st)
        except Exception:
            pass

        # Sleep until the next scheduled operation.
        next_due = next_apply if next_hb is None else min(next_apply, next_hb)
        sleep_s = max(1, int(next_due - time.time()))
        time.sleep(sleep_s)


def _parse_tags(s: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if not s.strip():
        return out
    parts = [p.strip() for p in s.split(",") if p.strip()]
    for p in parts:
        if "=" not in p:
            out[p] = True
        else:
            k, v = p.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _redact_config_for_print(cfg: Any) -> dict[str, Any]:
    return {
        "server_url": cfg.server_url,
        "enroll_token": "***redacted***" if getattr(cfg, "enroll_token", None) else None,
        "poll_interval_seconds": cfg.poll_interval_seconds,
        "heartbeat_interval_seconds": getattr(cfg, "heartbeat_interval_seconds", 0),
        "jitter_seconds": getattr(cfg, "jitter_seconds", 0),
        "log_level": cfg.log_level,
        "tags": cfg.tags or {},
        "state_dir": cfg.state_dir,
        "winget_path": getattr(cfg, "winget_path", None),
    }


def _sleep_with_jitter(base_seconds: int, jitter_seconds: int) -> int:
    base_seconds = max(1, int(base_seconds))
    jitter_seconds = max(0, int(jitter_seconds))
    if jitter_seconds <= 0:
        return base_seconds
    return base_seconds + random.randint(0, jitter_seconds)
