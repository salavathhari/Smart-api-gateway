"""
GatewayRouter — maps incoming URL prefixes to upstream service URLs.

Routing algorithm
-----------------
Longest-prefix match: /auth/me is more specific than /auth, so it wins.
This mirrors how Nginx location blocks work.

Example table
-------------
  /auth  → http://localhost:9001
  /chat  → http://localhost:9002
  /ai    → http://localhost:9003

Request:  GET /auth/login/google
Resolved: http://localhost:9001/auth/login/google
"""

from typing import Optional, Tuple, List, Dict
from gateway.config import Settings


class GatewayRouter:
    def __init__(self, settings: Settings):
        self._settings = settings
        # Pre-build sorted list: longest prefix first for O(n) match
        self._routes: List[Tuple[str, str]] = sorted(
            settings.route_table.items(), key=lambda kv: len(kv[0]), reverse=True
        )
        self._service_urls: Dict[str, str] = settings.service_urls

    # ── Public API ────────────────────────────────────────────────────────────

    def resolve(self, path: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Resolve a URL path to an (upstream_url, service_name) pair.

        Returns (None, None) if no prefix matches.

        The upstream_url already includes the full path so the caller can
        forward directly to it.

        Example
        -------
        resolve("/auth/me")
        → ("http://localhost:9001/auth/me", "auth")
        """
        for prefix, service_name in self._routes:
            if path.startswith(prefix):
                base_url = self._service_urls.get(service_name)
                if base_url is None:
                    continue
                # Strip trailing slash from base, keep path as-is
                upstream = base_url.rstrip("/") + path
                return upstream, service_name
        return None, None

    def describe(self) -> List[Dict]:
        """Return the routing table as a list of dicts (for the /gateway/routes endpoint)."""
        return [
            {
                "prefix": prefix,
                "service": service_name,
                "upstream_base": self._service_urls.get(service_name, "NOT CONFIGURED"),
            }
            for prefix, service_name in self._routes
        ]

    def add_route(self, prefix: str, service_name: str, upstream_url: str) -> None:
        """Dynamically add a new route at runtime (useful for tests)."""
        self._service_urls[service_name] = upstream_url
        self._routes.append((prefix, service_name))
        # Re-sort to maintain longest-prefix-first order
        self._routes.sort(key=lambda kv: len(kv[0]), reverse=True)
