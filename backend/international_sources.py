"""First-batch official company adapters, verified against server responses."""
import hashlib
import html
import json
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from . import news
from .publication import publication_fields

HOSTS = {
    'spacex': {'www.spacex.com', 'spacex.com'},
    'blue_origin': {'www.blueorigin.com', 'blueorigin.com'},
    'arianespace': {'www.arianespace.com', 'arianespace.com', 'newsroom.arianespace.com'},
    'ispace': {'www.ispace-inc.com', 'ispace-inc.com'},
    'skyroot': {'www.skyroot.in','skyroot.in'},
    'gilmour': {'www.gspace.com','gspace.com'},
}
SUPPORTED = {'arianespace', 'ispace', 'gilmour'}


def host_allowed(source_id, url):
    try:
        parts = urlsplit(url)
        return (parts.scheme in {'http', 'https'} and parts.hostname in HOSTS[source_id]
                and not parts.username and not parts.password and parts.port in {None, 80, 443})
    except ValueError:
        return False


def detail_allowed(source_id, url):
    if not host_allowed(source_id, url):
        return False
    p = urlsplit(url)
    query = parse_qs(p.query, keep_blank_values=True)
    if source_id == 'arianespace':
        if p.hostname != 'newsroom.arianespace.com':
            return False
        if p.path == '/':
            return set(query) == {'p'} and len(query['p']) == 1 and query['p'][0].isdigit()
        reserved = {'en', 'fr', 'login', 'dashboard', 'contact', 'terms-and-conditions'}
        return (not query and p.path.strip('/') not in reserved
                and bool(re.fullmatch(r'/[a-z0-9][a-z0-9-]+/?', p.path)))
    if source_id == 'ispace':
        return not query and bool(re.fullmatch(r'/\d{4}/\d{2}/\d{2}/[a-z0-9][a-z0-9-]+/?', p.path))
    if source_id == 'blue_origin':
        return not query and bool(re.fullmatch(r'/news/[a-z0-9][a-z0-9-]+/?', p.path))
    if source_id == 'skyroot':
        return not query and bool(re.fullmatch(r'/(?:newsroom|news|press-release)/[a-z0-9][a-z0-9-]+/?', p.path))
    if source_id == 'gilmour':
        return not query and bool(re.fullmatch(r'/post/[a-z0-9][a-z0-9-]+/?', p.path))
    # SpaceX missions and planned launch dates are not news publication metadata.
    return not query and bool(re.fullmatch(r'/updates/[a-z0-9][a-z0-9-]+/?', p.path))


def request_allowed(source_id, url):
    if not host_allowed(source_id, url):
        return False
    p = urlsplit(url)
    if p.path == '/robots.txt' and not p.query:
        return True
    if detail_allowed(source_id, url):
        return True
    entries = {'spacex': {'/updates/', '/updates'}, 'blue_origin': {'/news', '/news/'},
               'arianespace': {'/updates-en/', '/updates-en'}, 'ispace': {'/news/', '/news'},
               'skyroot': {'/newsroom','/newsroom/'}, 'gilmour': {'/update','/update/'}}
    primary = urlsplit(news.SOURCES[source_id]['url']).hostname
    return p.hostname == primary and not p.query and p.path in entries[source_id]


def listing_page(source_id, offset):
    if offset:
        raise ValueError('International company deep historical traversal is not enabled')
    return news.SOURCES[source_id]['url']


def parse_listing(source_id, raw, url):
    from .html_sources import plain, soup
    if source_id not in SUPPORTED:
        raise ValueError(f'{source_id}: no verified official news payload; source must remain disabled')
    tree = soup(raw)
    result = {}
    if source_id == 'arianespace':
        nodes = tree.select('a.ct--CardNews__inner, a.ct--CardHighlightedNews__inner')
        for node in nodes:
            category = node.select_one('[class$="__category"]')
            if plain(category) != 'Press Releases':
                continue
            link = urljoin(url, node.get('href', ''))
            title = plain(node.select_one('[class$="__title"]'), 400)
            if title and detail_allowed(source_id, link):
                list_date = plain(node.select_one('[class$="__date"]'), 150)
                result.setdefault(news.canonical_url(link), dict(url=link, title=title, summary='', list_date=list_date))
    elif source_id == 'ispace':
        nodes = tree.select('#posts-wrapper .card-list-item')
        for node in nodes:
            anchor = node.select_one('a[href]')
            # The inspected card title lives in its second direct column.
            columns = node.find_all('div', recursive=False)
            title = plain(columns[1], 400) if len(columns) >= 2 else ''
            if anchor is None:
                continue
            link = urljoin(url, anchor['href'])
            if title and detail_allowed(source_id, link):
                result.setdefault(news.canonical_url(link), dict(url=link, title=title, summary='', list_date=''))
    elif source_id == 'gilmour':
        for node in tree.select('[data-hook="post-list-item"]'):
            title_node = node.select_one('[data-hook="post-list-item__title"]')
            anchor = title_node.find_parent('a') if title_node else None
            if anchor is None or not anchor.get('href'):
                continue
            link = urljoin(url, anchor['href'])
            title = plain(title_node, 400)
            if title and detail_allowed(source_id, link):
                result.setdefault(news.canonical_url(link), dict(url=link,title=title,summary='',list_date=''))
    if not result:
        raise ValueError(f'{source_id}: reviewed official-news list structure returned no entries')
    # No archive completeness claim: this round intentionally reads only the newest ten.
    items = list(result.values())
    if source_id == 'arianespace':
        items.sort(key=lambda item: publication_fields(item['list_date'], date_order='dmy')['published_at'] or '', reverse=True)
    return items[:10], None


