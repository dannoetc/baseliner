from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path

from .security.dpapi import protect_bytes, unprotect_bytes


def default_state_dir() -> Path:
    programdata = os.environ.get("ProgramData") or r"C:\ProgramData"
    return Path(programdata) / "Baseliner"


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


@dataclass
class AgentState:
    device_id: str | None = None
    device_key: str | None = None
    last_policy_hash: str | None = None
    agent_version: str = "0.1.0-dev"

    @staticmethod
    def load(state_dir: str | Path) -> "AgentState":
        sd = Path(state_dir)
        path = sd / "state.json"
        if not path.exists():
            return AgentState()
        data = json.loads(path.read_text(encoding="utf-8-sig") or "{}")
        st = AgentState()
        st.device_id = data.get("device_id")
        st.device_key = data.get("device_key")
        st.last_policy_hash = data.get("last_policy_hash")
        st.agent_version = data.get("agent_version") or st.agent_version
        return st

    def save(self, state_dir: str | Path) -> None:
        sd = Path(state_dir)
        _ensure_dir(sd)
        path = sd / "state.json"
        payload = asdict(self)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8-sig")

    @staticmethod
    def _token_path(state_dir: str | Path) -> Path:
        return Path(state_dir) / "device_token.dpapi"

    def save_device_token(self, state_dir: str | Path, device_token: str) -> None:
        """
        Persist device token protected via DPAPI (LocalMachine scope),
        then base64-encode it to an ASCII file.
        """
        sd = Path(state_dir)
        _ensure_dir(sd)

        token_bytes = (device_token or "").encode("utf-8")
        protected = protect_bytes(token_bytes, local_machine=True)
        b64 = base64.b64encode(protected).decode("ascii")

        path = self._token_path(sd)
        path.write_text(b64, encoding="ascii")

    def load_device_token(self, state_dir: str | Path) -> str:
        """
        Load DPAPI-protected token from disk and return as UTF-8 string.
        """
        path = self._token_path(state_dir)
        if not path.exists():
            raise RuntimeError(
                f"device is not enrolled (missing {path}). run: baseliner_agent enroll ..."
            )

        raw = path.read_text(encoding="ascii").strip()

        # Accept either base64 (preferred) or legacy raw bytes file.
        protected: bytes
        try:
            protected = base64.b64decode(raw, validate=True)
        except Exception:
            protected = path.read_bytes()

        plain = unprotect_bytes(protected)
        return plain.decode("utf-8", errors="strict")

def ensure_queue_dir(state_dir: str | Path) -> Path:
    """
    Ensure the on-disk queue directory exists for offline report spooling.

    reporting.py expects this helper.
    """
    sd = Path(state_dir)
    _ensure_dir(sd)

    # Backwards/forwards-friendly: if an older queue dir exists, keep using it.
    for name in ("queue", "queued_reports", "report_queue"):
        p = sd / name
        if p.exists() and p.is_dir():
            return p

    q = sd / "queue"
    _ensure_dir(q)
    return q
