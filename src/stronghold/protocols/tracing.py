"""Tracing protocols: backend, trace, span."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from types import TracebackType


@runtime_checkable
class Span(Protocol):
    """A single span within a trace."""

    def __enter__(self) -> Span: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None: ...
    def set_input(self, data: Any) -> Span: ...
    def set_output(self, data: Any) -> Span: ...
    def set_usage(
        self,
        input_tokens: int = 0,
        output_tokens: int = 0,
        model: str = "",
    ) -> Span: ...


@runtime_checkable
class Trace(Protocol):
    """A request-level trace containing spans."""

    @property
    def trace_id(self) -> str: ...

    def span(self, name: str) -> Span: ...
    def score(self, name: str, value: float, comment: str = "") -> None: ...
    def update(self, metadata: dict[str, Any]) -> None: ...
    def end(self) -> None: ...


@runtime_checkable
class TracingBackend(Protocol):
    """Creates traces. Backed by Arize, Phoenix, or noop."""

    def create_trace(
        self,
        *,
        user_id: str = "",
        session_id: str = "",
        name: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> Trace:
        """Create a new trace for a request."""
        ...
