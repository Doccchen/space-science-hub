"""Four publisher-specific parsers derived from the saved server samples."""
import asyncio
import hashlib
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from . import news
from .sources import INTERNATIONAL_COMPANIES

USER_AGENT = 'SpaceScienceNews/0.2 (official-source-reader)'
DETAIL_DELAY = max(1.0, float(os.environ.get('DETAIL_DELAY_SECONDS', '1')))
SELECTORS = {
    'cnsa': dict(list='.cont_ulR .cont_list_li a[href]', title='.wz_title',
                 date='.wz_rq', origin='.wz_ly', body='.wz_conten', remove='.wzdb_gn'),
    'cmse': dict(list='#list li a[href]', title='.wzxq > .title',
                 date='.wzxq .pubDate', origin='.wzxq .source', body='#dochtmlcon', remove='.footer'),
    'cas_space': dict(list='#news-list-con > li .news-item-title a[href]', title='.detail-title',
                      date='.detail-info', origin='.detail-info', body='#content-text', remove=None),
    'landspace': dict(list='.page-news .section-1 .slide-right a[href], .page-news .section-2 a.link[href]',
                      title='.page-news-detail h3.title', date='.page-news-detail .times',
                      origin='.page-news-detail .times', body='.page-news-detail .article', remove=None),
}


class BudgetExceeded(TimeoutError):
    pass


def soup(raw):
    # Server probes: all four HTML pages are UTF-8. Support explicit GB legacy pages.
    if isinstance(raw, bytes):
        try:
            raw = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            raw = raw.decode('gb18030')
    return BeautifulSoup(raw, 'html.parser')


def plain(node, limit=600):
    if node is None:
        return ''
    # Work on a copy because a caller may inspect the original structure later.
    clean = BeautifulSoup(str(node), 'html.parser')
    for el in clean.select('script,style,noscript,iframe,svg,nav,footer'):
        el.decompose()
    return ' '.join(clean.get_text(' ', strip=True).split())[:limit]


def detail_allowed(source_id, url):
    if source_id in INTERNATIONAL_COMPANIES:
        from .international_sources import detail_allowed as international_detail_allowed
        return international_detail_allowed(source_id, url)
    source = news.SOURCES[source_id]
    parts = urlsplit(url)
    if (not news.allowed_url(url, source['domain']) or
            parts.hostname != urlsplit(source['url']).hostname or
            not re.fullmatch(source['detail_pattern'], parts.path)):
        return False
    if source_id == 'landspace':
        query = parse_qs(parts.query)
        return set(query) == {'itemid'} and len(query['itemid']) == 1 and query['itemid'][0].isdigit()
    return not parts.query


def request_allowed(source_id, url):
    if source_id in INTERNATIONAL_COMPANIES:
        from .international_sources import request_allowed as international_request_allowed
        return international_request_allowed(source_id, url)
    source = news.SOURCES[source_id]
    parts = urlsplit(url)
    if not news.allowed_url(url, source['domain']) or parts.hostname != urlsplit(source['url']).hostname:
        return False
    if parts.path == '/robots.txt' and not parts.query:
        return True
    if detail_allowed(source_id, url):
        return True
    if source_id == 'cnsa':
        return bool(re.fullmatch(r'/n6758823/n6758838/(?:index|index_10548744_\d+)\.html', parts.path)) and not parts.query
    if source_id == 'cmse':
        return bool(re.fullmatch(r'/xwzx/zhxw/(?:index(?:_\d+)?\.html)?', parts.path)) and not parts.query
    if source_id == 'cas_space':
        if parts.path == '/list/6.html' and not parts.query:
            return True
        q = parse_qs(parts.query)
        return (parts.path == '/list/ajax' and set(q) == {'page', 'pageSize', 'cid'}
                and q['cid'] == ['16'] and q['pageSize'] == ['9']
                and len(q['page']) == 1 and q['page'][0].isdigit() and int(q['page'][0]) > 0)
    q = parse_qs(parts.query)
    return (parts.path == '/news.html' and set(q) <= {'catid', 'page', 'mao'} and q.get('catid') == ['1']
            and all(len(v) == 1 and v[0].isdigit() for v in q.values()))


