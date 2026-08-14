"""Authenticated HTTP client for the D1-backed Cloudflare Worker API."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

import requests


class D1Error(RuntimeError):
    """Raised when the remote D1 data service rejects or cannot serve a request."""


class D1Client:
    def __init__(self, base_url: Optional[str] = None, token: Optional[str] = None):
        self.base_url = (base_url or os.environ.get("D1_API_URL", "")).rstrip("/")
        self._token = token

    def _load_token(self) -> str:
        if self._token:
            return self._token
        value = os.environ.get("D1_API_TOKEN", "").strip()
        if value:
            return value
        token_file = Path(os.environ.get("D1_API_TOKEN_FILE", "/run/secrets/d1_api_token"))
        if not token_file.exists():
            local_file = Path(__file__).resolve().parent.parent / ".d1_api_token"
            token_file = local_file if local_file.exists() else token_file
        try:
            return token_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise D1Error("D1_API_TOKEN 未配置，且服务令牌文件不可读") from exc

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        allow_404: bool = False,
    ) -> Optional[Dict[str, Any]]:
        if not self.base_url:
            raise D1Error("D1_API_URL 未配置")
        try:
            resp = requests.request(
                method,
                f"{self.base_url}{path}",
                params=params,
                json=json,
                headers={"Authorization": f"Bearer {self._load_token()}"},
                timeout=(5, 20),
            )
        except requests.RequestException as exc:
            raise D1Error(f"D1 数据服务不可用：{exc}") from exc
        if allow_404 and resp.status_code == 404:
            return None
        try:
            payload = resp.json()
        except ValueError as exc:
            raise D1Error(f"D1 数据服务返回非 JSON（HTTP {resp.status_code}）") from exc
        if not resp.ok or not payload.get("ok"):
            raise D1Error(payload.get("error") or f"D1 请求失败（HTTP {resp.status_code}）")
        return payload

    def get(self, path: str, **kwargs: Any) -> Optional[Dict[str, Any]]:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return self.request("POST", path, json=data) or {}

    def patch(self, path: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return self.request("PATCH", path, json=data) or {}

    def delete(self, path: str) -> Dict[str, Any]:
        return self.request("DELETE", path) or {}


client = D1Client()
