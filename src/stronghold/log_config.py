"""Centralized logging configuration for the Stronghold API process.

The FastAPI ``lifespan`` hook calls :func:`configure_logging` to set up
structured loggers with ``run_id`` propagation via :class:`RunIdFilter`.

See ARCHITECTURE.md §7.4 for the full design.
"""

from __future__ import annotations

import logging
import logging.config
from typing import Any

__all__ = ["LOG_CONFIG", "RunIdFilter", "configure_logging"]

_CONFIGURED = False


class RunIdFilter(logging.Filter):
    """Inject ``run_id="-"`` on records that don't have one.

    Required so the format string never raises ``KeyError`` on records emitted
    outside a workflow scope (libraries, framework code, ad-hoc loggers).
    Records that already carry a ``run_id`` (set via :class:`RunLoggerAdapter`
    or an explicit ``extra=`` kwarg) are left alone.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "run_id"):
            record.run_id = "-"
        return True


LOG_CONFIG: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "run_id": {"()": RunIdFilter},
    },
    "formatters": {
        "default": {
            "format": ("%(asctime)s %(levelname)-8s %(name)s [run_id=%(run_id)s] %(message)s"),
            "datefmt": "%Y-%m-%dT%H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "default",
            "filters": ["run_id"],
        },
    },
    "root": {"level": "INFO", "handlers": ["console"]},
    "loggers": {
        "stronghold": {"level": "INFO", "propagate": True},
        "stronghold.builders.tdd": {"level": "INFO", "propagate": True},
        "stronghold.builders.auditor": {"level": "INFO", "propagate": True},
        "stronghold.builders.onboarding": {"level": "INFO", "propagate": True},
        "stronghold.builders.outer": {"level": "INFO", "propagate": True},
        "stronghold.builders.workflow": {"level": "INFO", "propagate": True},
        # Quiet noisy upstream libs
        "httpx": {"level": "WARNING"},
        "httpcore": {"level": "WARNING"},
        "uvicorn.access": {"level": "WARNING"},
    },
}


def configure_logging() -> None:
    """Apply :data:`LOG_CONFIG` idempotently. Safe to call multiple times."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    logging.config.dictConfig(LOG_CONFIG)
    _CONFIGURED = True
