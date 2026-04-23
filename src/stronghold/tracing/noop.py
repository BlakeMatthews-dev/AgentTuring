"""No-op tracing backend for tests and standalone mode."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from types import TracebackType


class NoopSpan:
    """No-op span."""

    def __enter__(self) -> NoopSpan:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        return None

    def set_input(self, data: Any) -> NoopSpan:
        return self

    def set_output(self, data: Any) -> NoopSpan:
        return self

    def set_usage(
        self,
        input_tokens: int = 0,
        output_tokens: int = 0,
        model: str = "",
    ) -> NoopSpan:
        return self


class NoopTrace:
    """No-op trace."""

    @property
    def trace_id(self) -> str:
        return "noop-trace"

    def span(self, name: str) -> NoopSpan:
        return NoopSpan()

    def score(self, name: str, value: float, comment: str = "") -> None:
        pass

    def update(self, metadata: dict[str, Any]) -> None:
        pass

    def end(self) -> None:
        pass


class NoopTracingBackend:
    """No-op tracing backend."""

    def create_trace(
        self,
        *,
        user_id: str = "",
        session_id: str = "",
        name: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> NoopTrace:
        return NoopTrace()

    def shutdown(self) -> None:
        pass
