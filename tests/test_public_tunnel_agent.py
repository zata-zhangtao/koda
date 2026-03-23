"""Tests for the local public tunnel agent."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx

from forwarding_service.agent.config import (
    TunnelAgentConfig,
    build_tunnel_websocket_url,
)
from forwarding_service.agent.http_bridge import UpstreamHttpBridge
from forwarding_service.agent.main import TunnelAgent
from forwarding_service.shared.http import decode_body_text, encode_body_bytes
from forwarding_service.shared.messages import (
    AgentHttpResponseMessage,
    GatewayHttpRequestMessage,
    TunnelHeartbeatAckMessage,
)


@dataclass
class _FakeAgentWebSocket:
    """Minimal fake WebSocket for agent-loop tests."""

    inbound_message_text_list: list[str]

    def __post_init__(self) -> None:
        """Initialize mutable state after dataclass construction."""
        self.sent_message_text_list: list[str] = []
        self.closed = False

    async def send(self, data: str) -> None:
        """Record one outbound frame."""
        self.sent_message_text_list.append(data)

    async def recv(self) -> str:
        """Return the next inbound frame or block long enough to time out."""
        if self.inbound_message_text_list:
            return self.inbound_message_text_list.pop(0)
        await asyncio.sleep(1)
        return ""

    async def close(self) -> None:
        """Mark the fake connection as closed."""
        self.closed = True


class _FakeConnectContext:
    """Async context manager wrapper around a fake WebSocket."""

    def __init__(self, fake_websocket: _FakeAgentWebSocket) -> None:
        """Initialize the wrapper.

        Args:
            fake_websocket: Fake WebSocket instance.
        """
        self._fake_websocket = fake_websocket

    async def __aenter__(self) -> _FakeAgentWebSocket:
        """Return the fake connection."""
        return self._fake_websocket

    async def __aexit__(self, exc_type, exc, traceback) -> bool:
        """Close the fake connection on context exit."""
        await self._fake_websocket.close()
        return False


def test_build_tunnel_websocket_url_normalizes_http_and_https() -> None:
    """HTTP(S) server URLs should normalize into WS(S) registration URLs."""
    assert build_tunnel_websocket_url("http://gateway.example.com", "alpha") == (
        "ws://gateway.example.com/ws/tunnels/alpha"
    )
    assert build_tunnel_websocket_url("https://gateway.example.com/base", "beta") == (
        "wss://gateway.example.com/base/ws/tunnels/beta"
    )


def test_tunnel_agent_config_from_env_rejects_placeholder_shared_token(
    monkeypatch,
) -> None:
    """Agent startup should also refuse example placeholder shared tokens."""
    monkeypatch.setenv("KODA_TUNNEL_ID", "demo-tunnel")
    monkeypatch.setenv(
        "KODA_TUNNEL_SHARED_TOKEN",
        "replace-with-the-same-long-random-secret",
    )

    try:
        TunnelAgentConfig.from_env()
    except ValueError as config_error:
        assert "KODA_TUNNEL_SHARED_TOKEN" in str(config_error)
    else:
        raise AssertionError(
            "Expected TunnelAgentConfig.from_env() to reject placeholder secrets"
        )


def test_upstream_http_bridge_forwards_method_path_query_headers_and_body(
    monkeypatch,
) -> None:
    """The HTTP bridge should map a gateway envelope into one upstream HTTP request."""
    captured_request_kwargs: dict[str, object] = {}
    upstream_http_bridge = UpstreamHttpBridge(
        upstream_base_url="http://127.0.0.1:8000",
        request_timeout_seconds=1.0,
    )

    async def fake_request(**request_kwargs):
        captured_request_kwargs.update(request_kwargs)
        return httpx.Response(
            status_code=202,
            headers={"x-upstream": "ok"},
            content=b"upstream-response",
        )

    monkeypatch.setattr(upstream_http_bridge._http_client, "request", fake_request)

    async def run_bridge_test() -> AgentHttpResponseMessage:
        response_message = await upstream_http_bridge.forward_request(
            GatewayHttpRequestMessage(
                request_id="req-1",
                method="POST",
                path="/api/echo",
                query_string="hello=world",
                headers=[],
                body_base64=encode_body_bytes(b"bridge-body"),
            )
        )
        await upstream_http_bridge.close()
        return response_message

    response_message = asyncio.run(run_bridge_test())

    assert captured_request_kwargs["method"] == "POST"
    assert (
        captured_request_kwargs["url"] == "http://127.0.0.1:8000/api/echo?hello=world"
    )
    assert captured_request_kwargs["content"] == b"bridge-body"
    assert response_message.status_code == 202
    assert decode_body_text(response_message.body_base64) == b"upstream-response"


def test_tunnel_agent_reconnects_and_sends_heartbeat() -> None:
    """The agent should retry failed connections and emit heartbeat frames."""
    fake_websocket = _FakeAgentWebSocket(
        inbound_message_text_list=[
            TunnelHeartbeatAckMessage(
                tunnel_id="demo-tunnel",
                received_at_iso="2026-03-19T00:00:00+00:00",
            ).model_dump_json()
        ]
    )
    connect_attempt_state = {"count": 0, "call_kwargs": []}
    tunnel_agent = TunnelAgent(
        TunnelAgentConfig(
            public_base_url="https://koda.example.com",
            tunnel_server_url="https://gateway.example.com",
            tunnel_id="demo-tunnel",
            shared_token="secret-token",
            upstream_url="http://127.0.0.1:8000",
            heartbeat_interval_seconds=0.01,
            reconnect_delay_seconds=0.0,
            max_reconnect_delay_seconds=0.0,
            request_timeout_seconds=0.01,
            open_timeout_seconds=0.01,
            log_level="INFO",
        )
    )

    def fake_connect_callable(*args, **kwargs):
        connect_attempt_state["count"] += 1
        connect_attempt_state["call_kwargs"].append(kwargs)
        if connect_attempt_state["count"] == 1:
            raise RuntimeError("first connection failed")
        return _FakeConnectContext(fake_websocket)

    async def run_agent_test() -> None:
        await tunnel_agent.run_forever(
            connect_callable=fake_connect_callable,
            max_connection_attempts=2,
        )
        await tunnel_agent.close()

    asyncio.run(run_agent_test())

    assert connect_attempt_state["count"] == 2
    assert connect_attempt_state["call_kwargs"][1]["additional_headers"] == {
        "x-koda-tunnel-token": "secret-token",
    }
    assert any(
        '"message_type":"heartbeat"' in outbound_message_text
        for outbound_message_text in fake_websocket.sent_message_text_list
    )


def test_tunnel_agent_returns_stable_502_when_upstream_fails(monkeypatch) -> None:
    """The agent should not leak local network details when the upstream fails."""
    tunnel_agent = TunnelAgent(
        TunnelAgentConfig(
            public_base_url=None,
            tunnel_server_url="https://gateway.example.com",
            tunnel_id="demo-tunnel",
            shared_token="secret-token",
            upstream_url="http://127.0.0.1:8000",
            heartbeat_interval_seconds=1.0,
            reconnect_delay_seconds=0.0,
            max_reconnect_delay_seconds=0.0,
            request_timeout_seconds=1.0,
            open_timeout_seconds=1.0,
            log_level="INFO",
        )
    )

    async def fake_forward_request(
        request_message: GatewayHttpRequestMessage,
    ) -> AgentHttpResponseMessage:
        del request_message
        raise RuntimeError("dial tcp 127.0.0.1:8000: connection refused")

    monkeypatch.setattr(
        tunnel_agent._upstream_http_bridge,
        "forward_request",
        fake_forward_request,
    )

    async def run_agent_error_test() -> AgentHttpResponseMessage:
        response_message = await tunnel_agent._handle_http_request_message(
            GatewayHttpRequestMessage(
                request_id="req-1",
                method="GET",
                path="/health",
                query_string="",
                headers=[],
                body_base64="",
            )
        )
        await tunnel_agent.close()
        return response_message

    response_message = asyncio.run(run_agent_error_test())

    assert response_message.status_code == 502
    assert decode_body_text(response_message.body_base64) == b"Upstream Request Failed"
