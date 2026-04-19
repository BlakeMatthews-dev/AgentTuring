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
from ..dreaming import Dreamer
from ..motivation import Motivation
from ..repo import Repo
from ..scheduler import Scheduler
from ..self_identity import bootstrap_self_id
from ..tuning import CoefficientTuner
from .config import RuntimeConfig, load_config_from_env
from .instrumentation import setup_logging
from .actor import Actor
from .chat import ChatBridge, start_chat_server
from .journal import Journal
from .metrics import MetricsCollector, start_metrics_server
from .pools import PoolConfig, load_pools
from .providers.base import Provider
from .providers.fake import FakeProvider
from .providers.litellm import LiteLLMProvider
from .quota import FreeTierQuotaTracker
from .reactor import RealReactor
from .tools.base import ToolRegistry
from .tools.obsidian import ObsidianWriter
from .tools.rss import RSSReader
from .workload import WorkloadDriver, load_scenario


logger = logging.getLogger("turing.runtime.main")


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


def _select_chat_provider(
    providers: dict[str, Provider],
    weights: dict[str, float],
) -> Provider:
    """Highest-quality registered pool. Falls back to the first if weights tie."""
    if not providers:
        raise RuntimeError("no providers registered; cannot service chat")
    best_name = max(providers, key=lambda name: weights.get(name, 1.0))
    return providers[best_name]


