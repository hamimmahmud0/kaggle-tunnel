"""Tunnelbroker API client.

A Python client for the Cloudflare Worker peer discovery service.
Used by both the notebook cell (to register tunnels) and the manager
app (to discover and manage instances).
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiohttp


DEFAULT_PEER_TTL = 43200  # 12 hours
TUNNELBROKER_VERSION = "0.1.0"


@dataclass
class PeerInfo:
    """Deserialized peer record returned by the broker."""

    peer: str
    endpoint: str | None = None
    contacts: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    expiresAt: str | None = None


@dataclass
class ServerInfo:
    """Deserialized server record."""

    id: str
    url: str
    updatedAt: str


@dataclass
class HealthInfo:
    ok: bool
    server: ServerInfo


class TunnelbrokerError(Exception):
    """Raised when the tunnelbroker API returns a non-2xx status."""

    def __init__(self, status: int, body: str, message: str | None = None):
        self.status = status
        self.body = body
        super().__init__(message or f"tunnelbroker error {status}: {body}")


class TunnelbrokerClient:
    """Async HTTP client for tunnelbroker peer registry.

    Args:
        base_url: Root URL of the tunnelbroker Worker
            (e.g. ``https://tunnelbroker.hamimmahmud0.workers.dev``).
        group: Peer group namespace to operate in.
        group_token: Optional bearer token for group-level auth.
        session: Optional shared ``aiohttp.ClientSession``.  If omitted
            a session is created internally (and closed on ``close()``).
    """

    def __init__(
        self,
        base_url: str,
        group: str,
        group_token: str | None = None,
        session: aiohttp.ClientSession | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.group = group
        self.group_token = group_token
        self._owns_session = session is None
        self._session = session or aiohttp.ClientSession(
            headers=self._default_headers(),
            timeout=aiohttp.ClientTimeout(total=15),
        )

    def _default_headers(self) -> dict[str, str]:
        headers = {
            "User-Agent": f"kaggle-tunnel/{TUNNELBROKER_VERSION}",
            "Content-Type": "application/json",
        }
        if self.group_token:
            headers["Authorization"] = f"Bearer {self.group_token}"
        return headers

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP session if we own it."""
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

    async def __aenter__(self) -> TunnelbrokerClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health(self) -> HealthInfo:
        """Return server health info."""
        data = await self._get("/health")
        return HealthInfo(
            ok=data["ok"],
            server=ServerInfo(**data["server"]),
        )

    # ------------------------------------------------------------------
    # Peer operations
    # ------------------------------------------------------------------

    async def register_peer(
        self,
        peer: str,
        secret: str,
        endpoint: str | None = None,
        contacts: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create or update a peer record.

        Args:
            peer: Unique peer identifier within the group.
            secret: Per-peer secret used for ownership verification.
            endpoint: Public tunnel URL (single-contact shorthand).
            contacts: List of contact dicts with ``endpoint``, ``label``,
                ``priority`` keys.  Mutually exclusive with ``endpoint``
                at the API level, but if both are provided ``contacts``
                takes precedence.
            metadata: Arbitrary key-value metadata to attach.

        Returns:
            The parsed JSON response body.
        """
        body: dict[str, Any] = {"peer": peer, "secret": secret}
        if contacts:
            body["contacts"] = contacts
        elif endpoint:
            body["endpoint"] = endpoint
        if metadata:
            body["metadata"] = metadata
        return await self._post(f"/v1/peers?group={self.group}", body)

    async def get_peer(self, peer: str) -> PeerInfo:
        """Fetch a single peer record.

        Raises ``TunnelbrokerError`` (404) if the peer does not exist.
        """
        data = await self._get(f"/v1/peers/{peer}?group={self.group}")
        return PeerInfo(**data)

    async def delete_peer(self, peer: str, secret: str) -> dict[str, Any]:
        """Delete a peer record.  Requires the correct ``secret``."""
        return await self._delete(
            f"/v1/peers/{peer}?group={self.group}",
            {"secret": secret},
        )

    async def list_peers(self) -> list[PeerInfo]:
        """List all currently live peers in the configured group."""
        data = await self._get(f"/v1/groups/{self.group}/peers")
        return [PeerInfo(**p) for p in data.get("peers", data)]

    # ------------------------------------------------------------------
    # TTL refresh helper
    # ------------------------------------------------------------------

    async def keep_alive(
        self,
        peer: str,
        secret: str,
        endpoint: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Re-register a peer to refresh its TTL.

        This is a thin wrapper around ``register_peer`` intended to be
        called periodically (e.g. every 6 hours) so the peer record
        does not expire.
        """
        return await self.register_peer(peer, secret, endpoint=endpoint, metadata=metadata)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        async with self._session.request(method, url, json=json_body) as resp:
            body = await resp.text()
            if not resp.ok:
                raise TunnelbrokerError(resp.status, body)
            if not body.strip():
                return {}
            return await resp.json()

    async def _get(self, path: str) -> dict[str, Any]:
        return await self._request("GET", path)

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", path, body)

    async def _delete(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self._request("DELETE", path, body)


# ------------------------------------------------------------------
# Synchronous convenience helpers (for scripts / simple use-cases)
# ------------------------------------------------------------------

def _sync_request(
    base_url: str,
    method: str,
    path: str,
    json_body: dict[str, Any] | None = None,
    group_token: str | None = None,
    timeout: int = 15,
) -> dict[str, Any]:
    """Blocking HTTP request helper (uses ``urllib``, no asyncio needed)."""
    import json as _json
    import urllib.error
    import urllib.request

    url = f"{base_url.rstrip('/')}{path}"
    headers = {
        "User-Agent": f"kaggle-tunnel/{TUNNELBROKER_VERSION}",
        "Content-Type": "application/json",
    }
    if group_token:
        headers["Authorization"] = f"Bearer {group_token}"

    data = _json.dumps(json_body).encode("utf-8") if json_body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            if not body.strip():
                return {}
            return _json.loads(body)
    except urllib.error.HTTPError as exc:
        raise TunnelbrokerError(exc.code, exc.read().decode("utf-8", errors="replace"))
    except urllib.error.URLError as exc:
        raise TunnelbrokerError(0, str(exc.reason))


def register_peer_sync(
    base_url: str,
    group: str,
    peer: str,
    secret: str,
    endpoint: str | None = None,
    metadata: dict[str, Any] | None = None,
    group_token: str | None = None,
) -> dict[str, Any]:
    """Synchronously register a peer (convenience for scripts)."""
    body: dict[str, Any] = {"peer": peer, "secret": secret}
    if endpoint:
        body["endpoint"] = endpoint
    if metadata:
        body["metadata"] = metadata
    return _sync_request(
        base_url, "POST", f"/v1/peers?group={group}", body, group_token
    )


def list_peers_sync(
    base_url: str,
    group: str,
    group_token: str | None = None,
) -> list[PeerInfo]:
    """Synchronously list peers (convenience for scripts)."""
    data = _sync_request(
        base_url, "GET", f"/v1/groups/{group}/peers", group_token=group_token
    )
    return [PeerInfo(**p) for p in data.get("peers", data)]


def delete_peer_sync(
    base_url: str,
    group: str,
    peer: str,
    secret: str,
    group_token: str | None = None,
) -> dict[str, Any]:
    """Synchronously delete a peer (convenience for scripts)."""
    return _sync_request(
        base_url,
        "DELETE",
        f"/v1/peers/{peer}?group={group}",
        {"secret": secret},
        group_token,
    )
