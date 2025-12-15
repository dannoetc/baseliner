from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
import os

try:
    import tomllib  # py3.11+
except Exception:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]


@dataclass
class AgentConfig:
    server_url: str | None = None
    enroll_token: str | None = None
    poll_interval_seconds: int = 900
    log_level: str = "info"
    tags: dict[str, Any] = field(default_factory=dict)
    state_dir: str | None = None
    winget_path: str | None = None


def default_config_path() -> Path:
    programdata = os.environ.get("ProgramData") or r"C:\ProgramData"
    return Path(programdata) / "Baseliner" / "agent.toml"


def _parse_tags_str(s: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    s = (s or "").strip()
    if not s:
        return out
    parts = [p.strip() for p in s.split(",") if p.strip()]
    for p in parts:
        if "=" not in p:
            out[p] = True
        else:
            k, v = p.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    if tomllib is None:
        raise RuntimeError("tomllib not available; use Python 3.11+ or switch config format.")

    # IMPORTANT: tolerate UTF-8 BOM (common when edited in some Windows tools)
    text = path.read_text(encoding="utf-8-sig")

    data = tomllib.loads(text)
    if not isinstance(data, dict):
        return {}
    return data


def load_config(
    config_path: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> AgentConfig:
    """
    Precedence (lowest -> highest):
      defaults -> config file -> environment variables

    CLI overrides should be applied by caller after this returns.
    """
    env = env or os.environ
    path = config_path or default_config_path()

    raw = _read_toml(path)

    # Support either top-level keys or a [agent] table
    agent = raw.get("agent")
    if isinstance(agent, dict):
        raw = agent

    cfg = AgentConfig()

    # File values
    if isinstance(raw.get("server_url"), str):
        cfg.server_url = raw["server_url"]
    if isinstance(raw.get("enroll_token"), str):
        cfg.enroll_token = raw["enroll_token"]
    if isinstance(raw.get("poll_interval_seconds"), int):
        cfg.poll_interval_seconds = raw["poll_interval_seconds"]
    if isinstance(raw.get("log_level"), str):
        cfg.log_level = raw["log_level"]
    if isinstance(raw.get("state_dir"), str):
        cfg.state_dir = raw["state_dir"]
    if isinstance(raw.get("winget_path"), str):
        cfg.winget_path = raw["winget_path"]

    tags_val = raw.get("tags")
    if isinstance(tags_val, dict):
        cfg.tags = dict(tags_val)

    # Env overrides (tolerant; ignore bad values rather than crash)
    if env.get("BASELINER_SERVER_URL"):
        cfg.server_url = env["BASELINER_SERVER_URL"].strip() or cfg.server_url

    if env.get("BASELINER_ENROLL_TOKEN"):
        cfg.enroll_token = env["BASELINER_ENROLL_TOKEN"].strip() or cfg.enroll_token

    if env.get("BASELINER_POLL_INTERVAL_SECONDS"):
        try:
            cfg.poll_interval_seconds = int(env["BASELINER_POLL_INTERVAL_SECONDS"])
        except Exception:
            pass

    if env.get("BASELINER_LOG_LEVEL"):
        cfg.log_level = env["BASELINER_LOG_LEVEL"].strip() or cfg.log_level

    if env.get("BASELINER_STATE_DIR"):
        cfg.state_dir = env["BASELINER_STATE_DIR"].strip() or cfg.state_dir

    if env.get("BASELINER_TAGS"):
        env_tags = _parse_tags_str(env["BASELINER_TAGS"])
        if env_tags:
            merged = dict(cfg.tags)
            merged.update(env_tags)
            cfg.tags = merged

    if env.get("BASELINER_WINGET_PATH"):
        cfg.winget_path = env["BASELINER_WINGET_PATH"].strip() or cfg.winget_path

    return cfg


def merge_tags(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base or {})
    merged.update(override or {})
    return merged
