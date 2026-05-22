"""
Gateway configuration — loaded from environment variables / .env file.
All values have sensible defaults so the gateway works out-of-the-box.
"""

from typing import Dict
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Service URLs ──────────────────────────────────────────────────────────
    # Each service can be overridden via environment variable, e.g.
    #   AUTH_SERVICE_URL=http://my-auth:9001
    auth_service_url: str = "http://localhost:9001"
    user_service_url: str = "http://localhost:8001"
    chat_service_url: str = "http://localhost:9002"
    ai_service_url: str = "http://localhost:9003"
    products_service_url: str = "http://localhost:9004"

    # ── HTTP client / pool settings ───────────────────────────────────────────
    # Max persistent connections per upstream host
    pool_max_connections: int = 100
    # Max connections kept open waiting (keepalive)
    pool_max_keepalive: int = 20
    # Seconds before a request is considered timed out
    request_timeout: float = 30.0
    # Seconds to wait when establishing a new TCP connection
    connect_timeout: float = 5.0

    # ── Gateway ───────────────────────────────────────────────────────────────
    gateway_host: str = "0.0.0.0"
    gateway_port: int = 8000
    log_level: str = "INFO"
    environment: str = "development"

    # ── Database & Redis ──────────────────────────────────────────────────────
    database_url: str = "mongodb://localhost:27017/smart-api-gateway"
    redis_url: str = "redis://localhost:6379/0"

    # ── Security ──────────────────────────────────────────────────────────────
    secret_key: str = "super-secret-gateway-key-change-me-in-production"
    jwt_algorithm: str = "HS256"
    public_prefixes: list[str] = ["/auth/login", "/health", "/gateway"]

    # ── Rate Limiting ─────────────────────────────────────────────────────────
    rate_limit_requests: int = 10
    rate_limit_window: int = 60  # seconds

    # ── Route table ───────────────────────────────────────────────────────────
    # Prefix → service name.  The service name is used to look up the URL
    # above and to select the right connection-pool client.
    @property
    def route_table(self) -> Dict[str, str]:
        return {
            "/auth": "auth",
            "/users": "user",
            "/chat": "chat",
            "/ai": "ai",
            "/products": "products",
        }

    @property
    def service_urls(self) -> Dict[str, str]:
        return {
            "auth": self.auth_service_url,
            "user": self.user_service_url,
            "chat": self.chat_service_url,
            "ai": self.ai_service_url,
            "products": self.products_service_url,
        }


# Singleton — import this everywhere
settings = Settings()
