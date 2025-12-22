from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

import httpx


class ApiError(RuntimeError):
    def __init__(self, status_code: int, detail: Any):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail}")


@dataclass(frozen=True)
class ClientConfig:
    server: str
    admin_key: str
    timeout_s: float = 10.0


class BaselinerAdminClient:
    def __init__(self, cfg: ClientConfig):
        server = (cfg.server or "").rstrip("/")
        if not server:
            raise ValueError("server is required")
        if not cfg.admin_key:
            raise ValueError("admin_key is required")

        self.cfg = cfg
        self._client = httpx.Client(
            base_url=server,
            timeout=cfg.timeout_s,
            headers={"X-Admin-Key": cfg.admin_key},
        )

    def close(self) -> None:
        self._client.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any | None = None,
    ) -> Any:
        r = self._client.request(method, path, params=params, json=json_body)

        if r.status_code >= 400:
            detail: Any
            try:
                detail = r.json()
            except Exception:
                detail = r.text
            raise ApiError(r.status_code, detail)

        if r.status_code == 204:
            return None

        # Most endpoints return JSON.
        try:
            return r.json()
        except json.JSONDecodeError:
            return r.text

    # High-level helpers

    def list_devices(self, *, limit: int = 50, offset: int = 0, **params: Any) -> Any:
        qp: dict[str, Any] = {"limit": int(limit), "offset": int(offset)}
        qp.update({k: v for k, v in params.items() if v is not None})
        return self.request("GET", "/api/v1/admin/devices", params=qp)

    def get_device_debug(self, device_id: str) -> Any:
        return self.request("GET", f"/api/v1/admin/devices/{device_id}/debug")

    def delete_device(self, device_id: str, *, reason: str | None = None) -> Any:
        params = {"reason": reason} if reason else None
        return self.request("DELETE", f"/api/v1/admin/devices/{device_id}", params=params)

    def restore_device(self, device_id: str) -> Any:
        return self.request("POST", f"/api/v1/admin/devices/{device_id}/restore")

    def revoke_device_token(self, device_id: str) -> Any:
        return self.request("POST", f"/api/v1/admin/devices/{device_id}/revoke-token")

    def list_audit(
        self,
        *,
        limit: int = 100,
        cursor: str | None = None,
        action: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
    ) -> Any:
        qp: dict[str, Any] = {"limit": int(limit)}
        if cursor:
            qp["cursor"] = cursor
        if action:
            qp["action"] = action
        if target_type:
            qp["target_type"] = target_type
        if target_id:
            qp["target_id"] = target_id
        return self.request("GET", "/api/v1/admin/audit", params=qp)

    def list_runs(
        self,
        *,
        device_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Any:
        qp: dict[str, Any] = {"limit": int(limit), "offset": int(offset)}
        if device_id:
            qp["device_id"] = device_id
        return self.request("GET", "/api/v1/admin/runs", params=qp)

    def get_run_detail(self, run_id: str) -> Any:
        return self.request("GET", f"/api/v1/admin/runs/{run_id}")

    def upsert_policy(self, payload: dict[str, Any]) -> Any:
        return self.request("POST", "/api/v1/admin/policies", json_body=payload)

    def assign_policy(self, payload: dict[str, Any]) -> Any:
        return self.request("POST", "/api/v1/admin/assign-policy", json_body=payload)

    def list_device_assignments(self, device_id: str) -> Any:
        return self.request("GET", f"/api/v1/admin/devices/{device_id}/assignments")

    def clear_device_assignments(self, device_id: str) -> Any:
        return self.request("DELETE", f"/api/v1/admin/devices/{device_id}/assignments")
