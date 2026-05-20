"""
Tests for Phase 1 — Core Gateway
Run: pytest tests/ -v

Router tests: pure Python unit tests.
Integration tests: Starlette TestClient (handles lifespan, synchronous but correct).
Logger tests: async unit tests.
"""

import pytest
from starlette.testclient import TestClient

from gateway.router import GatewayRouter
from gateway.config import Settings


# ─────────────────────────────────────────────────────────────────────────────
# Fixture — full app with lifespan (app.state populated)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def gateway():
    from gateway.main import app
    with TestClient(app) as client:
        yield client


# ─────────────────────────────────────────────────────────────────────────────
# Router unit tests
# ─────────────────────────────────────────────────────────────────────────────

class TestGatewayRouter:
    def _router(self) -> GatewayRouter:
        s = Settings(
            auth_service_url="http://auth:9001",
            chat_service_url="http://chat:9002",
            ai_service_url="http://ai:9003",
        )
        return GatewayRouter(s)

    def test_resolves_auth(self):
        url, svc = self._router().resolve("/auth/login")
        assert svc == "auth" and url == "http://auth:9001/auth/login"

    def test_resolves_chat(self):
        url, svc = self._router().resolve("/chat/rooms")
        assert svc == "chat" and url == "http://chat:9002/chat/rooms"

    def test_resolves_ai(self):
        url, svc = self._router().resolve("/ai/complete")
        assert svc == "ai" and url == "http://ai:9003/ai/complete"

    def test_unknown_returns_none(self):
        url, svc = self._router().resolve("/unknown/path")
        assert url is None and svc is None

    def test_root_returns_none(self):
        assert self._router().resolve("/") == (None, None)

    def test_preserves_deep_path(self):
        url, _ = self._router().resolve("/auth/user/profile/avatar")
        assert url == "http://auth:9001/auth/user/profile/avatar"

    def test_describe_has_all_routes(self):
        prefixes = [r["prefix"] for r in self._router().describe()]
        assert {"/auth", "/chat", "/ai"}.issubset(prefixes)

    def test_dynamic_route_add(self):
        r = self._router()
        r.add_route("/metrics", "metrics", "http://metrics:9099")
        url, svc = r.resolve("/metrics/cpu")
        assert svc == "metrics" and url == "http://metrics:9099/metrics/cpu"

    def test_longest_prefix_wins(self):
        r = self._router()
        r.add_route("/a", "short", "http://short:9099")
        _, svc = r.resolve("/auth/me")
        assert svc == "auth"


# ─────────────────────────────────────────────────────────────────────────────
# Integration tests (lifespan active via TestClient)
# ─────────────────────────────────────────────────────────────────────────────

def test_health_endpoint(gateway):
    resp = gateway.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["phase"] == 1


def test_gateway_routes_endpoint(gateway):
    resp = gateway.get("/gateway/routes")
    assert resp.status_code == 200
    prefixes = [r["prefix"] for r in resp.json()["routes"]]
    assert "/auth" in prefixes and "/chat" in prefixes


def test_unknown_route_404(gateway):
    resp = gateway.get("/unknown/endpoint")
    assert resp.status_code == 404
    assert resp.json()["error"] == "no_route"


def test_request_id_header(gateway):
    resp = gateway.get("/health")
    assert "x-request-id" in resp.headers


def test_response_time_header(gateway):
    resp = gateway.get("/health")
    assert "x-response-time" in resp.headers
    assert resp.headers["x-response-time"].endswith("ms")


# ─────────────────────────────────────────────────────────────────────────────
# Logger unit tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_logger_buffers():
    from gateway.logger import GatewayLogger
    logger = GatewayLogger()
    await logger.log(
        request_id="x1", method="GET", path="/auth/me",
        service="auth", upstream="http://localhost:9001/auth/me",
        status=200, latency_ms=12.5,
    )
    assert len(logger.recent(10)) == 1


@pytest.mark.asyncio
async def test_logger_stats():
    from gateway.logger import GatewayLogger
    logger = GatewayLogger()
    for i in range(5):
        await logger.log(
            request_id=f"r{i}", method="GET", path="/chat/rooms",
            service="chat", upstream="http://localhost:9002/chat/rooms",
            status=500 if i == 4 else 200, latency_ms=10.0,
        )
    stats = logger.stats()
    assert stats["total"] == 5
    assert stats["errors"] == 1
    assert stats["by_service"]["chat"] == 5
