"""CLI entrypoint for running the public gateway server."""

from __future__ import annotations

import uvicorn

from forwarding_service.server.app import create_application
from forwarding_service.server.config import GatewayServerConfig


def main() -> None:
    """Run the public gateway server with uvicorn."""
    gateway_config = GatewayServerConfig.from_env()
    uvicorn.run(
        create_application(gateway_config),
        host=gateway_config.host,
        port=gateway_config.port,
        reload=False,
        log_level=gateway_config.log_level.lower(),
    )


if __name__ == "__main__":
    main()
