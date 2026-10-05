"""Read-only first-batch official source investigation; no DB/config changes."""
import argparse
import hashlib
import json
import re
import tarfile
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

SITES = {
    'spacex': dict(url='https://www.spacex.com/updates/', hosts={'www.spacex.com', 'spacex.com'},
                   detail=r'/(?:updates|stories)/[^/]+/?'),
    'blue_origin': dict(url='https://www.blueorigin.com/news', hosts={'www.blueorigin.com', 'blueorigin.com'},
                        detail=r'/news/[^/]+/?'),
    'arianespace': dict(url='https://www.arianespace.com/updates-en/',
                        hosts={'www.arianespace.com', 'arianespace.com', 'newsroom.arianespace.com'}, detail=r'/[^/]+/?'),
    'ispace': dict(url='https://www.ispace-inc.com/news/', hosts={'www.ispace-inc.com', 'ispace-inc.com'},
                   detail=r'/\d{4}/\d{2}/\d{2}/[^/]+/?'),
    'skyroot': dict(url='https://www.skyroot.in/newsroom', hosts={'www.skyroot.in','skyroot.in'},
                   detail=r'/(?:newsroom|news|press-release)/[^/]+/?'),
    'gilmour': dict(url='https://www.gspace.com/update', hosts={'www.gspace.com','gspace.com'},
                   detail=r'/post/[^/]+/?'),
}
UA = 'SpaceScienceNews/0.3 (official-news-source-probe)'
ROOT = Path('/data/international-probes')


def approved(url, site):
    p = urlsplit(url)
    return (p.scheme in {'http', 'https'} and p.hostname in site['hosts']
            and not p.username and not p.password and p.port in {None, 80, 443})


def run(source):
    site = SITES[source]
    folder = ROOT / source
    folder.mkdir(parents=True, exist_ok=True)
    result = dict(samples=[], errors=[], robots={}, navigation=[], feeds=[], scripts=[], external_links=[])
    policies, last_request = {}, None
    with httpx.Client(timeout=15, trust_env=False, follow_redirects=False) as client:
        def fetch(url, name, robots=False):
            nonlocal last_request
            for step in range(4):
                if not approved(url, site):
                    raise ValueError('Redirect left reviewed publisher hosts')
                if not robots:
                    check_robots(url)
                    policy = policies.get(urlsplit(url).netloc)
                    if policy and not policy.can_fetch(UA, url):
                        raise ValueError('Publisher robots disallows URL')
                if last_request is not None:
                    time.sleep(max(0, 1 - (time.monotonic() - last_request)))
                last_request = time.monotonic()
                with client.stream('GET', url, headers={'User-Agent': UA}) as response:
                    if robots and response.status_code == 404:
                        return b'', url
                    if response.is_redirect:
                        result['samples'].append({'requested_url': url, 'status': response.status_code,
                                                  'redirect': str(response.url.join(response.headers['location']))})
                        url = str(response.url.join(response.headers['location']))
                        continue
                    raw = bytearray()
                    for chunk in response.iter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 2 * 1024 * 1024:
                            raise ValueError('Response too large')
                    path = folder / name
                    path.write_bytes(raw)
                    result['samples'].append(dict(url=url, status=response.status_code,
                        content_type=response.headers.get('content-type'), bytes=len(raw), file=str(path.relative_to(ROOT)),
                        retry_after=response.headers.get('retry-after'),sha256=hashlib.sha256(raw).hexdigest()))
                    response.raise_for_status()
                    return bytes(raw), url
            raise ValueError('Too many redirects')

        def check_robots(url):
            authority = urlsplit(url).netloc
            if authority in result['robots']:
                return
            # Mark checked first, since fetch follows redirects.
            result['robots'][authority] = 'checking'
            robot_url = urljoin(url, '/robots.txt')
            raw, _ = fetch(robot_url, 'robots-' + authority + '.txt', robots=True)
            if not raw:
                result['robots'][authority] = 'missing_404_or_empty'
            elif re.search(br'<(?:html|!doctype)', raw[:200], re.I):
                result['robots'][authority] = 'html_response_no_rules'
            else:
                policy = RobotFileParser()
                policy.parse(raw.decode('utf-8-sig').splitlines())
                policies[authority] = policy
                result['robots'][authority] = 'parsed'

        try:
            raw, final = fetch(site['url'], 'list.html')
            tree = BeautifulSoup(raw, 'html.parser', from_encoding='utf-8')
            candidates = []
            for a in tree.select('a[href]'):
                url = urljoin(final, a['href'])
                label = a.get_text(' ', strip=True)[:250]
                if not approved(url, site):
                    if source == 'skyroot' and label and urlsplit(url).scheme in {'http','https'}:
                        result['external_links'].append(dict(url=url,label=label))
                    continue
                if source == 'arianespace':
                    valid = (urlsplit(url).hostname == 'newsroom.arianespace.com' and
                             (urlsplit(url).query.startswith('p=') or re.fullmatch(site['detail'], urlsplit(url).path)))
                    valid = valid and label not in {'Press', 'Press Releases', 'Access the Newsroom for latest news'}
                else:
                    valid = bool(re.fullmatch(site['detail'], urlsplit(url).path))
                if label and valid:
                    candidates.append(url)
                if re.search(r'news|update|press|stories', url, re.I):
                    result['navigation'].append(dict(url=url, label=label))
            for alternate in tree.select('link[rel="alternate"][href]'):
                if re.search('rss|atom|json', alternate.get('type', '')):
                    result['feeds'].append(dict(url=urljoin(final, alternate['href']), type=alternate.get('type')))
            for number, url in enumerate(dict.fromkeys(candidates)):
                if number >= 3:
                    break
                try:
                    fetch(url, f'detail-{number}.html')
                except Exception as error:
                    result['errors'].append(dict(url=url, error=f'{type(error).__name__}: {error}'))
            result['candidate_details'] = len(set(candidates))
            if source == 'spacex':
                home, home_url = fetch(urljoin(final, '/'), 'home.html')
                home_tree = BeautifulSoup(home, 'html.parser', from_encoding='utf-8')
                for a in home_tree.select('a[href]'):
                    href = urljoin(home_url, a['href'])
                    if approved(href, site):
                        result['navigation'].append(dict(url=href, label=a.get_text(' ', strip=True)[:150]))
                scripts = list(dict.fromkeys(urljoin(final, s['src']) for s in [*tree.select('script[src]'), *home_tree.select('script[src]')]))
                for number, url in enumerate([u for u in scripts if approved(u, site)][:6]):
                    try:
                        script, _ = fetch(url, f'script-{number}.js')
                        result['scripts'].append(dict(url=url, api_hints=re.findall(r'[^\s"\']*(?:/api/|graphql)[^\s"\']*', script.decode('utf-8', errors='replace'))[:20]))
                    except Exception as error:
                        result['errors'].append(dict(url=url, error=f'{type(error).__name__}: {error}'))
        except Exception as error:
            result['errors'].append(dict(url=site['url'], error=f'{type(error).__name__}: {error}'))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', choices=SITES, action='append')
    args = parser.parse_args()
    report = {source: run(source) for source in (args.source or ['spacex','blue_origin','arianespace','ispace'])}
    (ROOT / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    with tarfile.open('/data/international-probes.tar.gz', 'w:gz') as archive:
        archive.add(ROOT, arcname='international-probes')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
