"""Headlines from public RSS feeds, fetched at build time.

Baked into the page rather than loaded in the browser: the published dashboard runs
under a strict content policy and cannot call out to other hosts, and a build-time
fetch also means a slow or dead feed never affects the reader.

Deliberately headline-only, carrying the publisher's own summary verbatim where one
exists. Nothing here is re-worded - paraphrasing an article the system has not read
would manufacture claims and attribute them to a source.
"""
from __future__ import annotations

import re
import urllib.request
from datetime import datetime
from xml.etree import ElementTree

_UA = {"User-Agent": "Mozilla/5.0 (compatible; market-intel/1.0)"}
_TAG_RE = re.compile(r"<[^>]+>")

_DATE_FORMATS = (
    "%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z",
    "%a, %d %b %Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ",
)


class Item(object):
    __slots__ = ("title", "link", "summary", "source", "published", "topic")

    def __init__(self, **kw):
        for s in self.__slots__:
            setattr(self, s, kw.get(s))

    def as_dict(self):
        d = {s: getattr(self, s) for s in self.__slots__}
        if hasattr(d["published"], "isoformat"):
            d["published"] = d["published"].isoformat()
        return d


def _clean(text, limit=240):
    if not text:
        return ""
    text = _TAG_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit].rstrip() + ("…" if len(text) > limit else "")


def _parse_when(text):
    """Parse a feed timestamp, always returning a NAIVE datetime.

    Feeds mix timezone-aware and naive stamps, and Python refuses to compare the
    two - which crashed the whole news tab at sort time. Normalising to naive UTC
    at parse time keeps the comparison total.
    """
    if not text:
        return None
    text = text.strip()
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if parsed.tzinfo is not None:
            parsed = (parsed - parsed.utcoffset()).replace(tzinfo=None)
        return parsed
    return None


def fetch_feed(url, source, topic, timeout=20, limit=8):
    """One feed. Returns [] on any failure - news must never break the build."""
    try:
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        root = ElementTree.fromstring(raw)
    except Exception:  # noqa: BLE001 - a dead feed is not an error worth failing on
        return []

    items = root.findall(".//item") or root.findall(
        ".//{http://www.w3.org/2005/Atom}entry")
    out = []
    for node in items[:limit]:
        def _text(*names):
            for n in names:
                el = node.find(n)
                if el is not None and (el.text or el.get("href")):
                    return el.text or el.get("href")
            return ""

        title = _clean(_text("title", "{http://www.w3.org/2005/Atom}title"), 160)
        if not title:
            continue
        link = _text("link", "{http://www.w3.org/2005/Atom}link")
        out.append(Item(
            title=title,
            link=(link or "").strip(),
            summary=_clean(_text("description",
                                 "{http://www.w3.org/2005/Atom}summary")),
            source=source,
            published=_parse_when(_text("pubDate",
                                        "{http://www.w3.org/2005/Atom}updated")),
            topic=topic,
        ))
    return out


def fetch_all(feeds, per_topic=10):
    """Fetch every configured feed, grouped by topic, newest first."""
    by_topic = {}
    for feed in feeds:
        items = fetch_feed(feed["url"], feed.get("source", ""), feed["topic"])
        by_topic.setdefault(feed["topic"], []).extend(items)

    for topic, items in by_topic.items():
        # Sort newest first, with undated items last. `published` is guaranteed
        # naive by _parse_when, so the comparison cannot raise.
        items.sort(key=lambda i: (i.published is not None, i.published or datetime.min),
                   reverse=True)
        # Same story often appears across feeds; keep the first of each title.
        seen, unique = set(), []
        for i in items:
            key = i.title.lower()[:70]
            if key in seen:
                continue
            seen.add(key)
            unique.append(i)
        by_topic[topic] = unique[:per_topic]
    return by_topic
