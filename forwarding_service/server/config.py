"""Configuration models for the gateway server."""

from __future__ import annotations

import os
from dataclasses import dataclass

from forwarding_service.shared.config_utils import (
    load_float_env,
    load_int_env,
    load_required_secret_env,
)


@dataclass(frozen=True)
class GatewayServerConfig:
    """Runtime configuration for the public gateway server."""

    public_tunnel_id: str
    tunnel_shared_token: str
    request_timeout_seconds: float
    heartbeat_timeout_seconds: float
    host: str
    port: int
    log_level: str

    @classmethod
    def from_env(cls) -> "GatewayServerConfig":
        """Build gateway configuration from environment variables.

        Returns:
            GatewayServerConfig: Parsed gateway configuration.

        Raises:
            ValueError: Raised when required variables are missing.
        """
        public_tunnel_id = os.getenv("KODA_TUNNEL_ID", "default").strip()
        if public_tunnel_id == "":
            raise ValueError("KODA_TUNNEL_ID must not be empty")

        return cls(
            public_tunnel_id=public_tunnel_id,
            tunnel_shared_token=load_required_secret_env("KODA_TUNNEL_SHARED_TOKEN"),
            request_timeout_seconds=load_float_env(
                "KODA_TUNNEL_RESPONSE_TIMEOUT_SECONDS",
                30.0,
            ),
            heartbeat_timeout_seconds=load_float_env(
                "KODA_TUNNEL_HEARTBEAT_TIMEOUT_SECONDS",
                45.0,
            ),
            host=os.getenv("GATEWAY_HOST", "0.0.0.0"),
            port=load_int_env("GATEWAY_PORT", 9000),
            log_level=os.getenv("GATEWAY_LOG_LEVEL", "INFO"),
        )
