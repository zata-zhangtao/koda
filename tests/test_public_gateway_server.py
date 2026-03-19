"""Tests for the public gateway server."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from forwarding_service.server.app import TUNNEL_OFFLINE_TEXT, create_application
from forwarding_service.server.config import GatewayServerConfig
from forwarding_service.shared.http import decode_body_text, encode_body_bytes
from forwarding_service.shared.messages import (
    AgentHttpResponseMessage,
    TunnelHeaderEntry,
    TunnelHeartbeatMessage,
)


def _build_gateway_test_client(
    gateway_config: GatewayServerConfig | None = None,
) -> TestClient:
    """Build a test client for the gateway app.

    Args:
        gateway_config: Optional override config.

    Returns:
        TestClient: Gateway test client.
    """
    resolved_gateway_config = gateway_config or GatewayServerConfig(
        public_tunnel_id="demo-tunnel",
        tunnel_shared_token="secret-token",
        request_timeout_seconds=1.0,
        heartbeat_timeout_seconds=5.0,
        host="127.0.0.1",
        port=9000,
        log_level="INFO",
    )
    return TestClient(create_application(resolved_gateway_config))


def test_gateway_rejects_invalid_tunnel_token() -> None:
    """A wrong shared token must not establish an active tunnel."""
    test_client = _build_gateway_test_client()

    with pytest.raises(WebSocketDisconnect) as disconnect_info:
        with test_client.websocket_connect(
            "/ws/tunnels/demo-tunnel",
            headers={"x-koda-tunnel-token": "wrong-token"},
        ):
            pass

    assert disconnect_info.value.code == 4401


def test_gateway_returns_stable_503_when_tunnel_is_offline() -> None:
    """Browser requests should get a stable offline response without an active tunnel."""
    test_client = _build_gateway_test_client()

    response = test_client.get("/health")

    assert response.status_code == 503
    assert response.text == TUNNEL_OFFLINE_TEXT


def test_gateway_acknowledges_agent_heartbeat() -> None:
    """The gateway should update liveness on heartbeat and send an acknowledgement."""
    test_client = _build_gateway_test_client()

    with test_client.websocket_connect(
        "/ws/tunnels/demo-tunnel",
        headers={"x-koda-tunnel-token": "secret-token"},
    ) as websocket_connection:
        websocket_connection.send_json(
            TunnelHeartbeatMessage(
                tunnel_id="demo-tunnel",
                agent_instance_id="agent-1",
                sent_at_iso="2026-03-19T00:00:00+00:00",
            ).model_dump(mode="json")
        )

        heartbeat_ack_payload = websocket_connection.receive_json()

    assert heartbeat_ack_payload["message_type"] == "heartbeat_ack"
    assert heartbeat_ack_payload["tunnel_id"] == "demo-tunnel"


def test_gateway_forwards_http_request_to_active_tunnel() -> None:
    """The gateway should preserve core HTTP request/response fields over the tunnel."""
    gateway_application = create_application(
        GatewayServerConfig(
            public_tunnel_id="demo-tunnel",
            tunnel_shared_token="secret-token",
            request_timeout_seconds=1.0,
            heartbeat_timeout_seconds=5.0,
            host="127.0.0.1",
            port=9000,
            log_level="INFO",
        )
    )
    captured_payload_container: dict[str, object] = {}
    fake_response_message = AgentHttpResponseMessage(
        request_id="unused",
        status_code=201,
        headers=[],
        body_base64=encode_body_bytes(b"forwarded-response"),
    )

    class _FakeSession:
        async def wait_for_response(
            self,
            outbound_request_message,
            request_id: str,
            timeout_seconds: float,
        ) -> AgentHttpResponseMessage:
            captured_payload_container["request_payload"] = outbound_request_message.model_dump(
                mode="json"
            )
            fake_response_message.request_id = request_id
            assert timeout_seconds == 1.0
            return fake_response_message

    async def fake_get_active_session(tunnel_id: str, heartbeat_timeout_seconds: float):
        assert tunnel_id == "demo-tunnel"
        assert heartbeat_timeout_seconds == 5.0
        return _FakeSession()

    gateway_application.state.tunnel_session_registry.get_active_session = (
        fake_get_active_session
    )
    test_client = TestClient(gateway_application)

    response = test_client.post(
        "/api/echo?hello=world",
        headers={"x-koda-custom": "demo-header"},
        content=b"request-body",
    )

    assert response.status_code == 201
    assert response.content == b"forwarded-response"

    request_payload = captured_payload_container["request_payload"]
    request_header_dict = {
        header_entry["name"].lower(): header_entry["value"]
        for header_entry in request_payload["headers"]  # type: ignore[index]
    }
    assert request_payload["method"] == "POST"  # type: ignore[index]
    assert request_payload["path"] == "/api/echo"  # type: ignore[index]
    assert request_payload["query_string"] == "hello=world"  # type: ignore[index]
    assert request_header_dict["x-koda-custom"] == "demo-header"
    assert decode_body_text(request_payload["body_base64"]) == b"request-body"  # type: ignore[index]


def test_gateway_filters_framework_owned_response_headers() -> None:
    """The gateway must not replay entity headers that FastAPI regenerates."""
    gateway_application = create_application(
        GatewayServerConfig(
            public_tunnel_id="demo-tunnel",
            tunnel_shared_token="secret-token",
            request_timeout_seconds=1.0,
            heartbeat_timeout_seconds=5.0,
            host="127.0.0.1",
            port=9000,
            log_level="INFO",
        )
    )
    fake_response_body = b"forwarded-response"
    fake_response_message = AgentHttpResponseMessage(
        request_id="unused",
        status_code=200,
        headers=[
            TunnelHeaderEntry(name="content-length", value="999"),
            TunnelHeaderEntry(name="content-type", value="text/plain; charset=utf-8"),
            TunnelHeaderEntry(name="x-koda-demo", value="from-agent"),
        ],
        body_base64=encode_body_bytes(fake_response_body),
    )

    class _FakeSession:
        async def wait_for_response(
            self,
            outbound_request_message,
            request_id: str,
            timeout_seconds: float,
        ) -> AgentHttpResponseMessage:
            del outbound_request_message
            del request_id
            del timeout_seconds
            return fake_response_message

    async def fake_get_active_session(tunnel_id: str, heartbeat_timeout_seconds: float):
        del tunnel_id
        del heartbeat_timeout_seconds
        return _FakeSession()

    gateway_application.state.tunnel_session_registry.get_active_session = (
        fake_get_active_session
    )
    test_client = TestClient(gateway_application)

    response = test_client.get("/api/demo")

    assert response.status_code == 200
    assert response.content == fake_response_body
    assert response.headers.get_list("content-length") == [str(len(fake_response_body))]
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.headers["x-koda-demo"] == "from-agent"


def test_gateway_replaces_existing_tunnel_session_deterministically() -> None:
    """A newer connection for the same tunnel id should replace the old one."""
    gateway_config = GatewayServerConfig(
        public_tunnel_id="demo-tunnel",
        tunnel_shared_token="secret-token",
        request_timeout_seconds=1.0,
        heartbeat_timeout_seconds=5.0,
        host="127.0.0.1",
        port=9000,
        log_level="INFO",
    )
    test_client = _build_gateway_test_client(gateway_config)

    with test_client.websocket_connect(
        "/ws/tunnels/demo-tunnel",
        headers={"x-koda-tunnel-token": "secret-token"},
    ) as first_websocket:
        with test_client.websocket_connect(
            "/ws/tunnels/demo-tunnel",
            headers={"x-koda-tunnel-token": "secret-token"},
        ):
            with pytest.raises(WebSocketDisconnect):
                first_websocket.receive_json()

    health_response = test_client.get("/_gateway/health")
    assert health_response.status_code == 200
    assert health_response.json()["public_tunnel_online"] is False


@pytest.mark.parametrize(
    ("invalid_shared_token", "use_missing_env"),
    [
        ("", False),
        ("change-me", False),
        ("replace-with-a-long-random-secret", False),
        ("replace-with-the-same-long-random-secret", False),
        ("", True),
    ],
)
def test_gateway_config_from_env_rejects_missing_or_placeholder_shared_token(
    monkeypatch: pytest.MonkeyPatch,
    invalid_shared_token: str,
    use_missing_env: bool,
) -> None:
    """Gateway startup must fail fast on blank or placeholder shared tokens."""
    monkeypatch.setenv("KODA_TUNNEL_ID", "demo-tunnel")
    if use_missing_env:
        monkeypatch.delenv("KODA_TUNNEL_SHARED_TOKEN", raising=False)
    else:
        monkeypatch.setenv("KODA_TUNNEL_SHARED_TOKEN", invalid_shared_token)

    with pytest.raises(ValueError, match="KODA_TUNNEL_SHARED_TOKEN"):
        GatewayServerConfig.from_env()
