"""Stronghold API middleware: payload size limits."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.requests import Request


class PayloadSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests with Content-Length exceeding the configured limit.

    Returns 413 Payload Too Large for oversized requests.
    Also enforces limits on chunked transfer encoding by checking
    Transfer-Encoding header presence with no Content-Length.
    """

    def __init__(self, app: Any, max_bytes: int = 1_048_576) -> None:
        super().__init__(app)
        self._max_bytes = max_bytes

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[..., Any],
    ) -> Response:
        content_length = request.headers.get("content-length")
        transfer_encoding = request.headers.get("transfer-encoding", "")

        if content_length:
            try:
                length = int(content_length)
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": {"message": "Invalid Content-Length", "type": "request_error"}
                    },
                )
            if length < 0 or length > self._max_bytes:
                return JSONResponse(
                    status_code=413,
                    content={
                        "error": {
                            "message": f"Payload too large (max {self._max_bytes} bytes)",
                            "type": "payload_error",
                            "code": "PAYLOAD_TOO_LARGE",
                        }
                    },
                )
        elif "chunked" in transfer_encoding.lower() and request.method in ("POST", "PUT", "PATCH"):
            # Chunked requests without Content-Length: read body with limit
            body = await request.body()
            if len(body) > self._max_bytes:
                return JSONResponse(
                    status_code=413,
                    content={
                        "error": {
                            "message": f"Payload too large (max {self._max_bytes} bytes)",
                            "type": "payload_error",
                            "code": "PAYLOAD_TOO_LARGE",
                        }
                    },
                )

        result: Response = await call_next(request)
        return result
