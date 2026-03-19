"""Configuration helpers for the local tunnel agent."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import quote, urlparse, urlunparse

from forwarding_service.shared.config_utils import (
    load_float_env,
    load_required_secret_env,
)


def build_tunnel_websocket_url(base_server_url: str, tunnel_id: str) -> str:
    """Build the WebSocket registration URL for one tunnel id.

    Args:
        base_server_url: Base server URL such as `https://example.com`.
        tunnel_id: Tunnel identifier.

    Returns:
        str: WebSocket registration URL.
    """
    parsed_server_url = urlparse(base_server_url.strip())
    normalized_scheme = {
        "http": "ws",
        "https": "wss",
        "ws": "ws",
        "wss": "wss",
    }.get(parsed_server_url.scheme or "ws", "ws")
    normalized_path = parsed_server_url.path.rstrip("/")
    return urlunparse(
        (
            normalized_scheme,
            parsed_server_url.netloc,
            f"{normalized_path}/ws/tunnels/{quote(tunnel_id, safe='')}",
            "",
            "",
            "",
        )
    )


@dataclass(frozen=True)
class TunnelAgentConfig:
    """Runtime configuration for the local tunnel agent."""

    public_base_url: str | None
    tunnel_server_url: str
    tunnel_id: str
    shared_token: str
    upstream_url: str
    heartbeat_interval_seconds: float
    reconnect_delay_seconds: float
    max_reconnect_delay_seconds: float
    request_timeout_seconds: float
    open_timeout_seconds: float
    log_level: str

    @property
    def websocket_url(self) -> str:
        """Return the full WebSocket registration URL."""
        return build_tunnel_websocket_url(self.tunnel_server_url, self.tunnel_id)

    @classmethod
    def from_env(cls) -> "TunnelAgentConfig":
        """Build agent configuration from environment variables.

        Returns:
            TunnelAgentConfig: Parsed agent configuration.

        Raises:
            ValueError: Raised when required variables are missing.
        """
        tunnel_id = os.getenv("KODA_TUNNEL_ID", "default").strip()
        if tunnel_id == "":
            raise ValueError("KODA_TUNNEL_ID must not be empty")

        return cls(
            public_base_url=os.getenv("KODA_PUBLIC_BASE_URL"),
            tunnel_server_url=os.getenv(
                "KODA_TUNNEL_SERVER_URL",
                "ws://127.0.0.1:9000",
            ),
            tunnel_id=tunnel_id,
            shared_token=load_required_secret_env("KODA_TUNNEL_SHARED_TOKEN"),
            upstream_url=os.getenv(
                "KODA_TUNNEL_UPSTREAM_URL",
                "http://127.0.0.1:8000",
            ),
            heartbeat_interval_seconds=load_float_env(
                "KODA_TUNNEL_HEARTBEAT_INTERVAL_SECONDS",
                15.0,
            ),
            reconnect_delay_seconds=load_float_env(
                "KODA_TUNNEL_RECONNECT_DELAY_SECONDS",
                2.0,
            ),
            max_reconnect_delay_seconds=load_float_env(
                "KODA_TUNNEL_MAX_RECONNECT_DELAY_SECONDS",
                15.0,
            ),
            request_timeout_seconds=load_float_env(
                "KODA_TUNNEL_REQUEST_TIMEOUT_SECONDS",
                30.0,
            ),
            open_timeout_seconds=load_float_env(
                "KODA_TUNNEL_OPEN_TIMEOUT_SECONDS",
                10.0,
            ),
            log_level=os.getenv("KODA_TUNNEL_AGENT_LOG_LEVEL", "INFO"),
        )
