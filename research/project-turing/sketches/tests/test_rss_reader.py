"""Tests for runtime/tools/rss.py — RSS + Atom parsing, dedup."""

from __future__ import annotations

import httpx
import pytest
import respx

from turing.runtime.tools.rss import RSSReader


_RSS_BODY = """<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0">
  <channel>
    <title>Example feed</title>
    <link>https://example.com</link>
    <item>
      <title>First post</title>
      <link>https://example.com/first</link>
      <guid>guid-first</guid>
      <description>summary 1</description>
      <pubDate>Tue, 01 Apr 2026 12:00:00 +0000</pubDate>
    </item>
    <item>
      <title>Second post</title>
      <link>https://example.com/second</link>
      <guid>guid-second</guid>
      <description>summary 2</description>
      <pubDate>Tue, 02 Apr 2026 12:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>
"""

_ATOM_BODY = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom feed</title>
  <id>urn:atom:example</id>
  <entry>
    <id>urn:atom:entry:1</id>
    <title>Atom one</title>
    <link href="https://example.com/atom-1" />
    <updated>2026-04-01T12:00:00Z</updated>
    <summary>atom summary 1</summary>
  </entry>
</feed>
"""


@respx.mock
def test_rss_parse_returns_items() -> None:
    url = "https://example.com/rss"
    respx.get(url).mock(return_value=httpx.Response(200, text=_RSS_BODY))
    reader = RSSReader(feeds=[url])
    items = reader.invoke(url=url)
    assert len(items) == 2
    titles = {it.title for it in items}
    assert titles == {"First post", "Second post"}
    assert all(it.feed_url == url for it in items)


@respx.mock
def test_atom_parse_returns_items() -> None:
    url = "https://example.com/atom"
    respx.get(url).mock(return_value=httpx.Response(200, text=_ATOM_BODY))
    reader = RSSReader(feeds=[url])
    items = reader.invoke(url=url)
    assert len(items) == 1
    assert items[0].title == "Atom one"
    assert items[0].item_id == "urn:atom:entry:1"
    assert items[0].link == "https://example.com/atom-1"


@respx.mock
def test_dedup_across_polls() -> None:
    url = "https://example.com/rss"
    respx.get(url).mock(return_value=httpx.Response(200, text=_RSS_BODY))
    reader = RSSReader(feeds=[url])
    first = reader.invoke(url=url)
    second = reader.invoke(url=url)
    assert len(first) == 2
    assert second == []                              # no new items


@respx.mock
def test_failed_request_returns_empty_no_raise() -> None:
    url = "https://example.com/rss"
    respx.get(url).mock(return_value=httpx.Response(500, text="server down"))
    reader = RSSReader(feeds=[url])
    assert reader.invoke(url=url) == []


def test_add_feed_dynamically() -> None:
    reader = RSSReader(feeds=())
    reader.add_feed("https://example.com/feed")
    assert reader.feeds() == ["https://example.com/feed"]
    reader.add_feed("https://example.com/feed")          # idempotent
    assert reader.feeds() == ["https://example.com/feed"]
