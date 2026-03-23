"""Tunnel session registry for the gateway server."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel

from forwarding_service.shared.messages import AgentHttpResponseMessage


class TunnelSessionClosedError(RuntimeError):
    """Raised when a request is sent over a closed tunnel session."""


class GatewayWebSocketProtocol(Protocol):
    """Minimal gateway-side WebSocket protocol used by the registry."""

    async def send_text(self, data: str) -> None:
        """Send a text frame."""

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        """Close the connection."""


@dataclass
class TunnelSession:
    """Represents one active agent connection for a specific tunnel id."""

    tunnel_id: str
    websocket: GatewayWebSocketProtocol
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    last_activity_monotonic: float = field(default_factory=time.monotonic)
    _pending_response_future_by_request_id: dict[
        str, asyncio.Future[AgentHttpResponseMessage]
    ] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    _send_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock, init=False, repr=False
    )
    _pending_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock, init=False, repr=False
    )
    _closed: bool = field(default=False, init=False, repr=False)

    def mark_activity(self) -> None:
        """Update the last-seen timestamp for heartbeat/liveness checks."""
        self.last_activity_monotonic = time.monotonic()

    def is_stale(self, heartbeat_timeout_seconds: float) -> bool:
        """Return whether the session exceeded the allowed inactivity window.

        Args:
            heartbeat_timeout_seconds: Allowed inactivity duration.

        Returns:
            bool: `True` when the session is stale.
        """
        return (
            time.monotonic() - self.last_activity_monotonic
        ) > heartbeat_timeout_seconds

    async def send_message(self, outbound_message: BaseModel) -> None:
        """Serialize and send a Pydantic message over the WebSocket.

        Args:
            outbound_message: Message model to serialize.
        """
        async with self._send_lock:
            await self.websocket.send_text(outbound_message.model_dump_json())

    async def wait_for_response(
        self,
        outbound_request_message: BaseModel,
        request_id: str,
        timeout_seconds: float,
    ) -> AgentHttpResponseMessage:
        """Send a request to the agent and await its correlated response.

        Args:
            outbound_request_message: HTTP request envelope.
            request_id: Correlation id.
            timeout_seconds: Maximum wait time.

        Returns:
            AgentHttpResponseMessage: Correlated upstream response.

        Raises:
            TimeoutError: Raised when the agent does not answer in time.
            TunnelSessionClosedError: Raised when the session closes mid-flight.
        """
        async with self._pending_lock:
            if self._closed:
                raise TunnelSessionClosedError("Tunnel session already closed")
            response_future = asyncio.get_running_loop().create_future()
            self._pending_response_future_by_request_id[request_id] = response_future

        try:
            await self.send_message(outbound_request_message)
            return await asyncio.wait_for(response_future, timeout=timeout_seconds)
        except asyncio.TimeoutError as timeout_error:
            raise TimeoutError(
                "Timed out waiting for tunnel agent response"
            ) from timeout_error
        finally:
            async with self._pending_lock:
                self._pending_response_future_by_request_id.pop(request_id, None)

    async def resolve_response(
        self, response_message: AgentHttpResponseMessage
    ) -> None:
        """Resolve a pending request future with the agent response.

        Args:
            response_message: Correlated agent response envelope.
        """
        self.mark_activity()
        async with self._pending_lock:
            response_future = self._pending_response_future_by_request_id.get(
                response_message.request_id
            )
            if response_future is not None and not response_future.done():
                response_future.set_result(response_message)

    async def close(self, close_code: int, close_reason: str) -> None:
        """Close the session and fail all in-flight requests.

        Args:
            close_code: WebSocket close code.
            close_reason: Human-readable close reason.
        """
        async with self._pending_lock:
            if self._closed:
                return
            self._closed = True
            pending_future_list = list(
                self._pending_response_future_by_request_id.values()
            )
            self._pending_response_future_by_request_id.clear()

        for pending_future in pending_future_list:
            if not pending_future.done():
                pending_future.set_exception(TunnelSessionClosedError(close_reason))

        try:
            await self.websocket.close(code=close_code, reason=close_reason)
        except Exception:
            return


class TunnelSessionRegistry:
    """Concurrency-safe registry of active tunnel sessions."""

    def __init__(self) -> None:
        """Initialize the registry."""
        self._session_by_tunnel_id: dict[str, TunnelSession] = {}
        self._registry_lock = asyncio.Lock()

    async def register(
        self,
        tunnel_id: str,
        websocket: GatewayWebSocketProtocol,
    ) -> tuple[TunnelSession, bool]:
        """Register a new session and replace any existing session deterministically.

        Args:
            tunnel_id: Tunnel identifier.
            websocket: Accepted WebSocket connection.

        Returns:
            tuple[TunnelSession, bool]: The new session and whether an old session was replaced.
        """
        new_session = TunnelSession(tunnel_id=tunnel_id, websocket=websocket)
        async with self._registry_lock:
            previous_session = self._session_by_tunnel_id.get(tunnel_id)
            self._session_by_tunnel_id[tunnel_id] = new_session

        if previous_session is not None:
            await previous_session.close(
                close_code=1012,
                close_reason="Replaced by newer tunnel session",
            )

        return new_session, previous_session is not None

    async def unregister_current(
        self,
        session: TunnelSession,
        close_code: int = 1000,
        close_reason: str = "Tunnel session closed",
    ) -> None:
        """Remove a session if it is still the active entry for its tunnel.

        Args:
            session: Session to unregister.
            close_code: Close code used when shutting down the session.
            close_reason: Close reason used when shutting down the session.
        """
        should_close_session = False
        async with self._registry_lock:
            current_session = self._session_by_tunnel_id.get(session.tunnel_id)
            if current_session is session:
                self._session_by_tunnel_id.pop(session.tunnel_id, None)
                should_close_session = True

        if should_close_session:
            await session.close(close_code=close_code, close_reason=close_reason)

    async def get_active_session(
        self,
        tunnel_id: str,
        heartbeat_timeout_seconds: float,
    ) -> TunnelSession | None:
        """Return the current live session for a tunnel if one exists.

        Args:
            tunnel_id: Tunnel identifier.
            heartbeat_timeout_seconds: Allowed inactivity window.

        Returns:
            TunnelSession | None: Active live session or `None`.
        """
        async with self._registry_lock:
            active_session = self._session_by_tunnel_id.get(tunnel_id)

        if active_session is None:
            return None

        if active_session.is_stale(heartbeat_timeout_seconds):
            await self.unregister_current(
                active_session,
                close_code=1011,
                close_reason="Heartbeat timeout",
            )
            return None

        return active_session

    async def get_status_snapshot(
        self,
        public_tunnel_id: str,
        heartbeat_timeout_seconds: float,
    ) -> Mapping[str, object]:
        """Return a serializable registry status snapshot.

        Args:
            public_tunnel_id: The tunnel id used for public browser traffic.
            heartbeat_timeout_seconds: Allowed inactivity window.

        Returns:
            Mapping[str, object]: Registry status payload.
        """
        public_session = await self.get_active_session(
            public_tunnel_id,
            heartbeat_timeout_seconds=heartbeat_timeout_seconds,
        )
        async with self._registry_lock:
            active_tunnel_id_list = sorted(self._session_by_tunnel_id.keys())
        return {
            "active_tunnel_count": len(active_tunnel_id_list),
            "active_tunnel_ids": active_tunnel_id_list,
            "public_tunnel_id": public_tunnel_id,
            "public_tunnel_online": public_session is not None,
        }
