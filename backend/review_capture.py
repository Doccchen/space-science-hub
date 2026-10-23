"""Capture a private draft from a fixed government article; never auto-authorize."""
import hashlib
import re
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup
from . import news
from .html_sources import SELECTORS
from .publisher_fetch import Publisher, checked_url


def text_and_links(node, base_url, *, table=False):
    """Keep publisher link ranges alongside plain text; never persist source HTML."""
    parts, links, length, previous_anchor = [], [], 0, None
    for string in node.find_all(string=True):
        # Match BeautifulSoup.get_text's default exclusion of comments/script strings.
        if type(string) not in node.MAIN_CONTENT_STRING_TYPES:
            continue
        text = str(string).strip() if table else str(string)
        if table and not text:
            continue
        separator = ' ' if table and parts else ''
        parts.append(separator + text); length += len(separator)
        anchor = string.find_parent('a')
        href = str(anchor.get('href', '')) if anchor else ''
        try:
            target = urljoin(base_url, href) if href else ''
            parsed = urlsplit(target)
            safe = (parsed.scheme in {'http', 'https'} and parsed.hostname and not parsed.username
                    and not parsed.password and not re.search(r'[\s\x00-\x1f\x7f\\]', target))
        except ValueError:
            safe = False
        if safe and text:
            if anchor is previous_anchor and links and links[-1]['url'] == target:
                links[-1]['end'] = length + len(text)
            else:
                links.append({'start': length, 'end': length + len(text), 'url': target})
        length += len(text); previous_anchor = anchor if safe else None
    raw = ''.join(parts)
    offset = len(raw) - len(raw.lstrip())
    text = raw.strip()
    adjusted = []
    for link in links:
        start, end = max(0, link['start'] - offset), min(len(text), link['end'] - offset)
        if start < end:
            adjusted.append({**link, 'start': start, 'end': end})
    return text, adjusted