def _build_providers(
    cfg: RuntimeConfig,
) -> tuple[dict[str, Provider], dict[str, float]]:
    """Returns (providers_by_pool_name, quality_weights_by_pool_name)."""
    if cfg.use_fake_provider:
        return {"fake": FakeProvider(name="fake")}, {"fake": 0.1}

    assert cfg.litellm_base_url and cfg.litellm_virtual_key and cfg.pools_config_path
    pools: list[PoolConfig] = load_pools(cfg.pools_config_path)
    if not pools:
        raise ValueError(f"pools config has no pools: {cfg.pools_config_path}")
    providers: dict[str, Provider] = {}
    weights: dict[str, float] = {}
    for pool in pools:
        providers[pool.pool_name] = LiteLLMProvider(
            pool_config=pool,
            base_url=cfg.litellm_base_url,
            virtual_key=cfg.litellm_virtual_key,
        )
        weights[pool.pool_name] = pool.quality_weight
    return providers, weights


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
    parser.add_argument("--journal-dir", type=str, help="enable journal output at this directory")
    parser.add_argument("--log-level", type=str, choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--log-format", type=str, choices=["plain", "json"])
    parser.add_argument("--use-fake-provider", action="store_true",
                        help="run with the FakeProvider (no LiteLLM needed)")
    parser.add_argument("--litellm-base-url", type=str)
    parser.add_argument("--litellm-virtual-key", type=str)
    parser.add_argument("--pools-config", type=str, help="path to pools YAML")
    parser.add_argument("--scenario", type=str)
    parser.add_argument("--duration", type=int, help="seconds to run before auto-stop (default: forever)")
    parser.add_argument("--metrics-port", type=int, help="enable Prometheus endpoint on this port")
    parser.add_argument("--metrics-bind", type=str, default=None,
                        help="bind interface for the metrics endpoint (default 127.0.0.1)")
    parser.add_argument("--chat-port", type=int, help="enable chat HTTP server on this port")
    parser.add_argument("--chat-bind", type=str, default=None,
                        help="bind interface for the chat server (default 127.0.0.1)")
    parser.add_argument("--obsidian-vault", type=str,
                        help="enable Obsidian vault writes at this directory")
    parser.add_argument("--rss-feeds", type=str,
                        help="comma-separated RSS/Atom feed URLs to subscribe to")
    args = parser.parse_args(argv)

    overrides: dict[str, Any] = {}
    if args.tick_rate is not None:
        overrides["tick_rate_hz"] = args.tick_rate
    if args.db is not None:
        overrides["db_path"] = args.db
    if args.journal_dir is not None:
        overrides["journal_dir"] = args.journal_dir
    if args.log_level is not None:
        overrides["log_level"] = args.log_level
    if args.log_format is not None:
        overrides["log_format"] = args.log_format
    if args.use_fake_provider:
        overrides["use_fake_provider"] = True
    if args.litellm_base_url is not None:
        overrides["litellm_base_url"] = args.litellm_base_url
        overrides["use_fake_provider"] = False
    if args.litellm_virtual_key is not None:
        overrides["litellm_virtual_key"] = args.litellm_virtual_key
    if args.pools_config is not None:
        overrides["pools_config_path"] = args.pools_config
    if args.scenario is not None:
        overrides["scenario"] = args.scenario
    if args.metrics_port is not None:
        overrides["metrics_port"] = args.metrics_port
    if args.metrics_bind is not None:
        overrides["metrics_bind"] = args.metrics_bind
    if args.chat_port is not None:
        overrides["chat_port"] = args.chat_port
    if args.chat_bind is not None:
        overrides["chat_bind"] = args.chat_bind
    if args.obsidian_vault is not None:
        overrides["obsidian_vault_dir"] = args.obsidian_vault
    if args.rss_feeds is not None:
        overrides["rss_feeds"] = tuple(
            f.strip() for f in args.rss_feeds.split(",") if f.strip()
        )

    cfg = load_config_from_env(overrides=overrides)
    setup_logging(level=cfg.log_level, fmt=cfg.log_format)

    pool_label = "fake" if cfg.use_fake_provider else f"litellm({cfg.pools_config_path})"
    logger.info(
        "starting runtime tick_rate=%d db=%s pools=%s",
        cfg.tick_rate_hz,
        cfg.db_path,
        pool_label,
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

    providers, quality_weights = _build_providers(cfg)
    quota_tracker = FreeTierQuotaTracker()
    for pool_name, provider in providers.items():
        quota_tracker.register(
            provider,
            quality_weight=quality_weights.get(pool_name, 1.0),
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
    Dreamer(
        motivation=motivation,
        reactor=reactor,
        repo=repo,
        self_id=self_id,
    )

    if cfg.journal_dir:
        journal = Journal(repo=repo, self_id=self_id, journal_dir=cfg.journal_dir)
        reactor.register(journal.on_tick)
        logger.info("journal writing to %s", cfg.journal_dir)

    # Tool layer + Actor.
    tool_registry = ToolRegistry()
    if cfg.obsidian_vault_dir:
        tool_registry.register(ObsidianWriter(vault_dir=cfg.obsidian_vault_dir))
        logger.info("obsidian writes enabled at %s", cfg.obsidian_vault_dir)
    if cfg.rss_feeds:
        tool_registry.register(RSSReader(feeds=cfg.rss_feeds))
        logger.info("rss reader registered with %d feed(s)", len(cfg.rss_feeds))
    if tool_registry.names():
        actor = Actor(repo=repo, self_id=self_id, registry=tool_registry)
        reactor.register(actor.on_tick)

    # Chat HTTP server + dispatch handler that uses an LLM provider to reply.
    stop_chat: Any = None
    if cfg.chat_port is not None:
        bridge = ChatBridge()

        # Pick the highest-quality registered pool for chat replies.
        chat_provider = _select_chat_provider(providers, quality_weights)

        def _on_chat_dispatch(item: BacklogItem, chosen_pool: str) -> None:
            payload = item.payload or {}
            message = str(payload.get("message", ""))
            try:
                reply = chat_provider.complete(
                    f"You are an autonoetic Conduit. Reply concisely.\nUser: {message}\nReply:",
                    max_tokens=400,
                )
            except Exception:
                logger.exception("chat dispatch failed")
                reply = "(I encountered an error generating a reply.)"
            bridge.resolve(item.item_id, reply)

        motivation.register_dispatch("chat_message", _on_chat_dispatch)

        stop_chat = start_chat_server(
            motivation=motivation,
            repo=repo,
            self_id=self_id,
            bridge=bridge,
            port=cfg.chat_port,
            host=cfg.chat_bind,
            journal_dir=cfg.journal_dir,
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

    stop_metrics: Any = None
    if cfg.metrics_port is not None:
        collector = MetricsCollector()

        def _refresh_metrics(tick: int) -> None:
            status = reactor.get_status()
            collector.update(
                turing_tick_count=status.tick_count,
                turing_drift_ms_p99=status.drift_ms_p99,
            )
            for pool, value in quota_tracker.pressure_vec().items():
                collector.set_labeled("turing_pressure", (pool,), value)
                window = quota_tracker.window(pool)
                if window is not None:
                    collector.set_labeled(
                        "turing_quota_headroom", (pool,), window.headroom
                    )
            # Durable counts: cheap enough every tick, but only refresh
            # every 10th tick to avoid DB thrash.
            if tick % 10 == 0:
                for tier in ("regret", "accomplishment", "affirmation", "wisdom"):
                    n = repo.conn.execute(
                        "SELECT COUNT(*) FROM durable_memory WHERE tier = ?",
                        (tier,),
                    ).fetchone()[0]
                    collector.set_labeled(
                        "turing_durable_memories_total", (tier,), n
                    )

        reactor.register(_refresh_metrics)
        stop_metrics = start_metrics_server(
            collector, port=cfg.metrics_port, host=cfg.metrics_bind
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
    if stop_metrics is not None:
        stop_metrics()
    if stop_chat is not None:
        stop_chat()
    repo.close()
    return 0


if __name__ == "__main__":
    sys.exit(build_and_run())
