import json
import os
from dataclasses import dataclass
from pathlib import Path

from .security.dpapi import dpapi_decrypt, dpapi_encrypt


def default_state_dir() -> Path:
    program_data = os.environ.get("ProgramData") or r"C:\ProgramData"
    return Path(program_data) / "Baseliner"


@dataclass
class AgentState:
    device_id: str | None = None
    device_key: str | None = None
    last_policy_hash: str | None = None
    agent_version: str = "0.1.0-dev"

    @staticmethod
    def load(state_dir: str) -> "AgentState":
        d = Path(state_dir)
        d.mkdir(parents=True, exist_ok=True)
        path = d / "state.json"
        if not path.exists():
            return AgentState()
        data = json.loads(path.read_text(encoding="utf-8"))
        return AgentState(
            device_id=data.get("device_id"),
            device_key=data.get("device_key"),
            last_policy_hash=data.get("last_policy_hash"),
            agent_version=data.get("agent_version") or "0.1.0-dev",
        )

    def save(self, state_dir: str) -> None:
        d = Path(state_dir)
        d.mkdir(parents=True, exist_ok=True)
        path = d / "state.json"
        payload = {
            "device_id": self.device_id,
            "device_key": self.device_key,
            "last_policy_hash": self.last_policy_hash,
            "agent_version": self.agent_version,
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def save_device_token(self, state_dir: str, token: str) -> None:
        d = Path(state_dir)
        d.mkdir(parents=True, exist_ok=True)
        path = d / "device_token.dpapi"
        blob = dpapi_encrypt(token.encode("utf-8"))
        path.write_bytes(blob)

    def load_device_token(self, state_dir: str) -> str:
        d = Path(state_dir)
        path = d / "device_token.dpapi"
        if not path.exists():
            raise RuntimeError(f"Device token not found at {path}. Run: baseliner-agent enroll ...")
        blob = path.read_bytes()
        token = dpapi_decrypt(blob).decode("utf-8")
        if not token.strip():
            raise RuntimeError("Device token is empty after decrypt; re-enroll.")
        return token


def ensure_queue_dir(state_dir: str) -> Path:
    d = Path(state_dir) / "queue"
    d.mkdir(parents=True, exist_ok=True)
    return d
