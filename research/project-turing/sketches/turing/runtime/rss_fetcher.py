"""RSSFetcher: scheduled poller that drops new feed items into the backlog.

Distinct from `tools/rss.py`'s `RSSReader`, which is the on-demand Tool
that anyone can invoke. The Fetcher runs on a cadence and produces
backlog items the system then thinks about.

Each new feed item becomes a P7 `rss_item` backlog entry. When dispatched,
a separate handler (`_on_dispatch_rss_item` in main.py) asks the LLM to
reason about it — what does the self think? what does it want to do?
How interesting/relevant is it? A weak OBSERVATION summary is always
written. If interesting enough, an OPINION is minted. If actionable,
an AFFIRMATION.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from ..motivation import BacklogItem, Motivation, PipelineState
from ..reactor import FakeReactor
from .tools.rss import FeedItem, RSSReader


logger = logging.getLogger("turing.runtime.rss_fetcher")


DEFAULT_RSS_POLL_TICKS: int = 30_000      # 5 min at 100Hz


class RSSFetcher:
    def __init__(
        self,
        *,
        reader: RSSReader,
        motivation: Motivation,
        reactor: FakeReactor,
        poll_ticks: int = DEFAULT_RSS_POLL_TICKS,
    ) -> None:
        self._reader = reader
        self._motivation = motivation
        self._poll_ticks = poll_ticks
        self._last_poll_tick = 0
        reactor.register(self.on_tick)

    def on_tick(self, tick: int) -> None:
        if tick - self._last_poll_tick < self._poll_ticks:
            return
        self._last_poll_tick = tick
        try:
            self._poll()
        except Exception:
            logger.exception("rss fetch failed")

    def _poll(self) -> None:
        new_items = self._reader.invoke()
        for feed_item in new_items:
            self._motivation.insert(self._to_backlog(feed_item))

    def _to_backlog(self, feed_item: FeedItem) -> BacklogItem:
        return BacklogItem(
            item_id=str(uuid4()),
            class_=7,
            kind="rss_item",
            payload={"feed_item": feed_item},
            fit={},
            readiness=lambda s: True,
            cost_estimate_tokens=800,
        )
