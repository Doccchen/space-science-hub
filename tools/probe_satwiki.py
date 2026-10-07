"""Bounded, read-only SatWiki access probe; never downloads article batches.

Checks robots.txt, then site metadata if not explicitly disallowed. Stops on
access denial or rate limiting. No credentials, cookies or browser impersonation.
"""
import argparse
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import datetime, timezone
from pathlib import Path

ORIGIN = 'https://sat.huijiwiki.com'
AGENT = 'ZhihangSatWikiProbe/0.1 (read-only access assessment)'
MAX_BYTES = 256 * 1024


class SameOrigin(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).netloc != 'sat.huijiwiki.com' or not newurl.startswith('https://'):
            raise ValueError('Redirect outside approved HTTPS origin')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url):
    start = time.monotonic()
    opener = urllib.request.build_opener(SameOrigin())
    request = urllib.request.Request(url, headers={'User-Agent': AGENT})
    try:
        response = opener.open(request, timeout=20)
    except urllib.error.HTTPError as error:
        response = error
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as error:
        return {'url': url, 'network_error': str(error), 'elapsed_seconds': round(time.monotonic()-start, 2)}, b''
    with response:
        body = response.read(MAX_BYTES + 1)
        result = {
            'url': url, 'final_url': response.geturl(), 'status': response.code,
            'content_type': response.headers.get('Content-Type', ''),
            'retry_after': response.headers.get('Retry-After'),
            'elapsed_seconds': round(time.monotonic()-start, 2),
            'bytes_read': len(body), 'truncated': len(body) > MAX_BYTES,
            'sha256': hashlib.sha256(body).hexdigest(),
        }
    return result, body


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('artifacts/satwiki-access-probe'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report = {'started_utc': datetime.now(timezone.utc).isoformat(), 'user_agent': AGENT,
              'article_downloads': 0, 'requests': []}
    robots, body = fetch(ORIGIN + '/robots.txt')
    report['requests'].append(robots)
    params = {'action': 'query', 'meta': 'siteinfo',
              'siprop': 'general|statistics|namespaces|rightsinfo',
              'format': 'json', 'formatversion': '2', 'maxlag': '5'}
    api_url = ORIGIN + '/api.php?' + urllib.parse.urlencode(params)
    policy = None
    if robots.get('status') == 200 and not robots['truncated']:
        content = body.decode('utf-8', errors='replace')
        # A challenge HTML page is not a valid robots policy.
        if '<html' not in content.lower() and 'text/html' not in robots['content_type'].lower():
            (args.output/'robots.txt').write_text(content, encoding='utf-8')
            policy = urllib.robotparser.RobotFileParser()
            policy.parse(content.splitlines())
    report['robots_policy'] = 'read' if policy else 'unverified'
    if policy and not policy.can_fetch(AGENT, api_url):
        report['result'] = 'robots_disallows_api_probe'
    elif robots.get('network_error'):
        report['result'] = 'network_failed_before_api'
    elif robots.get('status') == 429:
        report['result'] = 'rate_limited_before_api'
    else:
        # Unknown robots policy permits only this metadata diagnostic here;
        # it must be resolved before any article enumeration or download.
        time.sleep(2)
        api, body = fetch(api_url)
        report['requests'].append(api)
        if api.get('network_error'):
            report['result'] = 'api_network_failed'
        elif api.get('status') in (401, 403):
            report['result'] = 'api_access_denied_stop'
        elif api.get('status') == 429:
            report['result'] = 'api_rate_limited_stop'
        elif api.get('status') != 200 or api['truncated']:
            report['result'] = 'api_unusable_response'
        else:
            try:
                data = json.loads(body)
                if not isinstance(data, dict) or not isinstance(data.get('query'), dict):
                    report['result'] = 'api_no_siteinfo'
                    report['api_error_code'] = data.get('error', {}).get('code') if isinstance(data, dict) else None
                else:
                    (args.output/'siteinfo.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
                    report['result'] = 'api_siteinfo_readable'
            except (ValueError, UnicodeError):
                report['result'] = 'api_non_json_stop'
    report['completed_utc'] = datetime.now(timezone.utc).isoformat()
    report['request_count'] = len(report['requests'])
    (args.output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