def article_metadata(tree, heading):
    """Only schema Article objects whose headline matches the actual page heading."""
    from .html_sources import plain
    def identity(value):
        return re.sub(r'\s+', ' ', html.unescape(plain(value, 400))).translate(
            str.maketrans({'’': "'", '‘': "'", '“': '"', '”': '"'})).strip()
    expected = identity(heading)
    for script in tree.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(script.get_text())
        except (ValueError, TypeError):
            continue
        nodes = value if isinstance(value, list) else value.get('@graph', [value]) if isinstance(value, dict) else []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            kind = node.get('@type')
            kinds = kind if isinstance(kind, list) else [kind]
            if not any(isinstance(item, str) and item in {'Article', 'NewsArticle', 'BlogPosting'} for item in kinds):
                continue
            if identity(node.get('headline')) == expected:
                return node
    return {}


def parse_detail(source_id, raw, listing):
    from .html_sources import plain, soup
    if source_id not in SUPPORTED:
        raise ValueError(f'{source_id}: official payload not verified')
    actual = listing.get('resolved_url') or listing['url']
    if not detail_allowed(source_id, actual):
        raise ValueError('Unapproved international company detail URL')
    tree = soup(raw)
    if source_id == 'arianespace':
        root = tree.select_one('.single__arianeSpace')
        heading = root.select_one('.single__arianeSpace--banner h1') if root else None
        body = root.select_one('#post-content.entry-content') if root else None
    elif source_id == 'ispace':
        root = tree.select_one('main article.type-post')
        heading = root.select_one('.entry-header h1.entry-title') if root else None
        body = root.select_one('.entry-content') if root else None
    else:
        root = tree
        heading = tree.select_one('h1[data-hook="post-title"]')
        paragraphs = tree.select('p[data-ricos-paragraph]')
        body = tree.new_tag('div') if paragraphs else None
        for paragraph in paragraphs:
            body.append(paragraph)
    if heading is None or body is None:
        raise ValueError(f'{source_id}: reviewed article structure missing')
    title = plain(heading, 400)
    if not title:
        raise ValueError('Company news title is empty')
    schema = article_metadata(tree, title)
    if source_id == 'arianespace' and 'Press Releases' not in schema.get('articleSection', []):
        raise ValueError('Arianespace record is not a reviewed press release')
    meta = tree.select_one('meta[property="article:published_time"]')
    time_node = root.select_one('.entry-header time.entry-date')
    if meta and meta.get('content'):
        raw_date, origin = meta['content'], 'detail.meta.article:published_time'
    elif time_node and time_node.get('datetime'):
        raw_date, origin = time_node['datetime'], 'detail.time.datetime'
    else:
        raw_date, origin = schema.get('datePublished'), 'detail.schema.datePublished'
    date = publication_fields(raw_date, date_order='mdy' if source_id == 'ispace' else 'dmy', origin=origin)
    canonical = tree.select_one('link[rel="canonical"][href]')
    canonical_url = urljoin(actual, canonical['href']) if canonical else actual
    if not detail_allowed(source_id, canonical_url):
        raise ValueError('Declared canonical URL left the reviewed company news scope')
    language = schema.get('inLanguage') or (tree.html.get('lang') if tree.html else None) or 'und'
    language = str(language).split('-')[0].lower()
    language = {'eng': 'en', 'jpn': 'ja', 'fra': 'fr', 'deu': 'de'}.get(language, language)
    if not re.fullmatch(r'[a-z]{2,3}', language):
        language = 'und'
    author = schema.get('author')
    author_name = author.get('name') if isinstance(author, dict) else author if isinstance(author, str) else None
    summary = plain(body)
    return dict(source_id=source_id, source_item_id=canonical_url,
                original_url=actual, canonical_url=news.canonical_url(canonical_url), title=title,
                summary=summary, lang=language, content_source=plain(author_name, 200) or None,
                summary_kind='body_excerpt' if summary else 'none',
                content_hash=hashlib.sha256((title + '\n' + summary).encode()).hexdigest(), **date)
