import time
from typing import Any

import requests


class ApiClient:
    def __init__(self, base_url: str, device_token: str | None = None, timeout_s: int = 30):
        self.base_url = base_url.rstrip("/")
        self.device_token = device_token
        self.timeout_s = timeout_s

    def _headers(self) -> dict[str, str]:
        h = {"Accept": "application/json"}
        if self.device_token:
            h["Authorization"] = f"Bearer {self.device_token}"
        return h

    def post_json(self, path: str, payload: Any, retries: int = 2) -> Any:
        url = f"{self.base_url}{path}"
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                resp = requests.post(url, json=payload, headers=self._headers(), timeout=self.timeout_s)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                last_exc = e
                if attempt < retries:
                    time.sleep(2 ** attempt)
                    continue
                raise last_exc

    def get_json(self, path: str, retries: int = 2) -> Any:
        url = f"{self.base_url}{path}"
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                resp = requests.get(url, headers=self._headers(), timeout=self.timeout_s)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                last_exc = e
                if attempt < retries:
                    time.sleep(2 ** attempt)
                    continue
                raise last_exc
