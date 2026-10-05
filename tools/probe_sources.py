"""Read-only server probe. Uses the existing container's standard library only."""
import hashlib
import json
import re
import tarfile
import time
import urllib.request
import urllib.error
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

SITES = {
    'cnsa': ('https://www.cnsa.gov.cn/n6758823/n6758838/index.html', r'/n6758823/n6758838/c\d+/content\.html$'),
    'cmse': ('https://www.cmse.gov.cn/xwzx/zhxw/', r'/xwzx/(?:zhxw/)?\d{6}/t\d+_\d+\.html$'),
    'cas_space': ('https://www.cas-space.com/list/6.html', r'/article/\d+\.html$'),
    'landspace': ('https://www.landspace.com/news.html?catid=1&mao=1', r'/news-detail\.html$'),
}
ROOT = Path('/data/source-probes')
ROOT.mkdir(parents=True, exist_ok=True)
ROBOTS = {}


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.scripts = [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a' and attrs.get('href'):
            self.links.append(attrs['href'])
        if tag == 'script' and attrs.get('src'):
            self.scripts.append(attrs['src'])


def allowed(url, host):
    parts = urlsplit(url)
    return (parts.scheme in {'http', 'https'} and parts.hostname == host
            and not parts.username and not parts.password and parts.port in {None, 80, 443})


class Redirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, host):
        self.host = host

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed(newurl, self.host):
            raise ValueError('Redirect left approved host')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, host, path):
    if not allowed(url, host):
        raise ValueError('URL left approved host')
    if urlsplit(url).path != '/robots.txt' and host in ROBOTS and not ROBOTS[host].can_fetch('SpaceScienceNews', url):
        raise ValueError('Publisher robots.txt disallows this probe URL')
    started = time.monotonic()
    req = urllib.request.Request(url, headers={'User-Agent': 'SpaceScienceNews/0.2 (official-source-probe)'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), Redirects(host))
    with opener.open(req, timeout=15) as response:
        raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError('Response too large')
        path.write_bytes(raw)
        meta = {'url': url, 'final_url': response.url, 'status': response.status,
                'content_type': response.headers.get('Content-Type'), 'bytes': len(raw),
                'sha256': hashlib.sha256(raw).hexdigest(), 'seconds': round(time.monotonic() - started, 2),
                'file': str(path.relative_to(ROOT))}
        return raw, meta


report = {}
for source, (url, pattern) in SITES.items():
    folder = ROOT / source
    folder.mkdir(exist_ok=True)
    result = {'samples': [], 'errors': []}
    host = urlsplit(url).hostname
    try:
        try:
            robot_raw, meta = fetch(urljoin(url, '/robots.txt'), host, folder / 'robots.txt')
            result['samples'].append(meta)
            policy = RobotFileParser()
            policy.parse(robot_raw.decode('utf-8-sig').splitlines())
            ROBOTS[host] = policy
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
            result['robots_state'] = '404_not_provided'
        raw, meta = fetch(url, host, folder / 'list.html')
        result['samples'].append(meta)
        parser = Links()
        parser.feed(raw.decode('utf-8', errors='replace'))
        urls = list(dict.fromkeys(urljoin(url, href) for href in parser.links
                                 if re.search(pattern, urlsplit(urljoin(url, href)).path)
                                 and allowed(urljoin(url, href), host)))
        result['discovered_details'] = len(urls)
        for number, detail in enumerate(urls[:3]):
            try:
                time.sleep(1)
                _, meta = fetch(detail, host, folder / f'detail-{number}.html')
                result['samples'].append(meta)
            except Exception as error:
                result['errors'].append({'url': detail, 'error': str(error)})
        # Read only same-host site scripts to identify official pagination.
        scripts = list(dict.fromkeys(urljoin(url, src) for src in parser.scripts
                                    if allowed(urljoin(url, src), host)))
        for number, script in enumerate(scripts[-6:]):
            try:
                time.sleep(1)
                _, meta = fetch(script, host, folder / f'script-{number}.js')
                result['samples'].append(meta)
            except Exception as error:
                result['errors'].append({'url': script, 'error': str(error)})
        text = raw.decode('utf-8', errors='replace')
        history = []
        if source == 'cnsa':
            values = [int(x) for x in re.findall(r'maxPageNum\s*=\s*(\d+)', text)]
            if values:
                maximum = max(values)
                history = [urljoin(url, f'index_10548744_{maximum-offset}.html') for offset in (1, 2) if maximum > offset]
        elif source == 'cmse':
            history = [urljoin(url, f'index_{offset}.html') for offset in (1, 2)]
        elif source == 'cas_space':
            history = ['https://www.cas-space.com/list/ajax?page=1&pageSize=9&cid=16',
                       'https://www.cas-space.com/list/ajax?page=2&pageSize=9&cid=16']
        else:
            history = ['https://www.landspace.com/news.html?catid=1&page=2',
                       'https://www.landspace.com/news.html?catid=1&page=3']
        extra = [urljoin(url, '/robots.txt'), *history]
        historical_details = []
        for number, extra_url in enumerate(extra):
            try:
                time.sleep(1)
                extra_raw, meta = fetch(extra_url, host, folder / f'extra-{number}.html')
                result['samples'].append(meta)
                if number > 0 and source != 'cas_space':
                    page_parser = Links()
                    page_parser.feed(extra_raw.decode('utf-8', errors='replace'))
                    historical_details.extend(urljoin(extra_url, href) for href in page_parser.links
                                              if re.search(pattern, urlsplit(urljoin(extra_url, href)).path)
                                              and allowed(urljoin(extra_url, href), host))
                elif number > 0:
                    data = json.loads(extra_raw)
                    historical_details.extend(urljoin(url, f"/article/{row['id']}.html")
                                              for row in data.get('data', {}).get('rows', [])
                                              if row.get('cid') == 16 and type(row.get('id')) is int and not row.get('url'))
            except Exception as error:
                result['errors'].append({'url': extra_url, 'error': str(error)})
        historical_details = [u for u in dict.fromkeys(historical_details) if u not in urls]
        for number, detail in enumerate(historical_details[:3]):
            try:
                time.sleep(1)
                _, meta = fetch(detail, host, folder / f'history-detail-{number}.html')
                result['samples'].append(meta)
            except Exception as error:
                result['errors'].append({'url': detail, 'error': str(error)})
    except Exception as error:
        result['errors'].append({'url': url, 'error': str(error)})
    report[source] = result

(ROOT / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
with tarfile.open('/data/source-probes.tar.gz', 'w:gz') as archive:
    archive.add(ROOT, arcname='source-probes')
print(json.dumps(report, ensure_ascii=False, indent=2))
