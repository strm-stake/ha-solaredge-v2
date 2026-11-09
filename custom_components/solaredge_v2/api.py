"""Async client for the SolarEdge Monitoring API v2 (OAuth 2.0 Site Access)."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import secrets
import time
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

from .const import API_BASE, TOKEN_URL

_LOGGER = logging.getLogger(__name__)
_TIMEOUT = aiohttp.ClientTimeout(total=30)


class SolarEdgeError(Exception):
    """Base error."""


class SolarEdgeAuthError(SolarEdgeError):
    """Credentials or tokens were refused."""


class SolarEdgeQuotaError(SolarEdgeError):
    """HTTP 429: rate or monthly credit limit reached."""


class SolarEdgeApiError(SolarEdgeError):
    """Any other API/network failure (status 0 = network error)."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message


def generate_pkce() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) using S256."""
    verifier = secrets.token_urlsafe(64)[:96]
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def normalize_token(data: dict[str, Any], old_refresh: str | None = None) -> dict[str, Any]:
    access = data.get("access_token")
    if not access:
        raise SolarEdgeAuthError("Token response contains no access_token")
    return {
        "access_token": access,
        # SolarEdge rotates refresh tokens; keep the old one only if none returned.
        "refresh_token": data.get("refresh_token") or old_refresh,
        "expires_at": time.time() + float(data.get("expires_in") or 3600),
    }


async def token_request(
    session: aiohttp.ClientSession,
    payload: dict[str, Any],
    client_id: str,
    client_secret: str,
) -> dict[str, Any]:
    """POST to the token endpoint (JSON body; falls back to HTTP Basic auth)."""
    attempts: list[tuple[dict[str, Any], aiohttp.BasicAuth | None]] = [
        ({**payload, "client_id": client_id, "client_secret": client_secret}, None),
        (payload, aiohttp.BasicAuth(client_id, client_secret)),
    ]
    last: tuple[int, str] = (0, "")
    for body, auth in attempts:
        try:
            async with session.post(
                TOKEN_URL, json=body, auth=auth, timeout=_TIMEOUT
            ) as resp:
                text = await resp.text()
                if resp.status == 200:
                    return json.loads(text)
                if resp.status == 429:
                    raise SolarEdgeQuotaError("Token endpoint rate limited")
                if resp.status >= 500:
                    raise SolarEdgeApiError(resp.status, text[:300])
                last = (resp.status, text[:300])
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise SolarEdgeApiError(0, str(err)) from err
    raise SolarEdgeAuthError(f"Token request refused ({last[0]}): {last[1]}")


async def exchange_code(
    session: aiohttp.ClientSession,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    code_verifier: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"grant_type": "authorization_code", "code": code}
    if code_verifier:
        payload["code_verifier"] = code_verifier
    try:
        data = await token_request(
            session, {**payload, "redirect_uri": redirect_uri}, client_id, client_secret
        )
    except SolarEdgeAuthError as err:
        if "redirect_uri" not in str(err).lower():
            raise
        # SolarEdge compares against the URIs registered in the app; retry
        # without it so the registered one is used. Keep the first error if that fails too.
        _LOGGER.warning("redirect_uri rejected, retrying without it: %s", err)
        try:
            data = await token_request(session, payload, client_id, client_secret)
        except SolarEdgeAuthError:
            raise err from None
    return normalize_token(data)


class SolarEdgeV2Client:
    """Bearer-token client with automatic, persisted refresh-token rotation."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        client_id: str,
        client_secret: str,
        site_id: str,
        token: dict[str, Any],
        on_token_update: Callable[[dict[str, Any]], Awaitable[None]],
        on_request: Callable[[], None] | None = None,
    ) -> None:
        self._session = session
        self._client_id = client_id
        self._client_secret = client_secret
        self.site_id = site_id
        self._token = token
        self._on_token_update = on_token_update
        self._on_request = on_request
        self._lock = asyncio.Lock()

    async def _access_token(self, force: bool = False) -> str:
        async with self._lock:
            if force or self._token["expires_at"] - time.time() < 60:
                await self._refresh()
            return self._token["access_token"]

    async def _refresh(self) -> None:
        refresh = self._token.get("refresh_token")
        if not refresh:
            raise SolarEdgeAuthError("No refresh token available")
        data = await token_request(
            self._session,
            {"grant_type": "refresh_token", "refresh_token": refresh},
            self._client_id,
            self._client_secret,
        )
        self._token = normalize_token(data, old_refresh=refresh)
        # Persist immediately: the old refresh token is no longer valid.
        await self._on_token_update(self._token)

    async def get(
        self, path: str, params: dict[str, Any] | list[tuple[str, str]] | None = None
    ) -> Any:
        url = f"{API_BASE}{path.format(site=self.site_id)}"
        for attempt in range(2):
            token = await self._access_token(force=attempt == 1)
            if self._on_request:
                self._on_request()
            try:
                async with self._session.get(
                    url,
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=_TIMEOUT,
                ) as resp:
                    text = await resp.text()
                    if resp.status == 401 and attempt == 0:
                        continue
                    if resp.status in (401, 403) and attempt == 1:
                        raise SolarEdgeAuthError(f"HTTP {resp.status}: {text[:200]}")
                    if resp.status == 429:
                        raise SolarEdgeQuotaError(text[:200])
                    if resp.status >= 400:
                        raise SolarEdgeApiError(resp.status, text[:300])
                    return json.loads(text) if text else {}
            except (aiohttp.ClientError, TimeoutError, ValueError) as err:
                raise SolarEdgeApiError(0, str(err)) from err
        raise SolarEdgeAuthError("Unauthorized")