def parse_date(value):
    match = re.search(r'(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})(?:日)?(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?', value or '')
    if not match:
        return None, 'missing', 'missing'
    try:
        year, month, day, hour, minute, second = match.groups()
        date = datetime(int(year), int(month), int(day), int(hour or 0), int(minute or 0),
                        int(second or 0), tzinfo=timezone(timedelta(hours=8)))
        precision = 'second' if second else 'minute' if hour else 'day'
        return date.astimezone(timezone.utc).isoformat(timespec='seconds'), precision, 'provided'
    except ValueError:
        return None, 'missing', 'invalid'


def listing_page(source_id, offset, total_pages=None):
    if source_id in INTERNATIONAL_COMPANIES:
        from .international_sources import listing_page as international_listing_page
        return international_listing_page(source_id, offset)
    base = news.SOURCES[source_id]['url']
    if source_id == 'cas_space':
        return f'https://www.cas-space.com/list/ajax?page={offset + 1}&pageSize=9&cid=16'
    if not offset:
        return base
    if source_id == 'cnsa':
        if not total_pages or offset >= total_pages:
            raise ValueError('CNSA pagination requires current page count')
        return urljoin(base, f'index_10548744_{total_pages - offset}.html')
    if source_id == 'cmse':
        return urljoin(base, f'index_{offset}.html')
    return f'https://www.landspace.com/news.html?catid=1&page={offset + 1}'


