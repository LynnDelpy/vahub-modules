"""Unit tests for the RSS module's parsing helpers.

The tools are thin wrappers over these and over the network, so parsing a feed,
merging by date and the "not configured" behaviour are what is worth testing
without a live feed.
"""

from __future__ import annotations

import asyncio

from vahub_mod_rss import server

RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
<title>Example Blog</title>
<item>
  <title>First post</title>
  <link>https://ex.test/1</link>
  <pubDate>Thu, 01 Jan 2026 10:00:00 GMT</pubDate>
  <description>&lt;p&gt;Hello &amp; welcome&lt;/p&gt;</description>
</item>
<item>
  <title>Second post</title>
  <link>https://ex.test/2</link>
  <pubDate>Fri, 02 Jan 2026 10:00:00 GMT</pubDate>
  <description>More stuff</description>
</item>
</channel></rss>
"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<title>Atom News</title>
<entry>
  <title>Atom item</title>
  <link href="https://at.test/1"/>
  <updated>2026-01-03T10:00:00Z</updated>
  <summary>Atom summary text</summary>
</entry>
</feed>
"""


def test_split_feeds_accepts_whitespace_comma_and_newlines() -> None:
    raw = "https://a/f.xml, https://b/f.xml\nhttps://c/f.xml"
    assert server.split_feeds(raw) == ["https://a/f.xml", "https://b/f.xml", "https://c/f.xml"]
    assert server.split_feeds("  ") == []


def test_strip_html_reduces_markup_to_plain_text() -> None:
    assert server.strip_html("<p>Hello &amp; <b>bye</b></p>") == "Hello & bye"
    assert server.strip_html("plain") == "plain"
    assert server.strip_html("") == ""


def test_parse_rss_extracts_title_items_and_dates() -> None:
    result = server.parse_feed(RSS, "https://ex.test/feed.xml")
    assert result["feed"] == "Example Blog"
    assert len(result["items"]) == 2
    first = result["items"][0]
    assert first["title"] == "First post"
    assert first["link"] == "https://ex.test/1"
    assert first["published"] == "2026-01-01T10:00:00+00:00"
    assert first["summary"] == "Hello & welcome"
    assert first["feed"] == "Example Blog"


def test_parse_atom_uses_updated_when_there_is_no_published() -> None:
    result = server.parse_feed(ATOM, "https://at.test/feed.xml")
    assert result["feed"] == "Atom News"
    item = result["items"][0]
    assert item["title"] == "Atom item"
    assert item["link"] == "https://at.test/1"
    assert item["published"] == "2026-01-03T10:00:00+00:00"


def test_feed_title_falls_back_to_the_host() -> None:
    result = server.parse_feed(b"<rss version='2.0'><channel></channel></rss>", "https://host.test/x.xml")
    assert result["feed"] == "host.test"


def test_items_merge_newest_first_and_undated_sort_last() -> None:
    items = server.parse_feed(RSS, "https://ex.test/f")["items"]
    items += server.parse_feed(ATOM, "https://at.test/f")["items"]
    undated = {"title": "no date", "_sort": None}
    items.append(undated)
    items.sort(key=server._sort_key, reverse=True)
    assert [i["title"] for i in items] == ["Atom item", "Second post", "First post", "no date"]


def test_matches_looks_across_title_summary_and_feed() -> None:
    item = server.parse_feed(RSS, "https://ex.test/f")["items"][0]
    assert server._matches(item, "welcome") is True
    assert server._matches(item, "example blog") is True
    assert server._matches(item, "nonsense") is False


def test_public_strips_the_internal_sort_key() -> None:
    item = server.parse_feed(RSS, "https://ex.test/f")["items"][0]
    assert "_sort" in item
    assert "_sort" not in server.public(item)


def test_feed_can_be_matched_by_host_not_only_title() -> None:
    # Channel title is "Example Blog"; the feed lives at blog.example.com.
    items = server.parse_feed(RSS, "https://blog.example.com/rss")["items"]
    assert all(i["_host"] == "blog.example.com" for i in items)
    assert "_host" not in server.public(items[0])
    # matching works by title (as before) and now by host (the documented promise)
    assert server.feed_match(items[0], "example blog") is True
    assert server.feed_match(items[0], "example.com") is True
    assert server.feed_match(items[0], "nonsense") is False


def test_tools_report_missing_configuration(monkeypatch) -> None:
    monkeypatch.setattr(server, "FEEDS", "")
    result = asyncio.run(server.summary())
    assert result["configured"] is False and "RSS_FEEDS" in result["error"]
    health = asyncio.run(server.health())
    assert health["ok"] is False and "RSS_FEEDS" in health["detail"]
