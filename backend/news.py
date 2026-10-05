"""Small, fixed-source RSS collector. No user-supplied fetch URLs."""
import asyncio
import base64
import calendar
import hashlib
import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import httpx

LOG = logging.getLogger("space_news")
DB_PATH = Path(os.environ.get("NEWS_DB_PATH", "data/news.sqlite3"))
SOURCES = {
    "nasa": {"name": "NASA", "url": "https://www.nasa.gov/news-release/feed/", "domain": "nasa.gov"},
    "esa": {"name": "ESA", "url": "https://www.esa.int/rssfeed/Our_Activities/Space_News", "domain": "esa.int"},
}
MAX_FEED_BYTES = 2 * 1024 * 1024


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip += 1
        if tag in {"p", "br", "div", "li"} and not self.skip:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.skip = max(0, self.skip - 1)
        elif tag in {"p", "div", "li"} and not self.skip:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def text(value, limit):
    parser = PlainText()
    parser.feed(str(value or ""))
    return " ".join("".join(parser.parts).split())[:limit]


def allowed_url(value, domain):
    try:
        parts = urlsplit(value)
        host = (parts.hostname or "").lower()
        return (parts.scheme in {"http", "https"} and not parts.username and not parts.password
                and parts.port in {None, 80, 443} and (host == domain or host.endswith("." + domain)))
    except ValueError:
        return False


