"""Phoenix tracing backend: sends traces to Arize Phoenix via OTLP.

Key: child spans must be created within the parent span's context
so OTEL can link them into a single trace tree. Without this,
every span appears as a separate orphaned trace in Phoenix.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from stronghold.protocols.tracing import Span, Trace

from opentelemetry import context as otel_context
from opentelemetry import trace as otel_trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

logger = logging.getLogger("stronghold.tracing")


class PhoenixSpan:
    """A real OTEL span wrapping the Phoenix trace."""

    def __init__(self, otel_span: otel_trace.Span, token: object | None = None) -> None:
        self._span = otel_span
        self._token = token

    def __enter__(self) -> Span:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        if exc_type is not None:
            self._span.set_attribute("error", True)
            self._span.set_attribute("error.type", exc_type.__name__)
            self._span.set_attribute("error.message", str(exc_val)[:500])
            self._span.record_exception(exc_val)  # type: ignore[arg-type]
        self._span.end()
        if self._token is not None:
            otel_context.detach(self._token)  # type: ignore[arg-type]

    def set_input(self, data: Any) -> Span:
        self._span.set_attribute("input", str(data)[:1000])
        return self

    def set_output(self, data: Any) -> Span:
        self._span.set_attribute("output", str(data)[:1000])
        return self

    def set_usage(
        self,
        input_tokens: int = 0,
        output_tokens: int = 0,
        model: str = "",
    ) -> Span:
        self._span.set_attribute("llm.token_count.prompt", input_tokens)
        self._span.set_attribute("llm.token_count.completion", output_tokens)
        if model:
            self._span.set_attribute("llm.model_name", model)
        return self


class PhoenixTrace:
    """A real trace that sends spans to Phoenix.

    The root span sets the trace context. All child spans created via
    .span() are nested under the root by attaching the root's context.
    """

    def __init__(self, tracer: otel_trace.Tracer, name: str, attributes: dict[str, str]) -> None:
        self._tracer = tracer
        self._trace_id = str(uuid.uuid4())[:16]
        self._root_span = tracer.start_span(name, attributes=attributes)
        # Activate the root span context so children are nested
        self._root_ctx = otel_trace.set_span_in_context(self._root_span)
        self._root_token = otel_context.attach(self._root_ctx)
        self._scores: list[tuple[str, float, str]] = []

    @property
    def trace_id(self) -> str:
        return self._trace_id

    def span(self, name: str) -> Span:
        # Start child span within the root's context — this is critical
        # for Phoenix to group them into a single trace tree.
        child_span = self._tracer.start_span(name, context=self._root_ctx)
        child_ctx = otel_trace.set_span_in_context(child_span)
        token = otel_context.attach(child_ctx)
        return PhoenixSpan(child_span, token)

    def score(self, name: str, value: float, comment: str = "") -> None:
        self._scores.append((name, value, comment))
        self._root_span.set_attribute(f"score.{name}", value)

    def update(self, metadata: dict[str, Any]) -> None:
        for k, v in metadata.items():
            self._root_span.set_attribute(f"metadata.{k}", str(v))

    def end(self) -> None:
        self._root_span.end()
        otel_context.detach(self._root_token)


class PhoenixTracingBackend:
    """Sends traces to Arize Phoenix via OTLP HTTP."""

    def __init__(self, endpoint: str = "http://phoenix:6006") -> None:
        resource = Resource.create({"service.name": "stronghold"})
        exporter = OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")
        provider = TracerProvider(resource=resource)
        processor = BatchSpanProcessor(
            exporter,
            max_export_batch_size=32,
            schedule_delay_millis=2000,
        )
        provider.add_span_processor(processor)
        otel_trace.set_tracer_provider(provider)
        self._tracer = otel_trace.get_tracer("stronghold")
        self._provider = provider
        logger.info("Phoenix tracing initialized → %s/v1/traces", endpoint)

    def create_trace(
        self,
        *,
        user_id: str = "",
        session_id: str = "",
        name: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> Trace:
        attributes: dict[str, str] = {"user.id": user_id, "session.id": session_id}
        if metadata:
            for k, v in metadata.items():
                attributes[f"metadata.{k}"] = str(v)
        return PhoenixTrace(self._tracer, name or "request", attributes)

    def flush(self) -> None:
        """Force-flush pending spans. Useful before shutdown."""
        self._provider.force_flush()

    def shutdown(self) -> None:
        """Shut down the tracer provider and stop background export threads."""
        self._provider.shutdown()
