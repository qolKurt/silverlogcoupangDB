"""HTTP client for the Silverlog catalogue API."""

from __future__ import annotations

import os
from typing import Any

import requests


class SilverlogError(RuntimeError):
    """Raised when the Silverlog API cannot complete an operation."""


class SilverlogClient:
    def __init__(self, *, base_url: str | None = None, username: str | None = None,
                 password: str | None = None, timeout: float = 15) -> None:
        self.base_url = (base_url or os.getenv("SILVERLOG_ADMIN_URL") or "https://silverlog-admin.vercel.app").rstrip("/")
        self.username = username or os.getenv("SILVERLOG_ADMIN_USERNAME") or "admin"
        self.password = password or os.getenv("SILVERLOG_ADMIN_PASSWORD")
        self.timeout = timeout
        self.session = requests.Session()

    def login(self) -> None:
        if not self.password:
            raise SilverlogError("SILVERLOG_ADMIN_PASSWORD 환경 변수가 설정되지 않았습니다.")
        try:
            response = self.session.post(
                f"{self.base_url}/api/auth/login",
                json={"username": self.username, "password": self.password},
                headers={"Content-Type": "application/json"}, timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise SilverlogError(f"어드민 로그인 실패: {exc}") from exc

    def get_catalogue(self) -> list[dict[str, Any]]:
        try:
            response = self.session.get(f"{self.base_url}/api/catalogue?all=true", timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise SilverlogError(f"카탈로그 조회 실패: {exc}") from exc
        if isinstance(payload, dict):
            payload = payload.get("items", payload.get("data", []))
        if not isinstance(payload, list):
            raise SilverlogError("카탈로그 API 응답 형식이 올바르지 않습니다.")
        return payload

    def update_item(self, item_id: str, payload: dict[str, Any]) -> None:
        try:
            response = self.session.patch(
                f"{self.base_url}/api/catalogue/{item_id}", json=payload,
                headers={"Content-Type": "application/json", "Accept": "*/*"}, timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise SilverlogError(f"상품 업데이트 실패: {exc}") from exc
