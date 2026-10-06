"""Small, fixed-source RSS collector. No user-supplied fetch URLs."""
import asyncio
import base64
import calendar
import hashlib
import json
import logging
import os
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from .sources import SOURCES, CATEGORIES, GEOGRAPHIC_REGIONS
from .locking import operation_lock

import feedparser
import httpx

LOG = logging.getLogger("space_news")
DB_PATH = Path(os.environ.get("NEWS_DB_PATH", "data/news.sqlite3"))
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
    with operation_lock(DB_PATH, timeout=10):
        _initialize()


def _initialize():
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
        columns = {row[1] for row in conn.execute('PRAGMA table_info(sources)')}
        if 'collector_kind' not in columns and conn.execute('SELECT COUNT(*) FROM articles').fetchone()[0]:
            # SQLite backup includes WAL and does not change existing article identities.
            backup = DB_PATH.with_name(DB_PATH.name + '.before-v2.sqlite3')
            if not backup.exists():
                with closing(sqlite3.connect(DB_PATH)) as origin, closing(sqlite3.connect(backup)) as target:
                    origin.backup(target)
        legacy = conn.execute('PRAGMA user_version').fetchone()[0] < 2
        migrating_v3 = 'geographic_region' not in columns
        if migrating_v3 and conn.execute('SELECT COUNT(*) FROM articles').fetchone()[0]:
            backup = DB_PATH.with_name(DB_PATH.name + '.before-v3.sqlite3')
            if not backup.exists():
                with closing(sqlite3.connect(DB_PATH)) as origin, closing(sqlite3.connect(backup)) as target:
                    origin.backup(target)
        additions = {
            'sources': {'collector_kind': "TEXT NOT NULL DEFAULT 'rss'", 'region': "TEXT NOT NULL DEFAULT 'international'",
                        'publisher_kind': "TEXT NOT NULL DEFAULT 'agency'", 'enabled': 'INTEGER NOT NULL DEFAULT 1',
                        'last_result': "TEXT NOT NULL DEFAULT 'never'", 'retry_after_at': 'TEXT',
                        'geographic_region': 'TEXT', 'country_code': 'TEXT', 'availability_note': 'TEXT'},
            'articles': {'summary_kind': "TEXT NOT NULL DEFAULT 'source_summary'", 'content_source': 'TEXT',
                         'published_precision': "TEXT NOT NULL DEFAULT 'second'", 'published_raw': 'TEXT',
                         'published_origin': "TEXT NOT NULL DEFAULT 'feed'", 'published_calendar_date': 'TEXT',
                         'published_timezone': 'TEXT', 'published_time_status': "TEXT NOT NULL DEFAULT 'legacy_unspecified'"},
        }
        for table, fields in additions.items():
            existing = {row[1] for row in conn.execute(f'PRAGMA table_info({table})')}
            for field, definition in fields.items():
                if field not in existing:
                    conn.execute(f'ALTER TABLE {table} ADD COLUMN {field} {definition}')
        if legacy:
            conn.execute("UPDATE articles SET published_precision='missing' WHERE published_at IS NULL")
            conn.execute("UPDATE articles SET summary_kind='none' WHERE summary=''")
            # v1 assigned en to every entry without checking a language declaration.
            conn.execute("UPDATE articles SET lang='und' WHERE lang='en'")
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS backfill_runs (
          id TEXT PRIMARY KEY, source_id TEXT NOT NULL, start_at TEXT NOT NULL, end_at TEXT NOT NULL,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, status TEXT NOT NULL,
          next_page INTEGER NOT NULL DEFAULT 0, total_pages INTEGER, stats TEXT NOT NULL DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS backfill_items (
          run_id TEXT NOT NULL REFERENCES backfill_runs(id), url TEXT NOT NULL, listing TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending', error TEXT, published_at TEXT,
          PRIMARY KEY(run_id,url));
        ''')
        item_columns = {row[1] for row in conn.execute('PRAGMA table_info(backfill_items)')}
        if 'attempts' not in item_columns:
            conn.execute('ALTER TABLE backfill_items ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0')
        if 'last_attempt_at' not in item_columns:
            conn.execute('ALTER TABLE backfill_items ADD COLUMN last_attempt_at TEXT')
        for source_id, source in SOURCES.items():
            conn.execute('''INSERT INTO sources(id,name,feed_url,collector_kind,region,publisher_kind,enabled,
              geographic_region,country_code,availability_note)
              VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,
              feed_url=excluded.feed_url,collector_kind=excluded.collector_kind,
              region=excluded.region,publisher_kind=excluded.publisher_kind,
              geographic_region=excluded.geographic_region,country_code=excluded.country_code,
              availability_note=excluded.availability_note''',
                         (source_id, source['name'], source['url'], source['collector_kind'],
                          source['region'], source['publisher_kind'], int(source['enabled']),
                          source.get('geographic_region'), source.get('country_code'), source.get('availability_note')))
        if migrating_v3:
            conn.execute("""UPDATE articles SET published_calendar_date=date(published_at,'+8 hours'),
              published_timezone='Asia/Shanghai',published_time_status='date_only'
              WHERE source_id IN ('cnsa','cmse','cas_space','landspace') AND published_precision='day' AND published_at IS NOT NULL""")
            conn.execute("UPDATE articles SET published_time_status='missing' WHERE published_at IS NULL")
        from . import reading
        reading.migrate(conn)
        from . import review_store
        review_store.migrate(conn)
        conn.execute('PRAGMA user_version=5')


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
                        "content_hash": hashlib.sha256((title + "\n" + summary).encode()).hexdigest(),
                        'lang': str(entry.get('language') or feed.feed.get('language') or 'und').split('-')[0].lower(),
                        'summary_kind': 'source_summary' if summary else 'none',
                        'published_precision': 'second' if date else 'missing',
                        'published_raw': entry.get('published'), 'published_origin': 'feed', 'content_source': None})
    if feed.entries and not records:
        raise ValueError("Feed contained no acceptable entries")
    return records, rejected


def store_records(records):
    stamp = now()
    with connect() as conn:
        for record in records:
            conn.execute("""INSERT INTO articles(source_id,source_item_id,canonical_url,original_url,
              title,summary,published_at,date_status,first_seen_at,last_seen_at,content_hash,
              lang,summary_kind,content_source,published_precision,published_raw,published_origin,
              published_calendar_date,published_timezone,published_time_status)
              VALUES(:source_id,:source_item_id,:canonical_url,:original_url,:title,:summary,
              :published_at,:date_status,:first_seen_at,:last_seen_at,:content_hash,
              :lang,:summary_kind,:content_source,:published_precision,:published_raw,:published_origin,
              :published_calendar_date,:published_timezone,:published_time_status)
              ON CONFLICT(source_id,canonical_url) DO UPDATE SET
                title=excluded.title,summary=excluded.summary,original_url=excluded.original_url,
                source_item_id=excluded.source_item_id,
                published_at=COALESCE(excluded.published_at,articles.published_at),
                date_status=CASE WHEN excluded.published_at IS NOT NULL THEN excluded.date_status
                                ELSE articles.date_status END,
                last_seen_at=excluded.last_seen_at,content_hash=excluded.content_hash,
                lang=excluded.lang,summary_kind=excluded.summary_kind,content_source=excluded.content_source,
                published_precision=CASE WHEN excluded.published_at IS NOT NULL THEN excluded.published_precision ELSE articles.published_precision END,
                published_raw=CASE WHEN excluded.published_at IS NOT NULL THEN excluded.published_raw ELSE articles.published_raw END,
                published_origin=CASE WHEN excluded.published_at IS NOT NULL THEN excluded.published_origin ELSE articles.published_origin END,
                published_calendar_date=CASE WHEN excluded.published_at IS NOT NULL THEN excluded.published_calendar_date ELSE articles.published_calendar_date END,
                published_timezone=CASE WHEN excluded.published_at IS NOT NULL THEN excluded.published_timezone ELSE articles.published_timezone END,
                published_time_status=CASE WHEN excluded.published_at IS NOT NULL THEN excluded.published_time_status ELSE articles.published_time_status END""",
                         {'lang': 'und', 'summary_kind': 'source_summary', 'content_source': None,
                          'published_precision': 'second', 'published_raw': None, 'published_origin': 'feed',
                          'published_calendar_date': None, 'published_timezone': None, 'published_time_status': 'legacy_unspecified',
                          **record, "first_seen_at": stamp, "last_seen_at": stamp})


def source_state(source_id):
    with connect() as conn:
        return dict(conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone())


def update_source(source_id, *, attempt=False, success=False, error=None, etag=None, modified=None, count=None):
    with connect() as conn:
        if attempt:
            conn.execute("UPDATE sources SET last_attempt_at=? WHERE id=?", (now(), source_id))
        elif success:
            conn.execute("""UPDATE sources SET last_success_at=?,last_error=NULL,last_result='success',retry_after_at=NULL,
                etag=COALESCE(?,etag),last_modified=COALESCE(?,last_modified),
                last_item_count=COALESCE(?,last_item_count) WHERE id=?""", (now(), etag, modified, count, source_id))
        else:
            conn.execute("UPDATE sources SET last_error=?,last_result='failed' WHERE id=?", (str(error)[:300], source_id))


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
    if SOURCES[source_id]['collector_kind'] == 'html':
        from .html_sources import collect_html
        return await collect_html(client, source_id)
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
    try:
        with operation_lock(DB_PATH):
            semaphore = asyncio.Semaphore(2)
            async with httpx.AsyncClient(timeout=15, limits=httpx.Limits(max_connections=2), trust_env=False) as client:
                async def limited(source_id):
                    async with semaphore:
                        return await collect_source(client, source_id)
                enabled = [row['id'] for row in sources_status() if row['enabled']]
                return await asyncio.gather(*(limited(source_id) for source_id in enabled))
    except RuntimeError as error:
        if 'operation lock' not in str(error):
            raise
        return [{'skipped': 'operation_locked'}]


def encode_cursor(row, source, category=None, region=None, geographic_region=None):
    filters = dict(source=source, category=category, region=region, geographic_region=geographic_region)
    return base64.urlsafe_b64encode(json.dumps([row["published_at"] or "", row["id"], filters, 3]).encode()).decode()


def list_articles(source=None, cursor=None, limit=20, category=None, region=None, geographic_region=None,
                  page=None, page_size=None, snapshot=None):
    paged = page is not None or page_size is not None
    if paged:
        if cursor:
            raise ValueError('Page pagination cannot be combined with cursor')
        page = 1 if page is None else page
        limit = limit if page_size is None else page_size
        if type(page) is not int or page < 1 or type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError('Invalid page or page size')
    elif snapshot is not None:
        raise ValueError('Snapshot requires page pagination')
    source, category, region, geographic_region = source or None, category or None, region or None, geographic_region or None
    clauses, args = [], []
    if region:
        if region not in {'domestic', 'international'}:
            raise ValueError('Unknown publisher region')
        if source in SOURCES and SOURCES[source]['region'] != region:
            raise ValueError('Source does not belong to publisher region')
        clauses.append('s.region=?')
        args.append(region)
    if geographic_region:
        if geographic_region not in GEOGRAPHIC_REGIONS:
            raise ValueError('Unknown geographic region')
        if source in SOURCES and SOURCES[source].get('geographic_region') != geographic_region:
            raise ValueError('Source does not belong to geographic region')
        clauses.append('s.geographic_region=?')
        args.append(geographic_region)
    if category:
        if category not in CATEGORIES:
            raise ValueError('Unknown category')
        category_region, kind = CATEGORIES[category]
        if source and source in SOURCES and (SOURCES[source]['publisher_kind'] != kind or
                                              (category_region and SOURCES[source]['region'] != category_region)):
            raise ValueError('Source does not belong to category')
        clauses.append('s.publisher_kind=?')
        args.append(kind)
        if category_region:
            clauses.append('s.region=?')
            args.append(category_region)
    if source:
        if source not in SOURCES:
            raise ValueError("Unknown source")
        clauses.append("a.source_id=?")
        args.append(source)
    if cursor:
        try:
            decoded = json.loads(base64.urlsafe_b64decode(cursor))
            if len(decoded) == 4 and decoded[-1] == 3:
                date, article_id, cursor_filters, version = decoded
                if cursor_filters != dict(source=source, category=category, region=region, geographic_region=geographic_region):
                    raise ValueError()
                cursor_source, cursor_category = source, category
            elif len(decoded) == 3 and not category and not region and not geographic_region:
                date, article_id, cursor_source = decoded
                cursor_category = None
            else:
                date, article_id, cursor_source, cursor_category, version = decoded
                if version != 2 or region or geographic_region:
                    raise ValueError()
            if not isinstance(date, str) or type(article_id) is not int or cursor_source != source or cursor_category != category:
                raise ValueError()
        except Exception as error:
            raise ValueError("Invalid cursor or source mismatch") from error
        clauses.append("(COALESCE(a.published_at,'')<? OR (COALESCE(a.published_at,'')=? AND a.id<?))")
        args.extend([date, date, article_id])
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with connect() as conn:
        if paged:
            conn.execute('BEGIN')
            maximum = conn.execute('SELECT COALESCE(MAX(id),0) FROM articles').fetchone()[0]
            if snapshot is not None and (type(snapshot) is not int or snapshot < 0):
                raise ValueError('Invalid page snapshot')
            snapshot = maximum if snapshot is None else min(snapshot, maximum)
            clauses.append('a.id<=?')
            args.append(snapshot)
            where = ' WHERE ' + ' AND '.join(clauses)
            total = conn.execute('SELECT COUNT(*) FROM articles a JOIN sources s ON a.source_id=s.id' + where, args).fetchone()[0]
            pages = max(1, (total + limit - 1)//limit)
            actual_page = min(page, pages)
            rows = [dict(row) for row in conn.execute('''SELECT a.*,s.name AS source_name,s.region,s.publisher_kind,s.enabled AS source_enabled,
              s.geographic_region,s.country_code FROM articles a JOIN sources s ON a.source_id=s.id''' + where +
              " ORDER BY COALESCE(a.published_at,'') DESC,a.id DESC LIMIT ? OFFSET ?", [*args, limit, (actual_page-1)*limit])]
            return {'items': rows, 'page': actual_page, 'page_size': limit, 'total': total, 'total_pages': pages,
                    'snapshot': snapshot, 'next_cursor': None}
        rows = [dict(row) for row in conn.execute("""SELECT a.*,s.name AS source_name,s.region,s.publisher_kind,s.enabled AS source_enabled,
            s.geographic_region,s.country_code FROM articles a
            JOIN sources s ON a.source_id=s.id""" + where +
            " ORDER BY COALESCE(a.published_at,'') DESC,a.id DESC LIMIT ?", [*args, limit + 1])]
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {"items": rows, "next_cursor": encode_cursor(rows[-1], source, category, region, geographic_region) if has_more else None}


def sources_status():
    with connect() as conn:
        return [dict(row) for row in conn.execute("""SELECT s.id,s.name,s.last_attempt_at,s.last_success_at,
            s.last_error,s.last_item_count,s.collector_kind,s.region,s.publisher_kind,s.enabled,s.last_result,
            s.geographic_region,s.country_code,s.availability_note,
            COUNT(a.id) AS stored_articles
            FROM sources s LEFT JOIN articles a ON a.source_id=s.id GROUP BY s.id ORDER BY s.id""")]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    initialize()
    print(json.dumps(asyncio.run(collect_all()), ensure_ascii=False, indent=2))
