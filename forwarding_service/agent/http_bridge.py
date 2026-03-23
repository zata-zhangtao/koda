"""HTTP bridge that forwards tunnel requests to the local DSL upstream."""

from __future__ import annotations

from collections.abc import Iterable
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
        rewritten_response_headers = self._rewrite_upstream_location_headers(
            upstream_response.headers.items()
        )
        return AgentHttpResponseMessage(
            request_id=request_message.request_id,
            status_code=upstream_response.status_code,
            headers=build_header_entry_list(rewritten_response_headers),
            body_base64=encode_body_bytes(upstream_response.content),
        )

    def _rewrite_upstream_location_headers(
        self,
        raw_header_pairs: Iterable[tuple[str, str]],
    ) -> list[tuple[str, str]]:
        """Rewrite absolute Location headers that point at the local upstream.

        Starlette builds redirect Location values using the request Host header.
        Because the gateway strips the Host before forwarding, the Location may
        still contain the upstream base URL (e.g. ``http://127.0.0.1:8000/foo``).
        Convert these to root-relative paths so the browser follows them on the
        public domain instead of trying to contact the internal address.

        Args:
            raw_header_pairs: Raw ``(name, value)`` pairs from the upstream response.

        Returns:
            list[tuple[str, str]]: Header pairs with upstream-origin Location
                values replaced by their root-relative equivalents.
        """
        rewritten_header_pair_list: list[tuple[str, str]] = []
        for header_name, header_value in raw_header_pairs:
            if header_name.lower() == "location" and header_value.startswith(
                self._upstream_base_url
            ):
                relative_location_path = header_value[len(self._upstream_base_url) :]
                if not relative_location_path.startswith("/"):
                    relative_location_path = "/" + relative_location_path
                header_value = relative_location_path
            rewritten_header_pair_list.append((header_name, header_value))
        return rewritten_header_pair_list

    def _build_upstream_request_url(self, request_path: str, query_string: str) -> str:
        """Build the concrete local upstream request URL.

        Args:
            request_path: HTTP path from the browser request.
            query_string: Raw query string.

        Returns:
            str: Absolute upstream URL.
        """
        parsed_base_url = urlsplit(self._upstream_base_url)
        normalized_path = (
            request_path if request_path.startswith("/") else f"/{request_path}"
        )
        return urlunsplit(
            (
                parsed_base_url.scheme,
                parsed_base_url.netloc,
                normalized_path,
                query_string,
                "",
            )
        )
