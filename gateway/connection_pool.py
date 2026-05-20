"""
ConnectionPoolManager — manages a dedicated httpx.AsyncClient (connection pool)
per upstream service.

Why a pool per service?
-----------------------
httpx.AsyncClient maintains a pool of persistent TCP connections internally.
Keeping one client per service means:
  • Auth traffic never exhausts Chat's connections
  • Each pool is sized appropriately for its service
  • Timeouts / retries can be tuned per service in the future
  • Clean teardown on shutdown

Under the hood
--------------
httpx uses h11 (HTTP/1.1) and h2 (HTTP/2) transports.
httpx.AsyncHTTPTransport is the object that actually manages the socket pool.
We configure it with:
  max_connections     — hard cap on total open sockets
  max_keepalive_connections — sockets kept open idle (warm pool)
"""

import httpx
from gateway.config import settings


class ConnectionPoolManager:
    def __init__(self):
        # Clients are created on startup; keyed by service name
        self._clients: dict[str, httpx.AsyncClient] = {}

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def startup(self):
        """Create one AsyncClient per configured service."""
        for service_name, base_url in settings.service_urls.items():
            transport = httpx.AsyncHTTPTransport(
                # Hard limit: how many simultaneous open sockets
                limits=httpx.Limits(
                    max_connections=settings.pool_max_connections,
                    max_keepalive_connections=settings.pool_max_keepalive,
                    # How long (seconds) to hold an idle socket open
                    keepalive_expiry=30,
                ),
                retries=0,  # Retries are handled at the gateway layer (Phase 2)
            )
            self._clients[service_name] = httpx.AsyncClient(
                transport=transport,
                timeout=httpx.Timeout(
                    connect=settings.connect_timeout,
                    read=settings.request_timeout,
                    write=settings.request_timeout,
                    pool=settings.connect_timeout,
                ),
                # Follow redirects from upstream
                follow_redirects=True,
                # base_url is optional here; we build full URLs in the router
            )
            print(f"  🔌 Pool ready for '{service_name}' → {base_url}")

    async def shutdown(self):
        """Gracefully close all client pools."""
        for service_name, client in self._clients.items():
            await client.aclose()
            print(f"  🔒 Pool closed for '{service_name}'")
        self._clients.clear()

    # ── Access ────────────────────────────────────────────────────────────────

    def get_client(self, service_name: str) -> httpx.AsyncClient:
        """
        Return the dedicated AsyncClient for a service.
        Falls back to the first available client if service is unknown
        (should not happen in normal operation).
        """
        client = self._clients.get(service_name)
        if client is None:
            # Fallback: create an ephemeral client (this is a safety net)
            return httpx.AsyncClient()
        return client

    @property
    def pool_info(self) -> dict:
        """Return a summary of all active pools (useful for metrics)."""
        info = {}
        for name, client in self._clients.items():
            # httpx exposes internal pool stats via the transport
            transport = client._transport  # noqa: SLF001
            if hasattr(transport, "_pool"):
                pool = transport._pool  # noqa: SLF001
                info[name] = {
                    "connections": len(pool.connections),
                }
            else:
                info[name] = {"connections": "n/a"}
        return info
