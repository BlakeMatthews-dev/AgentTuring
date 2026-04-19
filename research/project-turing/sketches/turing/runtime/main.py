"""Entry point. `python -m turing.runtime.main [flags]`.

Wires Repo + self_id + Motivation + Scheduler + DaydreamProducers +
ContradictionDetector + CoefficientTuner + Providers into a long-running
RealReactor tick loop.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
from typing import Any

from ..daydream import DaydreamProducer
from ..detectors.contradiction import ContradictionDetector
from ..motivation import Motivation
from ..repo import Repo
from ..scheduler import Scheduler
from ..self_identity import bootstrap_self_id
from ..tuning import CoefficientTuner
from .config import RuntimeConfig, load_config_from_env
from .instrumentation import setup_logging
from .providers.base import Provider
from .providers.fake import FakeProvider
from .providers.gemini import GeminiProvider
from .providers.zai import ZaiProvider
from .quota import FreeTierQuotaTracker
from .reactor import RealReactor
from .workload import WorkloadDriver, load_scenario


logger = logging.getLogger("turing.runtime.main")


# Per-provider quality weights. Tuner may propose updates at runtime.
DEFAULT_QUALITY_WEIGHTS: dict[str, float] = {
    "fake": 0.1,
    "gemini": 1.0,
    "openrouter": 0.7,
    "zai": 0.8,
}


def _resolve_scenario_path(scenario: str) -> str:
    """Locate a scenario YAML relative to the project-turing repo root."""
    from pathlib import Path

    direct = Path(scenario)
    if direct.is_file():
        return str(direct)

    # Try resolving relative to research/project-turing/scenarios/.
    anchor = Path(__file__).resolve()
    # __file__ = .../research/project-turing/sketches/turing/runtime/main.py
    project_root = anchor.parents[3]
    candidate = project_root / "scenarios" / f"{scenario}.yaml"
    if candidate.is_file():
        return str(candidate)
    raise FileNotFoundError(f"scenario not found: {scenario}")


def _build_providers(cfg: RuntimeConfig) -> dict[str, Provider]:
    providers: dict[str, Provider] = {}
    for name in cfg.provider_choice:
        if name == "fake":
            providers[name] = FakeProvider(name="fake")
        elif name == "gemini":
            if not cfg.gemini_api_key:
                raise ValueError("gemini selected but gemini_api_key unset")
            providers[name] = GeminiProvider(api_key=cfg.gemini_api_key)
        elif name == "openrouter":
            # chunk 3 left as FakeProvider (spec calls for zai as the
            # second real provider); operators can extend openrouter.py
            # following gemini.py / zai.py patterns.
            providers[name] = FakeProvider(name="openrouter")
        elif name == "zai":
            if not cfg.zai_api_key:
                raise ValueError("zai selected but zai_api_key unset")
            providers[name] = ZaiProvider(api_key=cfg.zai_api_key)
        else:
            raise ValueError(f"unknown provider: {name}")
    return providers


def _make_imagine_for_provider(provider: Provider) -> Any:
    """Return an `imagine` callable that uses the given provider."""
    from ..daydream import default_imagine
    from ..types import EpisodicMemory

    def imagine(
        seed: EpisodicMemory,
        retrieved: list[EpisodicMemory],
        pool_name: str,
    ) -> list[tuple[str, str, str]]:
        prompt = (
            f"Seed memory: {seed.content!r}\n"
            f"Related ({len(retrieved)}): "
            + "; ".join(m.content for m in retrieved[:3])
            + "\nProduce one HYPOTHESIS that explores an alternative future."
        )
        try:
            reply = provider.complete(prompt, max_tokens=256)
        except Exception:
            logger.exception("provider %s failed during imagine", provider.name)
            return default_imagine(seed, retrieved, pool_name)
        return [
            (
                "hypothesis",
                reply.strip() or f"no reply from {provider.name}",
                seed.intent_at_time or "generic-intent",
            )
        ]

    return imagine


def build_and_run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="turing-runtime")
    parser.add_argument("--tick-rate", type=int)
    parser.add_argument("--db", type=str)
    parser.add_argument("--log-level", type=str, choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--log-format", type=str, choices=["plain", "json"])
    parser.add_argument("--providers", type=str, help="comma-separated: fake,gemini,openrouter,zai")
    parser.add_argument("--scenario", type=str)
    parser.add_argument("--duration", type=int, help="seconds to run before auto-stop (default: forever)")
    args = parser.parse_args(argv)

    overrides: dict[str, Any] = {}
    if args.tick_rate is not None:
        overrides["tick_rate_hz"] = args.tick_rate
    if args.db is not None:
        overrides["db_path"] = args.db
    if args.log_level is not None:
        overrides["log_level"] = args.log_level
    if args.log_format is not None:
        overrides["log_format"] = args.log_format
    if args.providers is not None:
        overrides["provider_choice"] = tuple(
            p.strip() for p in args.providers.split(",") if p.strip()
        )
    if args.scenario is not None:
        overrides["scenario"] = args.scenario

    cfg = load_config_from_env(overrides=overrides)
    setup_logging(level=cfg.log_level, fmt=cfg.log_format)

    logger.info(
        "starting runtime tick_rate=%d db=%s providers=%s",
        cfg.tick_rate_hz,
        cfg.db_path,
        ",".join(cfg.provider_choice),
    )

    repo = Repo(cfg.db_path if cfg.db_path != ":memory:" else None)
    self_id = bootstrap_self_id(repo.conn)
    logger.info("self_id=%s", self_id)

    reactor = RealReactor(
        tick_rate_hz=cfg.tick_rate_hz,
        executor_workers=cfg.executor_workers,
    )
    motivation = Motivation(reactor)
    scheduler = Scheduler(reactor, motivation)

    providers = _build_providers(cfg)
    quota_tracker = FreeTierQuotaTracker()
    for pool_name, provider in providers.items():
        quota_tracker.register(
            provider,
            quality_weight=DEFAULT_QUALITY_WEIGHTS.get(pool_name, 1.0),
        )
        DaydreamProducer(
            pool_name=pool_name,
            self_id=self_id,
            motivation=motivation,
            reactor=reactor,
            repo=repo,
            imagine=_make_imagine_for_provider(provider),
        )

    # Per-tick: refresh pressure_vec from the quota tracker. O(len(providers))
    # and cheap.
    def _refresh_pressure(tick: int) -> None:
        for pool_name, value in quota_tracker.pressure_vec().items():
            motivation.set_pressure(pool_name, value)

    reactor.register(_refresh_pressure)

    ContradictionDetector(
        repo=repo,
        motivation=motivation,
        reactor=reactor,
        self_id=self_id,
    )
    CoefficientTuner(
        motivation=motivation,
        reactor=reactor,
        repo=repo,
        self_id=self_id,
    )

    if cfg.scenario:
        scenario_path = _resolve_scenario_path(cfg.scenario)
        logger.info("loading scenario %s", scenario_path)
        scenario = load_scenario(scenario_path)
        WorkloadDriver(
            scenario=scenario,
            motivation=motivation,
            reactor=reactor,
            scheduler=scheduler,
            repo=repo,
            self_id=self_id,
        )

    def _handle_signal(signum: int, _frame: Any) -> None:
        logger.info("signal %d received; stopping reactor", signum)
        reactor.stop()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    if args.duration is not None:
        import threading

        threading.Timer(args.duration, reactor.stop).start()

    reactor.run_forever()
    status = reactor.get_status()
    logger.info(
        "reactor stopped tick_count=%d drift_p99_ms=%.2f",
        status.tick_count,
        status.drift_ms_p99,
    )
    repo.close()
    return 0


if __name__ == "__main__":
    sys.exit(build_and_run())
