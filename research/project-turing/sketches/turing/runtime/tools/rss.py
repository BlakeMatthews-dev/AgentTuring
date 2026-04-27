"""RSSReader: subscribes to RSS / Atom feeds; surfaces new items.

Reads-only tool. Polls its registered feeds on a cadence; new items become
backlog candidates the operator can route through the motivation layer
however they like (a default integration drops them as P5 backlog items).

stdlib XML — no feedparser dep — to keep the runtime lean. Handles RSS 2.0
and Atom feed shapes we'd realistically encounter; bails on anything weirder
with a logged warning.
"""

from __future__ import annotations

import hashlib
import logging
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from .base import Tool, ToolMode


logger = logging.getLogger("turing.runtime.tools.rss")


@dataclass(frozen=True)
class FeedItem:
    feed_url: str
    item_id: str  # stable across polls (guid / id / link or hashed link+title)
    title: str
    summary: str
    link: str
    published_at: datetime | None


@dataclass
class FeedState:
    url: str
    seen_ids: set[str] = field(default_factory=set)
    last_polled_at: datetime | None = None


_ATOM_NS = "{http://www.w3.org/2005/Atom}"
_RDF_NS = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
_RSS1_NS = "{http://purl.org/rss/1.0/}"


class RSSReader:
    name = "rss_reader"
    mode = ToolMode.READ

    def __init__(
        self,
        *,
        feeds: Iterable[str] = (),
        client: httpx.Client | None = None,
    ) -> None:
        self._feeds: dict[str, FeedState] = {url: FeedState(url=url) for url in feeds}
        self._client = client or httpx.Client(timeout=30.0, follow_redirects=True)

    def add_feed(self, url: str) -> None:
        if url in self._feeds:
            return
        self._feeds[url] = FeedState(url=url)

    def feeds(self) -> list[str]:
        return sorted(self._feeds)

    def invoke(self, *, url: str | None = None) -> list[FeedItem]:
        """Poll a single feed (or all) and return new items since last poll."""
        urls = [url] if url else list(self._feeds)
        new_items: list[FeedItem] = []
        for u in urls:
            state = self._feeds.get(u)
            if state is None:
                self.add_feed(u)
                state = self._feeds[u]
            try:
                items = self._poll(state)
            except Exception:
                logger.exception("rss poll failed for %s", u)
                continue
            new_items.extend(items)
        return new_items

    def _poll(self, state: FeedState) -> list[FeedItem]:
        try:
            response = self._client.get(state.url)
        except httpx.RequestError as exc:
            logger.warning("rss request error %s: %s", state.url, exc)
            return []
        if not response.is_success:
            logger.warning("rss %s returned %d", state.url, response.status_code)
            return []
        raw = response.text
        if raw and raw[0] == "\ufeff":
            raw = raw[1:]
        root = ET.fromstring(raw)
        if root.tag.endswith("rss"):
            items = list(_parse_rss(state.url, root))
        elif root.tag.endswith("feed"):
            items = list(_parse_atom(state.url, root))
        elif _RDF_NS in root.tag and root.tag.endswith("RDF"):
            items = list(_parse_rdf(state.url, root))
        else:
            logger.warning("rss unknown root tag %s for %s", root.tag, state.url)
            items = []
        new = [it for it in items if it.item_id not in state.seen_ids]
        for it in new:
            state.seen_ids.add(it.item_id)
        state.last_polled_at = datetime.now(UTC)
        return new


# ---- Parsers ------------------------------------------------------------


def _parse_rss(feed_url: str, root: ET.Element) -> list[FeedItem]:
    out: list[FeedItem] = []
    channel = root.find("channel")
    if channel is None:
        return out
    for item in channel.findall("item"):
        guid = _text(item, "guid")
        link = _text(item, "link")
        title = _text(item, "title")
        summary = _text(item, "description") or ""
        pub_text = _text(item, "pubDate")
        item_id = guid or link or _hash_id(title, link)
        out.append(
            FeedItem(
                feed_url=feed_url,
                item_id=item_id,
                title=title or "(untitled)",
                summary=summary,
                link=link or "",
                published_at=_parse_rss_date(pub_text),
            )
        )
    return out


def _parse_atom(feed_url: str, root: ET.Element) -> list[FeedItem]:
    out: list[FeedItem] = []
    for entry in root.findall(f"{_ATOM_NS}entry"):
        eid = _text_atom(entry, "id")
        link_el = entry.find(f"{_ATOM_NS}link")
        link = link_el.attrib.get("href", "") if link_el is not None else ""
        title = _text_atom(entry, "title")
        summary = _text_atom(entry, "summary") or _text_atom(entry, "content") or ""
        pub_text = _text_atom(entry, "updated") or _text_atom(entry, "published")
        item_id = eid or link or _hash_id(title, link)
        out.append(
            FeedItem(
                feed_url=feed_url,
                item_id=item_id,
                title=title or "(untitled)",
                summary=summary,
                link=link,
                published_at=_parse_iso_date(pub_text),
            )
        )
    return out


def _parse_rdf(feed_url: str, root: ET.Element) -> list[FeedItem]:
    out: list[FeedItem] = []
    for item in root.findall(f"{_RSS1_NS}item"):
        link = _text_ns(item, _RSS1_NS, "link")
        title = _text_ns(item, _RSS1_NS, "title")
        summary = _text_ns(item, _RSS1_NS, "description") or ""
        item_id = link or _hash_id(title, link)
        out.append(
            FeedItem(
                feed_url=feed_url,
                item_id=item_id,
                title=title or "(untitled)",
                summary=summary,
                link=link or "",
                published_at=None,
            )
        )
    return out


def _text(el: ET.Element, name: str) -> str:
    child = el.find(name)
    return (child.text or "").strip() if child is not None and child.text else ""


def _text_atom(el: ET.Element, name: str) -> str:
    child = el.find(f"{_ATOM_NS}{name}")
    return (child.text or "").strip() if child is not None and child.text else ""


def _text_ns(el: ET.Element, ns: str, name: str) -> str:
    child = el.find(f"{ns}{name}")
    return (child.text or "").strip() if child is not None and child.text else ""


def _hash_id(*parts: str) -> str:
    h = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
    return f"sha1:{h[:16]}"


def _parse_rss_date(text: str) -> datetime | None:
    if not text:
        return None
    try:
        from email.utils import parsedate_to_datetime

        return parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None


def _parse_iso_date(text: str) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
