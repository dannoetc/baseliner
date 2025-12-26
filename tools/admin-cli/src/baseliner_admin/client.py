from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

import httpx


DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


class ApiError(RuntimeError):
    def __init__(self, status_code: int, detail: Any):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail}")


@dataclass(frozen=True)
class ClientConfig:
    server: str
    admin_key: str
    tenant_id: str
    timeout_s: float = 15.0


class BaselinerAdminClient:
    def __init__(
        self,
        cfg: ClientConfig | None = None,
        *,
        # Back-compat for older call sites.
        base_url: str | None = None,
        admin_key: str | None = None,
        tenant_id: str | None = None,
        timeout_s: float = 15.0,
    ):
        if cfg is None:
            cfg = ClientConfig(
                server=str(base_url or ""),
                admin_key=str(admin_key or ""),
                tenant_id=str(tenant_id or DEFAULT_TENANT_ID),
                timeout_s=float(timeout_s),
            )

        server = (cfg.server or "").rstrip("/")
        if not server:
            raise ValueError("server is required")
        if not cfg.admin_key:
            raise ValueError("admin_key is required")
        if not cfg.tenant_id:
            raise ValueError("tenant_id is required")

        self.cfg = cfg
        self._client = httpx.Client(
            base_url=server,
            timeout=cfg.timeout_s,
            headers={
                "X-Admin-Key": cfg.admin_key,
                "X-Tenant-ID": cfg.tenant_id,
                "Accept": "application/json",
                "User-Agent": "baseliner-admin-cli",
            },
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
            try:
                detail: Any = r.json()
            except Exception:
                detail = r.text
            raise ApiError(r.status_code, detail)

        if r.status_code == 204:
            return None

        try:
            return r.json()
        except json.JSONDecodeError:
            return r.text

    @staticmethod
    def pretty_json(obj: Any) -> str:
        return json.dumps(obj, indent=2, sort_keys=True, default=str)

    
    def whoami(self) -> Any:
        return self.request("GET", "/api/v1/admin/whoami")


    # ---- Admin helpers ----

    def devices_list(
        self, *, limit: int = 50, offset: int = 0, include_deleted: bool = False
    ) -> Any:
        return self.request(
            "GET",
            "/api/v1/admin/devices",
            params={
                "limit": int(limit),
                "offset": int(offset),
                "include_deleted": str(bool(include_deleted)).lower(),
            },
        )

    def devices_debug(self, device_id: str) -> Any:
        return self.request("GET", f"/api/v1/admin/devices/{device_id}/debug")

    def devices_tokens(self, device_id: str) -> Any:
        return self.request("GET", f"/api/v1/admin/devices/{device_id}/tokens")

    def devices_delete(self, device_id: str, *, reason: str | None = None) -> Any:
        params: dict[str, Any] = {}
        if reason:
            params["reason"] = reason
        return self.request("DELETE", f"/api/v1/admin/devices/{device_id}", params=params)

    def devices_restore(self, device_id: str) -> Any:
        return self.request("POST", f"/api/v1/admin/devices/{device_id}/restore")

    def devices_revoke_token(self, device_id: str) -> Any:
        return self.request("POST", f"/api/v1/admin/devices/{device_id}/revoke-token")

    def devices_deactivate(self, device_id: str, *, reason: str | None = None) -> Any:
        payload: dict[str, Any] = {}
        if reason:
            payload["reason"] = reason
        return self.request(
            "POST",
            f"/api/v1/admin/devices/{device_id}/deactivate",
            json=payload or None,
        )

    def devices_reactivate(self, device_id: str) -> Any:
        return self.request("POST", f"/api/v1/admin/devices/{device_id}/reactivate")

    def devices_rotate_token(self, device_id: str, *, reason: str | None = None) -> Any:
        payload: dict[str, Any] = {}
        if reason:
            payload["reason"] = reason
        return self.request(
            "POST",
            f"/api/v1/admin/devices/{device_id}/rotate-token",
            json=payload or None,
        )

    def device_assignments_list(self, device_id: str) -> Any:
        return self.request("GET", f"/api/v1/admin/devices/{device_id}/assignments")

    def device_assignments_clear(self, device_id: str) -> Any:
        return self.request("DELETE", f"/api/v1/admin/devices/{device_id}/assignments")

    def device_assignment_remove(self, device_id: str, policy_id: str) -> Any:
        return self.request(
            "DELETE",
            f"/api/v1/admin/devices/{device_id}/assignments/{policy_id}",
        )

    def assignment_set(
        self,
        *,
        device_id: str,
        policy_name: str,
        priority: int,
        mode: str = "enforce",
    ) -> Any:
        payload = {
            "device_id": device_id,
            "policy_name": policy_name,
            "priority": int(priority),
            "mode": mode,
        }
        return self.request("POST", "/api/v1/admin/assign-policy", json_body=payload)

    def policies_list(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        include_inactive: bool = False,
        q: str | None = None,
    ) -> Any:
        params: dict[str, Any] = {"limit": int(limit), "offset": int(offset)}
        if include_inactive:
            params["include_inactive"] = True
        if q:
            params["q"] = q
        return self.request("GET", "/api/v1/admin/policies", params=params)

    def policies_show(self, policy_id: str) -> Any:
        return self.request("GET", f"/api/v1/admin/policies/{policy_id}")

    def policies_upsert(self, payload: Mapping[str, Any]) -> Any:
        return self.request("POST", "/api/v1/admin/policies", json_body=dict(payload))

    def runs_list(
        self, *, limit: int = 50, offset: int = 0, device_id: str | None = None
    ) -> Any:
        params: dict[str, Any] = {"limit": int(limit), "offset": int(offset)}
        if device_id:
            params["device_id"] = device_id
        return self.request("GET", "/api/v1/admin/runs", params=params)

    def runs_show(self, run_id: str) -> Any:
        return self.request("GET", f"/api/v1/admin/runs/{run_id}")

    def audit_list(
        self,
        *,
        limit: int = 100,
        cursor: str | None = None,
        action: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
    ) -> Any:
        params: dict[str, Any] = {"limit": int(limit)}
        if cursor:
            params["cursor"] = cursor
        if action:
            params["action"] = action
        if target_type:
            params["target_type"] = target_type
        if target_id:
            params["target_id"] = target_id
        return self.request("GET", "/api/v1/admin/audit", params=params)

    # ---- Tenant lifecycle (superadmin-only) ----

    def tenants_list(self) -> Any:
        return self.request("GET", "/api/v1/admin/tenants")

    def tenants_create(self, *, name: str, is_active: bool = True) -> Any:
        return self.request(
            "POST",
            "/api/v1/admin/tenants",
            json_body={"name": str(name), "is_active": bool(is_active)},
        )


def tenants_update(
    self,
    *,
    tenant_id: str,
    name: str | None = None,
    is_active: bool | None = None,
) -> Any:
    payload: dict[str, Any] = {}
    if name is not None:
        payload["name"] = str(name)
    if is_active is not None:
        payload["is_active"] = bool(is_active)
    return self.request("PATCH", f"/api/v1/admin/tenants/{tenant_id}", json_body=payload)


    def admin_keys_issue(
        self,
        *,
        tenant_id: str,
        scope: str = "tenant_admin",
        note: str | None = None,
    ) -> Any:
        payload: dict[str, Any] = {"scope": scope}
        if note:
            payload["note"] = note
        return self.request("POST", f"/api/v1/admin/tenants/{tenant_id}/admin-keys", json_body=payload)

    def admin_keys_list(self, *, tenant_id: str) -> Any:
        return self.request("GET", f"/api/v1/admin/tenants/{tenant_id}/admin-keys")

    def admin_keys_revoke(self, *, tenant_id: str, key_id: str) -> Any:
        return self.request("DELETE", f"/api/v1/admin/tenants/{tenant_id}/admin-keys/{key_id}")


    def enroll_token_create(
        self,
        *,
        ttl_seconds: int | None = None,
        expires_at: str | None = None,
        note: str | None = None,
    ) -> Any:
        payload: dict[str, Any] = {}
        if ttl_seconds is not None:
            payload["ttl_seconds"] = int(ttl_seconds)
        if expires_at:
            payload["expires_at"] = expires_at
        if note:
            payload["note"] = note
        return self.request("POST", "/api/v1/admin/enroll-tokens", json_body=payload)

    def enroll_tokens_list(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        include_used: bool = False,
        include_expired: bool = True,
    ) -> Any:
        return self.request(
            "GET",
            "/api/v1/admin/enroll-tokens",
            params={
                "limit": int(limit),
                "offset": int(offset),
                "include_used": str(bool(include_used)).lower(),
                "include_expired": str(bool(include_expired)).lower(),
            },
        )

    def enroll_token_revoke(self, token_id: str, *, reason: str | None = None) -> Any:
        payload: dict[str, Any] = {}
        if reason:
            payload["reason"] = reason
        return self.request(
            "POST",
            f"/api/v1/admin/enroll-tokens/{token_id}/revoke",
            json_body=payload,
        )
