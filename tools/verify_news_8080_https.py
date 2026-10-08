"""External TLS/redirect/origin/cookie acceptance; never asks the model."""
import hashlib
import json
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = 'https://8.137.164.100:8080'


def main():
    report = {'url': PUBLIC, 'model_calls': 0}
    with httpx.Client(base_url=PUBLIC, timeout=20, trust_env=False) as client:
        homepage = client.get('/')
        homepage.raise_for_status()
        report['homepage'] = homepage.status_code
        report['homepage_sha256'] = hashlib.sha256(homepage.content).hexdigest()
        report['tls_verified'] = True
        health = client.get('/api/health'); health.raise_for_status()
        report['health'] = health.json()
        resources = client.get('/api/resources?page=1&page_size=12'); resources.raise_for_status()
        report['resources'] = resources.status_code
        listing = client.get('/api/news?page=1&page_size=10'); listing.raise_for_status()
        report['news_list'] = listing.status_code
        ai_status = client.get('/api/ai/status'); ai_status.raise_for_status()
        enabled = ai_status.json()['enabled']
        report['ai_enabled'] = enabled
        rejected = client.post('/api/ai/conversations', headers={'Origin': 'https://other.invalid'})
        assert rejected.status_code == 403, 'Cross-origin conversation creation must fail'
        report['cross_origin_rejected'] = True
        created = client.post('/api/ai/conversations', headers={'Origin': PUBLIC})
        report['same_origin_create_status'] = created.status_code
        if enabled:
            assert created.status_code == 200, 'HTTPS origin must reach enabled conversation service'
            conversation = created.json()['conversation_id']
            try:
                cookie = created.headers.get('set-cookie', '').lower()
                assert 'secure' in cookie and 'httponly' in cookie and 'samesite=strict' in cookie
                report['secure_cookie'] = True
            finally:
                deleted = client.delete('/api/ai/conversations/' + conversation, headers={'Origin': PUBLIC})
                assert deleted.status_code == 204, 'Own test conversation must be erasable'
                report['test_conversation_deleted'] = True
        else:
            assert created.status_code == 503 and created.json()['error']['code'] != 'origin'
        legacy = client.get('http://8.137.164.100:8080/')
        assert legacy.status_code == 308 and legacy.headers.get('location') == PUBLIC + '/'
        report['legacy_http_redirect'] = 308
        mcp = client.get('https://8.137.164.100/api/news-mcp/mcp')
        report['mcp_gateway_status'] = mcp.status_code
        challenge = client.get('http://8.137.164.100/.well-known/acme-challenge/news-mcp-preflight')
        assert challenge.status_code == 200 and challenge.text.strip() == 'space-news-acme-ready'
        report['acme_challenge_accessible'] = True
    try:
        # Some networks complete a TCP handshake before rejecting the application
        # protocol. Check an actual no-credential HTTP request, plus server binding evidence.
        with httpx.Client(timeout=httpx.Timeout(5, connect=3), trust_env=False) as probe:
            probe.get('http://8.137.164.100:18081/api/health')
    except httpx.RequestError:
        report['private_upstream_http_inaccessible'] = True
    else:
        raise AssertionError('Private HTTP upstream unexpectedly reachable externally')
    output = ROOT / 'artifacts/https-8080/verification.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
