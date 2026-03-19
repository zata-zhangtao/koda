"""HTTP bridge that forwards tunnel requests to the local DSL upstream."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

import httpx

from forwarding_service.shared.http import (
    build_header_entry_list,
    build_header_tuple_list,
    decode_body_text,
    encode_body_bytes,
)
from forwarding_service.shared.messages import (
    AgentHttpResponseMessage,
    GatewayHttpRequestMessage,
)


class UpstreamHttpBridge:
    """Bridge that executes proxied HTTP requests against the local upstream."""

    def __init__(self, upstream_base_url: str, request_timeout_seconds: float) -> None:
        """Initialize the bridge.

        Args:
            upstream_base_url: Local upstream base URL.
            request_timeout_seconds: Per-request timeout.
        """
        self._upstream_base_url = upstream_base_url.rstrip("/")
        self._http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(request_timeout_seconds),
            follow_redirects=False,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http_client.aclose()

    async def forward_request(
        self,
        request_message: GatewayHttpRequestMessage,
    ) -> AgentHttpResponseMessage:
        """Forward one gateway request to the configured local upstream.

        Args:
            request_message: Gateway request envelope.

        Returns:
            AgentHttpResponseMessage: Serialized upstream response envelope.
        """
        upstream_request_url = self._build_upstream_request_url(
            request_message.path,
            request_message.query_string,
        )
        upstream_response = await self._http_client.request(
            method=request_message.method,
            url=upstream_request_url,
            headers=build_header_tuple_list(request_message.headers),
            content=decode_body_text(request_message.body_base64),
        )
        return AgentHttpResponseMessage(
            request_id=request_message.request_id,
            status_code=upstream_response.status_code,
            headers=build_header_entry_list(upstream_response.headers.items()),
            body_base64=encode_body_bytes(upstream_response.content),
        )

    def _build_upstream_request_url(self, request_path: str, query_string: str) -> str:
        """Build the concrete local upstream request URL.

        Args:
            request_path: HTTP path from the browser request.
            query_string: Raw query string.

        Returns:
            str: Absolute upstream URL.
        """
        parsed_base_url = urlsplit(self._upstream_base_url)
        normalized_path = request_path if request_path.startswith("/") else f"/{request_path}"
        return urlunsplit(
            (
                parsed_base_url.scheme,
                parsed_base_url.netloc,
                normalized_path,
                query_string,
                "",
            )
        )
