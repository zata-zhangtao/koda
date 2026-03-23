"""Typed tunnel message models shared by the gateway and the agent."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter


class TunnelMessageType(str, Enum):
    """Supported tunnel message types."""

    HTTP_REQUEST = "http_request"
    HTTP_RESPONSE = "http_response"
    HEARTBEAT = "heartbeat"
    HEARTBEAT_ACK = "heartbeat_ack"


class TunnelHeaderEntry(BaseModel):
    """Serializable HTTP header entry."""

    name: str
    value: str


class GatewayHttpRequestMessage(BaseModel):
    """HTTP request envelope sent from the gateway to the local agent."""

    message_type: Literal[TunnelMessageType.HTTP_REQUEST] = (
        TunnelMessageType.HTTP_REQUEST
    )
    request_id: str
    method: str
    path: str
    query_string: str
    headers: list[TunnelHeaderEntry] = Field(default_factory=list)
    body_base64: str


class AgentHttpResponseMessage(BaseModel):
    """HTTP response envelope sent from the local agent back to the gateway."""

    message_type: Literal[TunnelMessageType.HTTP_RESPONSE] = (
        TunnelMessageType.HTTP_RESPONSE
    )
    request_id: str
    status_code: int
    headers: list[TunnelHeaderEntry] = Field(default_factory=list)
    body_base64: str


class TunnelHeartbeatMessage(BaseModel):
    """Heartbeat event emitted by the local agent."""

    message_type: Literal[TunnelMessageType.HEARTBEAT] = TunnelMessageType.HEARTBEAT
    tunnel_id: str
    agent_instance_id: str
    sent_at_iso: str


class TunnelHeartbeatAckMessage(BaseModel):
    """Heartbeat acknowledgement emitted by the gateway."""

    message_type: Literal[TunnelMessageType.HEARTBEAT_ACK] = (
        TunnelMessageType.HEARTBEAT_ACK
    )
    tunnel_id: str
    received_at_iso: str


TunnelInboundMessage = Annotated[
    GatewayHttpRequestMessage
    | AgentHttpResponseMessage
    | TunnelHeartbeatMessage
    | TunnelHeartbeatAckMessage,
    Field(discriminator="message_type"),
]

_TUNNEL_MESSAGE_ADAPTER = TypeAdapter(TunnelInboundMessage)


def parse_tunnel_message(raw_payload: dict[str, Any]) -> TunnelInboundMessage:
    """Parse an inbound tunnel message payload.

    Args:
        raw_payload: Raw JSON-decoded payload.

    Returns:
        TunnelInboundMessage: Parsed typed message.
    """
    return _TUNNEL_MESSAGE_ADAPTER.validate_python(raw_payload)
