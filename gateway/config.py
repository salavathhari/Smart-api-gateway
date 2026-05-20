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
    chat_service_url: str = "http://localhost:9002"
    ai_service_url: str = "http://localhost:9003"

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

    # ── Route table ───────────────────────────────────────────────────────────
    # Prefix → service name.  The service name is used to look up the URL
    # above and to select the right connection-pool client.
    @property
    def route_table(self) -> Dict[str, str]:
        return {
            "/auth": "auth",
            "/chat": "chat",
            "/ai": "ai",
        }

    @property
    def service_urls(self) -> Dict[str, str]:
        return {
            "auth": self.auth_service_url,
            "chat": self.chat_service_url,
            "ai": self.ai_service_url,
        }


# Singleton — import this everywhere
settings = Settings()
