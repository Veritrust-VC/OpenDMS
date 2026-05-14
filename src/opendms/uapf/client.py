"""
UapfClient — thin async wrapper around the UAPF-IP v0.1 REST surface
of the uapf-engine reference runtime.
"""

import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


class UapfClient:
    def __init__(
        self,
        engine_url: str,
        auth_token: Optional[str] = None,
        timeout_seconds: float = 30.0,
    ):
        if not engine_url:
            raise ValueError("UapfClient: engine_url is required")
        self.engine_url = engine_url.rstrip("/")
        self.auth_token = auth_token
        self.timeout = timeout_seconds

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.auth_token:
            h["Authorization"] = f"Bearer {self.auth_token}"
        return h

    async def start_session(
        self,
        package_id: str,
        process_id: str,
        input_payload: Any,
        host_manifest: dict,
        package_version: Optional[str] = None,
    ) -> dict:
        """Trigger a UAPF process execution."""
        body = {
            "packageId": package_id,
            "processId": process_id,
            "input": input_payload,
            "hostManifest": host_manifest,
        }
        if package_version:
            body["packageVersion"] = package_version

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(
                f"{self.engine_url}/uapf/start-session",
                headers=self._headers(),
                json=body,
            )
            if r.status_code >= 400:
                raise RuntimeError(
                    f"UAPF engine returned {r.status_code}: {r.text[:500]}"
                )
            return r.json()

    async def evaluate_decision(
        self, package_id: str, decision_id: str, input_payload: Any
    ) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(
                f"{self.engine_url}/uapf/evaluate-decision",
                headers=self._headers(),
                json={
                    "packageId": package_id,
                    "decisionId": decision_id,
                    "input": input_payload,
                },
            )
            r.raise_for_status()
            return r.json()

    async def get_session(self, session_id: str) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.get(
                f"{self.engine_url}/uapf/sessions/{session_id}",
                headers=self._headers(),
            )
            r.raise_for_status()
            return r.json()

    async def get_session_audit(self, session_id: str) -> list:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.get(
                f"{self.engine_url}/uapf/sessions/{session_id}/audit",
                headers=self._headers(),
            )
            r.raise_for_status()
            return r.json()

    async def list_packages(self) -> list:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.get(
                f"{self.engine_url}/uapf/packages", headers=self._headers()
            )
            r.raise_for_status()
            return r.json()

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{self.engine_url}/health")
                return r.status_code == 200
        except Exception:
            return False