def canonical_url(value):
    parts = urlsplit(value)
    query = [(key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True)
             if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"}]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", urlencode(query), ""))


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def initialize():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS sources (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, feed_url TEXT NOT NULL,
          last_attempt_at TEXT, last_success_at TEXT, last_error TEXT,
          etag TEXT, last_modified TEXT, last_item_count INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS articles (
          id INTEGER PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id),
          source_item_id TEXT, canonical_url TEXT NOT NULL, original_url TEXT NOT NULL,
          title TEXT NOT NULL, summary TEXT NOT NULL, published_at TEXT,
          date_status TEXT NOT NULL, first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
          content_hash TEXT NOT NULL, lang TEXT NOT NULL DEFAULT 'en',
          material_status TEXT NOT NULL DEFAULT 'summary_only',
          UNIQUE(source_id, canonical_url));
        CREATE INDEX IF NOT EXISTS article_order ON articles(published_at DESC,id DESC);
        CREATE INDEX IF NOT EXISTS article_source ON articles(source_id,published_at DESC,id DESC);
        """)
        for source_id, source in SOURCES.items():
            conn.execute("""INSERT INTO sources(id,name,feed_url) VALUES(?,?,?)
              ON CONFLICT(id) DO UPDATE SET name=excluded.name,feed_url=excluded.feed_url""",
                         (source_id, source["name"], source["url"]))


def parse_feed(source_id, raw):
    feed = feedparser.parse(raw)
    if not feed.get("version"):
        raise ValueError("Response is not a recognized RSS/Atom feed")
    records = []
    rejected = 0
    for entry in feed.entries:
        url = entry.get("link", "")
        title = text(entry.get("title"), 400)
        if not title or not allowed_url(url, SOURCES[source_id]["domain"]):
            rejected += 1
            continue
        published = entry.get("published_parsed")
        date_status = "provided" if published else "missing"
        # An updated date is not silently substituted for a publication date.
        try:
            date = datetime.fromtimestamp(calendar.timegm(published), timezone.utc).isoformat(timespec="seconds") if published else None
        except (ValueError, OverflowError, OSError):
            date, date_status = None, "invalid"
        summary = text(entry.get("summary", entry.get("description", "")), 600)
        records.append({"source_id": source_id, "source_item_id": str(entry.get("id", ""))[:600],
                        "canonical_url": canonical_url(url), "original_url": url,
                        "title": title, "summary": summary, "published_at": date, "date_status": date_status,
                        "content_hash": hashlib.sha256((title + "\n" + summary).encode()).hexdigest()})
    if feed.entries and not records:
        raise ValueError("Feed contained no acceptable entries")
    return records, rejected


def store_records(records):
    stamp = now()
    with connect() as conn:
        for record in records:
            conn.execute("""INSERT INTO articles(source_id,source_item_id,canonical_url,original_url,
              title,summary,published_at,date_status,first_seen_at,last_seen_at,content_hash)
              VALUES(:source_id,:source_item_id,:canonical_url,:original_url,:title,:summary,
              :published_at,:date_status,:first_seen_at,:last_seen_at,:content_hash)
              ON CONFLICT(source_id,canonical_url) DO UPDATE SET
                title=excluded.title,summary=excluded.summary,original_url=excluded.original_url,
                source_item_id=excluded.source_item_id,
                published_at=COALESCE(excluded.published_at,articles.published_at),
                date_status=CASE WHEN excluded.published_at IS NOT NULL THEN excluded.date_status
                                ELSE articles.date_status END,
                last_seen_at=excluded.last_seen_at,content_hash=excluded.content_hash""",
                         {**record, "first_seen_at": stamp, "last_seen_at": stamp})


def source_state(source_id):
    with connect() as conn:
        return dict(conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone())


def update_source(source_id, *, attempt=False, success=False, error=None, etag=None, modified=None, count=None):
    with connect() as conn:
        if attempt:
            conn.execute("UPDATE sources SET last_attempt_at=? WHERE id=?", (now(), source_id))
        elif success:
            conn.execute("""UPDATE sources SET last_success_at=?,last_error=NULL,
                etag=COALESCE(?,etag),last_modified=COALESCE(?,last_modified),
                last_item_count=COALESCE(?,last_item_count) WHERE id=?""", (now(), etag, modified, count, source_id))
        else:
            conn.execute("UPDATE sources SET last_error=? WHERE id=?", (str(error)[:300], source_id))


async def fetch_feed(client, source_id, state):
    source = SOURCES[source_id]
    headers = {"User-Agent": "SpaceScienceNews/0.1 (official-feed-reader)", "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"}
    if state.get("etag"):
        headers["If-None-Match"] = state["etag"]
    if state.get("last_modified"):
        headers["If-Modified-Since"] = state["last_modified"]
    url = source["url"]
    for _ in range(4):
        if not allowed_url(url, source["domain"]):
            raise ValueError("Feed redirect left approved publisher domain")
        async with client.stream("GET", url, headers=headers, follow_redirects=False) as response:
            if response.status_code == 304:
                return None, {}
            if response.is_redirect:
                url = str(response.url.join(response.headers["location"]))
                continue
            response.raise_for_status()
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > MAX_FEED_BYTES:
                    raise ValueError("Feed exceeds maximum response size")
            return bytes(data), dict(response.headers)
    raise ValueError("Too many feed redirects")


async def collect_source(client, source_id):
    await asyncio.to_thread(update_source, source_id, attempt=True)
    state = await asyncio.to_thread(source_state, source_id)
    try:
        for attempt in range(2):
            try:
                raw, headers = await fetch_feed(client, source_id, state)
                break
            except httpx.HTTPStatusError as error:
                # Respect throttling; defer until the next scheduled run rather than hammering.
                if error.response.status_code == 429 or error.response.status_code < 500 or attempt == 1:
                    raise
                await asyncio.sleep(2)
            except httpx.TransportError:
                if attempt == 1:
                    raise
                await asyncio.sleep(2)
        if raw is None:
            await asyncio.to_thread(update_source, source_id, success=True)
            return {"source": source_id, "unchanged": True}
        records, rejected = await asyncio.to_thread(parse_feed, source_id, raw)
        await asyncio.to_thread(store_records, records)
        await asyncio.to_thread(update_source, source_id, success=True, etag=headers.get("etag"),
                                modified=headers.get("last-modified"), count=len(records))
        LOG.info("%s collected=%d rejected=%d", source_id, len(records), rejected)
        return {"source": source_id, "accepted": len(records), "rejected": rejected}
    except Exception as error:
        message = f"{type(error).__name__}: {error}"
        await asyncio.to_thread(update_source, source_id, error=message)
        LOG.warning("%s collection failed: %s", source_id, message)
        return {"source": source_id, "error": message}


async def collect_all():
    async with httpx.AsyncClient(timeout=15, limits=httpx.Limits(max_connections=2), trust_env=False) as client:
        return await asyncio.gather(*(collect_source(client, source_id) for source_id in SOURCES))


def encode_cursor(row, source):
    return base64.urlsafe_b64encode(json.dumps([row["published_at"] or "", row["id"], source]).encode()).decode()


def list_articles(source=None, cursor=None, limit=20):
    clauses, args = [], []
    if source:
        if source not in SOURCES:
            raise ValueError("Unknown source")
        clauses.append("a.source_id=?")
        args.append(source)
    if cursor:
        try:
            date, article_id, cursor_source = json.loads(base64.urlsafe_b64decode(cursor))
            if not isinstance(date, str) or type(article_id) is not int or cursor_source != source:
                raise ValueError()
        except Exception as error:
            raise ValueError("Invalid cursor or source mismatch") from error
        clauses.append("(COALESCE(a.published_at,'')<? OR (COALESCE(a.published_at,'')=? AND a.id<?))")
        args.extend([date, date, article_id])
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with connect() as conn:
        rows = [dict(row) for row in conn.execute("""SELECT a.*,s.name AS source_name FROM articles a
            JOIN sources s ON a.source_id=s.id""" + where +
            " ORDER BY COALESCE(a.published_at,'') DESC,a.id DESC LIMIT ?", [*args, limit + 1])]
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {"items": rows, "next_cursor": encode_cursor(rows[-1], source) if has_more else None}


def sources_status():
    with connect() as conn:
        return [dict(row) for row in conn.execute("""SELECT s.id,s.name,s.last_attempt_at,s.last_success_at,
            s.last_error,s.last_item_count,COUNT(a.id) AS stored_articles
            FROM sources s LEFT JOIN articles a ON a.source_id=s.id GROUP BY s.id ORDER BY s.id""")]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    initialize()
    print(json.dumps(asyncio.run(collect_all()), ensure_ascii=False, indent=2))