def parse(source, url, raw, actor, *, strict=False):
    try:
        html = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        html = raw.decode('gb18030')
    tree = BeautifulSoup(html, 'html.parser')
    root = tree.select_one('article .entry-content' if source == 'nasa' else SELECTORS[source]['body'])
    if root is None:
        raise ValueError('Reviewed article structure missing')
    if source == 'cmse':
        editor = root.select_one('.TRS_Editor')
        if editor is not None:
            # The current publisher wraps each text paragraph in a leaf div.
            # Keep editorial credits outside this content boundary out of the body.
            root = editor
    for node in root.select('script,style,nav,footer,noscript,form'):
        node.decompose()
    if source != 'nasa' and SELECTORS[source].get('remove'):
        for node in root.select(SELECTORS[source]['remove']):
            node.decompose()
    if source == 'cmse' and root.get('class') and 'TRS_Editor' in root['class']:
        for node in root.find_all('div'):
            if node.find(['div','p','h1','h2','h3','h4','h5','h6','ul','ol','table',
                          'section','article','blockquote','iframe','svg','math','canvas']) is None:
                node.name = 'p'
    if source == 'nasa':
        for node in root.select('.image-details-toggle-button svg[aria-hidden="true"], .hds-file-list-download a[download] svg[aria-hidden="true"]'):
            # Only the publisher's observed decorative control icons, never a diagram.
            if node.find(['text','title','desc','foreignobject']) is None:
                node.decompose()
    warnings = bool(root.select('iframe,svg,math,canvas'))
    blocks, candidates = [], []
    for node in root.find_all(['p', 'h2', 'h3', 'h4', 'ul', 'ol', 'table', 'img']):
        if node.name == 'img':
            original = urljoin(url, node.get('src') or '')
            try:
                checked_url(source, original, image=True)
            except ValueError:
                continue
            figure = node.find_parent(class_='hds-media') or node.find_parent('figure') or node.parent
            caption = figure.select_one('.hds-caption-text') or figure.find('figcaption')
            credit = figure.select_one('.hds-credits')
            candidates.append({'source_url': original, 'caption': caption.get_text(' ', strip=True)[:2000] if caption else node.get('alt', '')[:2000],
                               'extracted_credit': credit.get_text(' ', strip=True)[:1000] if credit else '', 'block_index': len(blocks)})
            continue
        if node.find_parent(['p', 'ul', 'ol', 'table', 'figure', 'figcaption']) is not None:
            continue
        for br in node.find_all('br'):
            br.replace_with('\n')
        if node.name in {'ul', 'ol'}:
            entries = [text_and_links(li, url) for li in node.find_all('li', recursive=False)]
            items = [text for text, _ in entries]
            if items:
                block = {'type': 'list', 'items': items, 'ordered': node.name == 'ol'}
                links = [{**link, 'item': index} for index, (_, entries_links) in enumerate(entries) for link in entries_links]
                if links:
                    block['links'] = links
                blocks.append(block)
        elif node.name == 'table':
            entries = [[text_and_links(cell, url, table=True) for cell in tr.find_all(['th', 'td'], recursive=False)] for tr in node.find_all('tr')]
            rows = [[text for text, _ in row] for row in entries]
            if any(node.select('[rowspan],[colspan]')):
                warnings = True
            if rows and any(cell for row in rows for cell in row):
                block = {'type': 'table', 'rows': rows}
                links = [{**link, 'row': r, 'column': c} for r, row in enumerate(entries) for c, (_, cell_links) in enumerate(row) for link in cell_links]
                if links:
                    block['links'] = links
                blocks.append(block)
        else:
            value, links = text_and_links(node, url)
            if value:
                block = {'type': 'heading' if node.name.startswith('h') else 'paragraph', 'text': value}
                if block['type'] == 'heading':
                    block['level'] = int(node.name[1])
                if links:
                    block['links'] = links
                blocks.append(block)
    if not blocks or len(candidates) > 10:
        raise ValueError('Empty or oversized draft')
    if strict:
        if warnings:
            raise ValueError('Unsupported article structure; keeping original link')
        comparison = BeautifulSoup(str(root), 'html.parser')
        for node in comparison.select('figure,figcaption,.hds-media,.edit-post-link'):
            node.decompose()
        original_text = re.sub(r'\s+', '', comparison.get_text())
        rendered = ''.join(block.get('text', '') if block['type'] in {'paragraph', 'heading'} else
                           ''.join(block['items']) if block['type'] == 'list' else ''.join(''.join(row) for row in block['rows'])
                           for block in blocks)
        if original_text != re.sub(r'\s+', '', rendered):
            raise ValueError('Parser did not cover all article text; keeping original link')
    language_node = root if root.get('lang') else root.find_parent(attrs={'lang': True})
    declared_language = str(language_node.get('lang', '') if language_node else '').replace('_', '-').split('-')[0].lower()
    language = declared_language if re.fullmatch(r'[a-z]{2,3}', declared_language) else 'und'
    author = tree.select_one("meta[name='parsely-author']")
    credit = news.SOURCES[source]['name']
    if author and author.get('content'):
        credit += ' / ' + author['content'].strip()[:500]
    if source != 'nasa' and SELECTORS[source].get('origin'):
        origin = tree.select_one(SELECTORS[source]['origin'])
        if origin:
            credit += ' / ' + origin.get_text(' ', strip=True)[:500]
    document = {'original_url': url, 'mode': 'full', 'language': language,
                'blocks': blocks, 'permissions': {key: {'status': 'pending'} for key in ('text', 'image', 'translation', 'ai_context')},
                'credit': credit, 'reviewed_at': news.now(), 'reviewer': actor,
                'completeness': 'complete_checked', 'source_sha256': hashlib.sha256(raw).hexdigest(),
                'notes': '待人工核对完整性与许可；图片需独立审核。' + (' 原文含特殊结构，请逐项确认没有遗漏。' if warnings else '')}
    # completeness is a format value; capture never creates an allowed permission.
    return document, candidates


def capture(item, actor, *, strict=False):
    client = Publisher(item['source_id'])
    raw, mime = client.get(item['original_url'])
    if mime not in {'text/html', 'application/xhtml+xml'}:
        raise ValueError('Publisher did not return HTML')
    document, candidates = parse(item['source_id'], item['original_url'], raw, actor, strict=strict)
    if document['language'] == 'und' and re.fullmatch(r'[a-z]{2,3}', str(item.get('lang', ''))) and item['lang'] != 'und':
        document['language'] = item['lang']
    return document, candidates
