"""FastAPI gateway application for the public tunnel forwarding service."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from forwarding_service.server.config import GatewayServerConfig
from forwarding_service.server.session_registry import (
    TunnelSessionClosedError,
    TunnelSessionRegistry,
)
from forwarding_service.shared.http import (
    build_header_entry_list,
    build_forwarded_response_header_tuple_list,
    decode_body_text,
    encode_body_bytes,
)
from forwarding_service.shared.logging_utils import get_structured_logger, log_event
from forwarding_service.shared.messages import (
    AgentHttpResponseMessage,
    GatewayHttpRequestMessage,
    TunnelHeartbeatAckMessage,
    TunnelHeartbeatMessage,
    parse_tunnel_message,
)

TUNNEL_OFFLINE_TEXT = "Tunnel Offline"
UPSTREAM_FAILURE_TEXT = "Upstream Request Failed"


def create_application(
    gateway_config: GatewayServerConfig | None = None,
) -> FastAPI:
    """Create the gateway FastAPI application.

    Args:
        gateway_config: Optional explicit config for tests or embedding.

    Returns:
        FastAPI: Configured gateway application.
    """
    resolved_gateway_config = gateway_config or GatewayServerConfig.from_env()
    structured_logger = get_structured_logger(
        "koda.public_gateway",
        resolved_gateway_config.log_level,
    )
    tunnel_session_registry = TunnelSessionRegistry()

    application = FastAPI(
        title="Koda Public Gateway",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.state.gateway_config = resolved_gateway_config
    application.state.structured_logger = structured_logger
    application.state.tunnel_session_registry = tunnel_session_registry

    @application.get("/_gateway/health")
    async def gateway_health() -> JSONResponse:
        """Return internal gateway health and tunnel status."""
        status_payload = await tunnel_session_registry.get_status_snapshot(
            resolved_gateway_config.public_tunnel_id,
            heartbeat_timeout_seconds=resolved_gateway_config.heartbeat_timeout_seconds,
        )
        return JSONResponse(
            {
                "status": "healthy",
                "service": "public-gateway",
                **status_payload,
            }
        )

    @application.websocket("/ws/tunnels/{tunnel_id}")
    async def register_tunnel(websocket: WebSocket, tunnel_id: str) -> None:
        """Register one local agent connection over WebSocket.

        Args:
            websocket: Incoming WebSocket connection.
            tunnel_id: Tunnel identifier from the path.
        """
        provided_shared_token = (
            websocket.headers.get("x-koda-tunnel-token")
            or websocket.query_params.get("token")
            or ""
        )
        if provided_shared_token != resolved_gateway_config.tunnel_shared_token:
            log_event(
                structured_logger,
                "warning",
                "tunnel_auth_rejected",
                {"tunnel_id": tunnel_id},
            )
            await websocket.close(code=4401, reason="Invalid tunnel token")
            return

        await websocket.accept()
        (
            active_session,
            replaced_previous_session,
        ) = await tunnel_session_registry.register(
            tunnel_id=tunnel_id,
            websocket=websocket,
        )
        log_event(
            structured_logger,
            "info",
            "tunnel_connected",
            {
                "tunnel_id": tunnel_id,
                "session_id": active_session.session_id,
                "replaced_previous_session": replaced_previous_session,
            },
        )

        try:
            while True:
                raw_payload = await websocket.receive_json()
                parsed_message = parse_tunnel_message(raw_payload)
                active_session.mark_activity()

                if isinstance(parsed_message, TunnelHeartbeatMessage):
                    await active_session.send_message(
                        TunnelHeartbeatAckMessage(
                            tunnel_id=tunnel_id,
                            received_at_iso=datetime.now(UTC).isoformat(),
                        )
                    )
                    continue

                if isinstance(parsed_message, AgentHttpResponseMessage):
                    await active_session.resolve_response(parsed_message)
                    continue

                await websocket.close(code=4400, reason="Unexpected message type")
                return
        except WebSocketDisconnect as disconnect_error:
            log_event(
                structured_logger,
                "info",
                "tunnel_disconnected",
                {
                    "tunnel_id": tunnel_id,
                    "session_id": active_session.session_id,
                    "close_code": disconnect_error.code,
                },
            )
        finally:
            await tunnel_session_registry.unregister_current(
                active_session,
                close_reason="Tunnel websocket disconnected",
            )

    async def forward_public_request(request: Request) -> Response:
        """Forward one public HTTP request to the active tunnel session.

        Args:
            request: Incoming browser request.

        Returns:
            Response: Forwarded upstream response or a stable error response.
        """
        active_session = await tunnel_session_registry.get_active_session(
            resolved_gateway_config.public_tunnel_id,
            heartbeat_timeout_seconds=resolved_gateway_config.heartbeat_timeout_seconds,
        )
        if active_session is None:
            return PlainTextResponse(
                TUNNEL_OFFLINE_TEXT,
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        request_body_bytes = await request.body()
        request_id = uuid4().hex
        outbound_request_message = GatewayHttpRequestMessage(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            query_string=request.url.query,
            headers=build_header_entry_list(request.headers.items()),
            body_base64=encode_body_bytes(request_body_bytes),
        )

        try:
            inbound_response_message = await active_session.wait_for_response(
                outbound_request_message=outbound_request_message,
                request_id=request_id,
                timeout_seconds=resolved_gateway_config.request_timeout_seconds,
            )
        except (TimeoutError, TunnelSessionClosedError) as request_error:
            log_event(
                structured_logger,
                "warning",
                "gateway_request_failed",
                {
                    "path": request.url.path,
                    "method": request.method,
                    "request_id": request_id,
                    "error": str(request_error),
                },
            )
            return PlainTextResponse(
                TUNNEL_OFFLINE_TEXT,
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        forwarded_response = Response(
            content=decode_body_text(inbound_response_message.body_base64),
            status_code=inbound_response_message.status_code,
        )
        for header_name, header_value in build_forwarded_response_header_tuple_list(
            inbound_response_message.headers
        ):
            forwarded_response.headers.append(header_name, header_value)
        return forwarded_response

    @application.api_route(
        "/", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
    )
    async def forward_root_request(request: Request) -> Response:
        """Forward the application root path through the active tunnel."""
        return await forward_public_request(request)

    @application.api_route(
        "/{forward_path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
        include_in_schema=False,
    )
    async def forward_nested_request(forward_path: str, request: Request) -> Response:
        """Forward all other public paths through the active tunnel.

        Args:
            forward_path: Matched path parameter, unused except for routing.
            request: Incoming browser request.

        Returns:
            Response: Forwarded upstream response or a stable error response.
        """
        del forward_path
        return await forward_public_request(request)

    return application
