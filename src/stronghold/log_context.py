"""LoggerAdapter for attaching ``run_id`` to log records in a workflow scope.

Used at the top of long-running async workflows (builders runs, mission runs)
so every log line emitted during that workflow inherits the ``run_id`` without
manual interpolation. The :class:`stronghold.log_config.RunIdFilter` then
backstops any record emitted outside such a scope by injecting ``run_id="-"``.

See ARCHITECTURE.md §7.4 for the full design.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import MutableMapping

__all__ = ["RunLoggerAdapter", "get_run_logger"]


class RunLoggerAdapter(logging.LoggerAdapter):  # type: ignore[type-arg]
    """LoggerAdapter that injects ``run_id`` into every record's ``extra``.

    Construction:

        adapter = RunLoggerAdapter(logging.getLogger("stronghold.builders.tdd"), run_id="run-abc")
        adapter.info("criterion %d/%d done", 1, 5)
        # Logged record carries record.run_id == "run-abc"

    The adapter merges its stored ``run_id`` into any caller-supplied ``extra``
    dict, so callers can still pass extra fields and they'll be combined with
    the workflow's ``run_id``.
    """

    def __init__(self, logger: logging.Logger, run_id: str) -> None:
        super().__init__(logger, {"run_id": run_id})

    def process(
        self, msg: Any, kwargs: MutableMapping[str, Any]
    ) -> tuple[Any, MutableMapping[str, Any]]:
        extra = kwargs.get("extra")
        if extra is None:
            extra = {}
            kwargs["extra"] = extra
        # Inject run_id without overriding caller-supplied fields
        extra.setdefault("run_id", self.extra["run_id"] if self.extra else "-")
        return msg, kwargs


def get_run_logger(name: str, run_id: str) -> RunLoggerAdapter:
    """Convenience: return a :class:`RunLoggerAdapter` for the named logger."""
    return RunLoggerAdapter(logging.getLogger(name), run_id)
