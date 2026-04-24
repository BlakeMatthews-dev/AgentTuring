"""MCP server capability metadata.

Kept separate so transport layers (stdio, Streamable HTTP) share the same
identity declarations.
"""

from __future__ import annotations

from dataclasses import dataclass

SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2025-03-26"


@dataclass(frozen=True)
class ServerMetadata:
    name: str
    version: str
    protocol_version: str


def server_metadata() -> ServerMetadata:
    return ServerMetadata(
        name="stronghold",
        version=SERVER_VERSION,
        protocol_version=PROTOCOL_VERSION,
    )
