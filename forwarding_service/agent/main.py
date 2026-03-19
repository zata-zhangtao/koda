"""CLI entrypoint and runtime loop for the local tunnel agent."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any, Protocol

from dotenv import find_dotenv, load_dotenv
import websockets
from websockets.exceptions import ConnectionClosed

from forwarding_service.agent.config import TunnelAgentConfig
from forwarding_service.agent.http_bridge import UpstreamHttpBridge
from forwarding_service.shared.http import encode_body_bytes
from forwarding_service.shared.logging_utils import get_structured_logger, log_event
from forwarding_service.shared.messages import (
    AgentHttpResponseMessage,
    GatewayHttpRequestMessage,
    TunnelHeartbeatAckMessage,
    TunnelHeartbeatMessage,
    parse_tunnel_message,
)


class AgentWebSocketProtocol(Protocol):
    """Minimal agent-side WebSocket protocol used for runtime and tests."""

    async def send(self, data: str) -> None:
        """Send a text frame."""

    async def recv(self) -> str:
        """Receive a text frame."""

    async def close(self) -> None:
        """Close the connection."""


class TunnelAgent:
    """Reconnectable local agent that bridges gateway requests to the DSL app."""

    def __init__(self, agent_config: TunnelAgentConfig) -> None:
        """Initialize the tunnel agent.

        Args:
            agent_config: Agent runtime configuration.
        """
        self._agent_config = agent_config
        self._structured_logger = get_structured_logger(
            "koda.public_agent",
            agent_config.log_level,
        )
        self._upstream_http_bridge = UpstreamHttpBridge(
            upstream_base_url=agent_config.upstream_url,
            request_timeout_seconds=agent_config.request_timeout_seconds,
        )
        self._shutdown_event = asyncio.Event()
        self._agent_instance_id = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")

    async def close(self) -> None:
        """Shut down the agent and close its HTTP bridge."""
        self._shutdown_event.set()
        await self._upstream_http_bridge.close()

    async def run_forever(
        self,
        connect_callable: Any | None = None,
        max_connection_attempts: int | None = None,
    ) -> None:
        """Run the agent with reconnect logic until shutdown.

        Args:
            connect_callable: Optional injected connection factory for tests.
            max_connection_attempts: Optional cap used by tests.
        """
        resolved_connect_callable = connect_callable or websockets.connect
        current_reconnect_delay_seconds = self._agent_config.reconnect_delay_seconds
        completed_connection_attempt_count = 0

        while not self._shutdown_event.is_set():
            if (
                max_connection_attempts is not None
                and completed_connection_attempt_count >= max_connection_attempts
            ):
                return
            completed_connection_attempt_count += 1

            try:
                await self._run_connection_once(resolved_connect_callable)
                current_reconnect_delay_seconds = self._agent_config.reconnect_delay_seconds
            except Exception as connection_error:
                log_event(
                    self._structured_logger,
                    "warning",
                    "agent_connection_failed",
                    {
                        "error": str(connection_error),
                        "public_base_url": self._agent_config.public_base_url,
                        "tunnel_id": self._agent_config.tunnel_id,
                        "websocket_url": self._agent_config.websocket_url,
                    },
                )
                await asyncio.sleep(current_reconnect_delay_seconds)
                current_reconnect_delay_seconds = min(
                    current_reconnect_delay_seconds * 2,
                    self._agent_config.max_reconnect_delay_seconds,
                )

    async def _run_connection_once(self, connect_callable: Any) -> None:
        """Open one WebSocket connection and serve it until disconnect.

        Args:
            connect_callable: Connection factory compatible with `websockets.connect`.
        """
        log_event(
            self._structured_logger,
            "info",
            "agent_connecting",
            {
                "tunnel_id": self._agent_config.tunnel_id,
                "upstream_url": self._agent_config.upstream_url,
                "websocket_url": self._agent_config.websocket_url,
            },
        )

        async with connect_callable(
            self._agent_config.websocket_url,
            additional_headers={
                "x-koda-tunnel-token": self._agent_config.shared_token,
            },
            open_timeout=self._agent_config.open_timeout_seconds,
            max_size=None,
            ping_interval=None,
        ) as websocket_connection:
            log_event(
                self._structured_logger,
                "info",
                "agent_connected",
                {
                    "agent_instance_id": self._agent_instance_id,
                    "tunnel_id": self._agent_config.tunnel_id,
                },
            )
            heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(websocket_connection),
                name="koda-tunnel-heartbeat",
            )
            receive_task = asyncio.create_task(
                self._receive_loop(websocket_connection),
                name="koda-tunnel-receive",
            )
            done_task_set, pending_task_set = await asyncio.wait(
                {heartbeat_task, receive_task},
                return_when=asyncio.FIRST_EXCEPTION,
            )
            for pending_task in pending_task_set:
                pending_task.cancel()
            await asyncio.gather(*pending_task_set, return_exceptions=True)
            for done_task in done_task_set:
                done_task.result()

    async def _heartbeat_loop(self, websocket_connection: AgentWebSocketProtocol) -> None:
        """Send periodic heartbeat messages while the connection is alive.

        Args:
            websocket_connection: Active WebSocket connection.
        """
        while not self._shutdown_event.is_set():
            heartbeat_message = TunnelHeartbeatMessage(
                tunnel_id=self._agent_config.tunnel_id,
                agent_instance_id=self._agent_instance_id,
                sent_at_iso=datetime.now(UTC).isoformat(),
            )
            await websocket_connection.send(heartbeat_message.model_dump_json())
            log_event(
                self._structured_logger,
                "info",
                "agent_heartbeat_sent",
                {
                    "agent_instance_id": self._agent_instance_id,
                    "tunnel_id": self._agent_config.tunnel_id,
                },
            )
            await asyncio.sleep(self._agent_config.heartbeat_interval_seconds)

    async def _receive_loop(self, websocket_connection: AgentWebSocketProtocol) -> None:
        """Receive and handle gateway messages.

        Args:
            websocket_connection: Active WebSocket connection.
        """
        while not self._shutdown_event.is_set():
            try:
                raw_message_text = await asyncio.wait_for(
                    websocket_connection.recv(),
                    timeout=self._agent_config.request_timeout_seconds,
                )
            except asyncio.TimeoutError as timeout_error:
                raise TimeoutError("No traffic received from gateway within timeout window") from timeout_error
            except ConnectionClosed as connection_closed_error:
                raise RuntimeError("Gateway websocket closed") from connection_closed_error

            raw_payload = json.loads(raw_message_text)
            parsed_message = parse_tunnel_message(raw_payload)

            if isinstance(parsed_message, TunnelHeartbeatAckMessage):
                log_event(
                    self._structured_logger,
                    "info",
                    "agent_heartbeat_ack",
                    {
                        "agent_instance_id": self._agent_instance_id,
                        "tunnel_id": self._agent_config.tunnel_id,
                    },
                )
                continue

            if isinstance(parsed_message, GatewayHttpRequestMessage):
                outbound_response_message = await self._handle_http_request_message(
                    parsed_message
                )
                await websocket_connection.send(outbound_response_message.model_dump_json())
                continue

            raise RuntimeError(f"Unsupported gateway message type: {parsed_message.message_type}")

    async def _handle_http_request_message(
        self,
        request_message: GatewayHttpRequestMessage,
    ) -> AgentHttpResponseMessage:
        """Forward one HTTP request to the local DSL upstream.

        Args:
            request_message: Gateway request envelope.

        Returns:
            AgentHttpResponseMessage: Upstream response envelope.
        """
        try:
            upstream_response_message = await self._upstream_http_bridge.forward_request(
                request_message
            )
            log_event(
                self._structured_logger,
                "info",
                "agent_request_forwarded",
                {
                    "request_id": request_message.request_id,
                    "method": request_message.method,
                    "path": request_message.path,
                    "status_code": upstream_response_message.status_code,
                },
            )
            return upstream_response_message
        except Exception as upstream_error:
            log_event(
                self._structured_logger,
                "warning",
                "agent_upstream_failed",
                {
                    "request_id": request_message.request_id,
                    "method": request_message.method,
                    "path": request_message.path,
                    "error": str(upstream_error),
                },
            )
            return AgentHttpResponseMessage(
                request_id=request_message.request_id,
                status_code=502,
                headers=[],
                body_base64=encode_body_bytes(b"Upstream Request Failed"),
            )


def _load_agent_dotenv() -> None:
    """Load the current working directory `.env` before CLI config parsing."""
    dotenv_file_path = find_dotenv(filename=".env", usecwd=True)
    if dotenv_file_path != "":
        load_dotenv(dotenv_file_path, override=False)


async def main_async() -> None:
    """Run the tunnel agent until interrupted."""
    _load_agent_dotenv()
    tunnel_agent = TunnelAgent(TunnelAgentConfig.from_env())
    try:
        await tunnel_agent.run_forever()
    finally:
        await tunnel_agent.close()


def main() -> None:
    """Synchronous CLI wrapper for the async tunnel agent."""
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