def parse_listing(source_id, raw, url, known_total=None):
    if source_id in INTERNATIONAL_COMPANIES:
        from .international_sources import parse_listing as international_parse_listing
        return international_parse_listing(source_id, raw, url)
    if source_id == 'cas_space' and urlsplit(url).path == '/list/ajax':
        payload = json.loads(raw)
        data = payload.get('data', {})
        if payload.get('code') != 200 or not isinstance(data.get('rows'), list) or type(data.get('total')) is not int:
            raise ValueError('CAS pagination response structure changed')
        items = []
        for row in data['rows']:
            # Even domain-local media copies are excluded by the cid boundary.
            if row.get('cid') != 16 or row.get('url'):
                continue
            if type(row.get('id')) is not int or not row.get('title'):
                raise ValueError('CAS news record structure changed')
            detail = urljoin(news.SOURCES[source_id]['url'], f"/article/{row['id']}.html")
            items.append(dict(url=detail, title=news.text(row['title'], 400),
                              summary=news.text(row.get('description'), 600), list_date=row.get('updateTime', '')))
        if data['rows'] and not items:
            raise ValueError('CAS page contained no acceptable company news')
        return items, max(1, (data['total'] + 8) // 9)
    tree = soup(raw)
    anchors = tree.select(SELECTORS[source_id]['list'])
    if not anchors:
        raise ValueError(f'{source_id}: reviewed list selector returned no entries')
    items = {}
    for anchor in anchors:
        detail = urljoin(url, anchor['href'])
        if not detail_allowed(source_id, detail):
            continue
        title = anchor.get('title') or plain(anchor, 400)
        summary = ''
        if source_id == 'cnsa':
            summary = plain(anchor.select_one('.ejlist_cont_wz.pc'))
        elif source_id == 'cas_space':
            summary = plain(anchor.find_parent('li').select_one('.abs-text'))
        elif source_id == 'landspace':
            title_node = anchor.select_one('h4')
            if title_node:
                title = plain(title_node, 400)
            if anchor.get_text(strip=True).startswith('Learn more'):
                continue
        if title:
            items.setdefault(news.canonical_url(detail), dict(url=detail, title=title, summary=summary, list_date=''))
    if not items:
        raise ValueError('List contained no acceptable news links')
    html = str(tree)
    if source_id == 'cnsa':
        values = [int(value) for value in re.findall(r'maxPageNum\s*=\s*(\d+)', html)]
        total = max(values) if values else known_total
        if not total:
            raise ValueError('CNSA pagination metadata missing')
    elif source_id == 'cmse':
        count = re.search(r'countPage\s*=\s*(\d+)', html)
        if not count:
            raise ValueError('CMSE pagination metadata missing')
        total = int(count.group(1))
    elif source_id == 'landspace':
        count = re.search(r'goPage\(\s*\d+\s*,\s*(\d+)\s*,', html)
        if not count:
            raise ValueError('LandSpace pagination metadata missing')
        total = int(count.group(1))
    else:
        total = None  # HTML homepage isn't used for CAS historical pagination.
    return list(items.values()), total


def parse_detail(source_id, raw, listing):
    if source_id in INTERNATIONAL_COMPANIES:
        from .international_sources import parse_detail as international_parse_detail
        return international_parse_detail(source_id, raw, listing)
    if not detail_allowed(source_id, listing['url']):
        raise ValueError('Unapproved news detail URL')
    tree = soup(raw)
    cfg = SELECTORS[source_id]
    heading, body = tree.select_one(cfg['title']), tree.select_one(cfg['body'])
    if heading is None or body is None:
        raise ValueError(f'{source_id}: reviewed detail structure missing')
    title = plain(heading, 400)
    if not title:
        raise ValueError('Detail title missing')
    if cfg['remove']:
        for node in body.select(cfg['remove']):
            node.decompose()
    if source_id == 'cas_space':
        metadata = tree.select('.detail-info > div')
        date_node = next((node for node in metadata if re.match(r'^发布时间\s*[:：]', plain(node, 150))), None)
        source_node = next((node for node in metadata if re.match(r'^(?:文章来源|来源)\s*[:：]', plain(node, 200))), None)
        date_raw = plain(date_node, 150)
        origin = plain(source_node, 200)
    else:
        date_raw = plain(tree.select_one(cfg['date']), 150)
        origin = plain(tree.select_one(cfg['origin']), 200) if cfg['origin'] else ''
    date, precision, status = parse_date(date_raw)
    origin_match = re.search(r'(?:文章来源|信息来源|来源)\s*[:：]\s*(.+)', origin)
    origin = origin_match.group(1).strip() if origin_match else ''
    summary = listing.get('summary') or plain(body)
    return dict(source_id=source_id, source_item_id=listing['url'], original_url=listing['url'],
                canonical_url=news.canonical_url(listing['url']), title=title, summary=summary,
                published_at=date, date_status=status, lang='zh', published_precision=precision,
                published_raw=date_raw or None, published_origin='detail' if date_raw else 'missing',
                published_calendar_date=datetime.fromisoformat(date).astimezone(timezone(timedelta(hours=8))).date().isoformat() if date else None,
                published_timezone='Asia/Shanghai' if date else None,
                published_time_status='date_only' if precision == 'day' else 'provided' if date else 'missing',
                summary_kind=('source_summary' if listing.get('summary') else 'body_excerpt') if summary else 'none',
                content_source=origin or None, content_hash=hashlib.sha256((title + '\n' + summary).encode()).hexdigest())


class PublisherHTTP:
    def __init__(self, client, source_id):
        self.client, self.source_id = client, source_id
        self.last_request = None
        self.request_count = 0
        self.robots = None
        self.robots_state = 'unchecked'
        self.deadline = None
        self.delay = DETAIL_DELAY
        self.robots_by_host = {}
        self.robots_states = {}
        self.delays_by_host = {}
        self.last_url = None

    async def get(self, url, *, robots=False):
        if self.deadline is None:
            return await self._get_retry(url, robots=robots)
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise BudgetExceeded('Backfill time budget exhausted')
        try:
            return await asyncio.wait_for(self._get_retry(url, robots=robots), timeout=remaining)
        except asyncio.TimeoutError as error:
            raise BudgetExceeded('Backfill time budget exhausted') from error

    async def _get_retry(self, url, *, robots=False):
        for attempt in range(2):
            try:
                return await self._get(url, robots=robots)
            except httpx.HTTPStatusError as error:
                if error.response.status_code == 429:
                    retry = error.response.headers.get('retry-after', '3600')
                    try:
                        until = (datetime.now(timezone.utc) + timedelta(seconds=max(1, int(retry)))) if retry.isdigit() else parsedate_to_datetime(retry)
                    except (ValueError, TypeError):
                        until = datetime.now(timezone.utc) + timedelta(hours=1)
                    with news.connect() as conn:
                        conn.execute('UPDATE sources SET retry_after_at=? WHERE id=?',
                                     (until.astimezone(timezone.utc).isoformat(timespec='seconds'), self.source_id))
                    raise
                if error.response.status_code < 500 or attempt:
                    raise
            except httpx.TransportError:
                if attempt:
                    raise
            await asyncio.sleep(2)

    async def _get(self, url, *, robots=False):
        for _ in range(4):
            parts = urlsplit(url)
            source = news.SOURCES[self.source_id]
            # Captured LandSpace robots redirects to its own homepage. Inspect
            # that response only for robots discovery; never allow news traversal there.
            robots_home = (robots and self.source_id == 'landspace' and parts.path in {'/', '/index.html'}
                           and not parts.query and news.allowed_url(url, source['domain'])
                           and parts.hostname == urlsplit(source['url']).hostname)
            if not request_allowed(self.source_id, url) and not robots_home:
                raise ValueError('Request/redirect left reviewed publisher paths')
            host = urlsplit(url).netloc
            if not robots and self.source_id in INTERNATIONAL_COMPANIES and host not in self.robots_by_host:
                await self.check_robots(url)
            policy = self.robots_by_host.get(host, self.robots if self.source_id not in INTERNATIONAL_COMPANIES else None)
            if not robots and policy is not None and not policy.can_fetch(USER_AGENT, url):
                raise ValueError('Publisher robots.txt disallows this URL')
            if self.last_request is not None:
                await asyncio.sleep(max(0, self.delays_by_host.get(host, self.delay) - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            self.request_count += 1
            async with self.client.stream('GET', url, headers={'User-Agent': USER_AGENT}, follow_redirects=False) as response:
                if robots and response.status_code == 404:
                    self.last_url = str(response.url)
                    return b''
                if response.is_redirect:
                    url = str(response.url.join(response.headers['location']))
                    continue
                response.raise_for_status()
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > news.MAX_FEED_BYTES:
                        raise ValueError('Publisher response exceeds maximum size')
                self.last_url = str(response.url)
                return bytes(raw)
        raise ValueError('Too many publisher redirects')

    async def check_robots(self, target=None):
        base = target or news.SOURCES[self.source_id]['url']
        host = urlsplit(base).netloc
        url = urljoin(base, '/robots.txt')
        raw = await self.get(url, robots=True)
        self.robots_state = ('missing_or_empty' if not raw else 'html_response_no_rules'
                             if re.search(br'<(?:!doctype|html)', raw[:200], re.I) else 'parsed')
        self.robots = RobotFileParser()
        self.robots.parse([] if self.robots_state == 'html_response_no_rules' else raw.decode('utf-8-sig').splitlines())
        self.robots_by_host[host] = self.robots
        self.robots_states[host] = self.robots_state
        crawl_delay = self.robots.crawl_delay(USER_AGENT)
        self.delays_by_host[host] = max(DETAIL_DELAY, float(crawl_delay or 0))


async def collect_html(client, source_id):
    state = news.source_state(source_id)
    if state['retry_after_at'] and state['retry_after_at'] > news.now():
        return {'source': source_id, 'skipped': 'retry_after'}
    news.update_source(source_id, attempt=True)
    fetcher = PublisherHTTP(client, source_id)
    failed, accepted, skipped = [], 0, 0
    started = time.monotonic()
    try:
        await fetcher.check_robots()
        url = listing_page(source_id, 0)
        items, _ = parse_listing(source_id, await fetcher.get(url), url)
        for item in items[:10]:
            with news.connect() as conn:
                existing = conn.execute('SELECT title,summary,last_seen_at FROM articles WHERE source_id=? AND canonical_url=?',
                                        (source_id, news.canonical_url(item['url']))).fetchone()
            # Periodically re-check detail corrections, without fetching every known URL each hour.
            unchanged_listing = existing and re.sub(r'\s+', '', existing['title']) == re.sub(r'\s+', '', item['title']) and (
                not item.get('summary') or existing['summary'] == item['summary'])
            if unchanged_listing and existing['last_seen_at'] > (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec='seconds'):
                skipped += 1
                continue
            try:
                raw = await fetcher.get(item['url'])
                record = parse_detail(source_id, raw, {**item, 'resolved_url': fetcher.last_url})
                news.store_records([record])
                accepted += 1
            except Exception as error:
                failed.append({'url': item['url'], 'error': str(error)[:300]})
                if isinstance(error, httpx.HTTPStatusError) and error.response.status_code == 429:
                    break
        if failed:
            news.update_source(source_id, error=f'{len(failed)} detail requests failed: {failed[0]["error"]}')
            if accepted or skipped:
                with news.connect() as conn:
                    conn.execute("UPDATE sources SET last_result='partial' WHERE id=?", (source_id,))
        else:
            news.update_source(source_id, success=True, count=len(items[:10]))
        return {'source': source_id, 'accepted': accepted, 'skipped': skipped, 'failures': failed,
                'result': ('partial' if accepted or skipped else 'failed') if failed else 'success', 'requests': fetcher.request_count,
                'seconds': round(time.monotonic() - started, 2)}
    except Exception as error:
        news.update_source(source_id, error=f'{type(error).__name__}: {error}')
        return {'source': source_id, 'error': str(error), 'requests': fetcher.request_count}
