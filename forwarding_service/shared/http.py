"""HTTP serialization helpers for the public tunnel."""

from __future__ import annotations

import base64
from collections.abc import Iterable

from forwarding_service.shared.messages import TunnelHeaderEntry

HOP_BY_HOP_HEADER_NAME_SET = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}

# Headers that must be stripped when forwarding to the local upstream.
# "host" is set automatically by httpx from the target URL; forwarding the
# original public-domain Host header causes Starlette to build redirect
# Location values that point at the public domain instead of the upstream.
UPSTREAM_REQUEST_STRIP_HEADER_NAME_SET = HOP_BY_HOP_HEADER_NAME_SET | {"host"}

FRAMEWORK_OWNED_RESPONSE_HEADER_NAME_SET = {
    "content-length",
}


def encode_body_bytes(body_bytes: bytes) -> str:
    """Encode raw bytes into base64 text.

    Args:
        body_bytes (bytes): Raw body bytes.

    Returns:
        str: Base64-encoded payload.
    """
    return base64.b64encode(body_bytes).decode("ascii")


def decode_body_text(body_base64_text: str) -> bytes:
    """Decode base64 text into raw bytes.

    Args:
        body_base64_text (str): Base64 payload text.

    Returns:
        bytes: Decoded body bytes.
    """
    if body_base64_text == "":
        return b""
    return base64.b64decode(body_base64_text.encode("ascii"))


def build_header_entry_list(
    raw_header_pair_iterable: Iterable[tuple[str, str]],
) -> list[TunnelHeaderEntry]:
    """Normalize raw headers into serializable header entries.

    Args:
        raw_header_pair_iterable: Raw header `(name, value)` pairs.

    Returns:
        list[TunnelHeaderEntry]: Filtered header entries without hop-by-hop headers.
    """
    filtered_header_entry_list: list[TunnelHeaderEntry] = []
    for header_name, header_value in raw_header_pair_iterable:
        if header_name.lower() in HOP_BY_HOP_HEADER_NAME_SET:
            continue
        filtered_header_entry_list.append(
            TunnelHeaderEntry(name=header_name, value=header_value)
        )
    return filtered_header_entry_list


def build_header_tuple_list(
    header_entry_list: Iterable[TunnelHeaderEntry],
) -> list[tuple[str, str]]:
    """Convert serializable header entries into upstream-safe `(name, value)` tuples.

    Strips hop-by-hop headers and the ``host`` header so that the upstream
    HTTP client can set the correct ``Host`` for the local target URL.

    Args:
        header_entry_list: Serialized header entries.

    Returns:
        list[tuple[str, str]]: Filtered header tuples safe to forward upstream.
    """
    return [
        (header_entry.name, header_entry.value)
        for header_entry in header_entry_list
        if header_entry.name.lower() not in UPSTREAM_REQUEST_STRIP_HEADER_NAME_SET
    ]


def build_forwarded_response_header_tuple_list(
    header_entry_list: Iterable[TunnelHeaderEntry],
) -> list[tuple[str, str]]:
    """Build response headers that are safe to replay to the browser.

    Args:
        header_entry_list: Serialized upstream response headers.

    Returns:
        list[tuple[str, str]]: Response headers excluding hop-by-hop and
            framework-owned entity headers.
    """
    return [
        (header_entry.name, header_entry.value)
        for header_entry in header_entry_list
        if header_entry.name.lower() not in HOP_BY_HOP_HEADER_NAME_SET
        and header_entry.name.lower() not in FRAMEWORK_OWNED_RESPONSE_HEADER_NAME_SET
    ]
