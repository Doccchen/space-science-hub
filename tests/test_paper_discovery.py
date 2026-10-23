"""Discovery API contracts using provider-shaped fixtures; never calls a live model."""
import asyncio
import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from reader.app import create_app
from reader.config import Settings
from reader.discovery import fallback_plan, merge_rank, paper, plan


def settings(**kwargs):
    return Settings(model_key='', **kwargs)


def provider(request):
    host = request.url.host
    if host == 'api.crossref.org':
        return httpx.Response(200, json={'message': {'items': [
            {'title': ['Net capture dynamics'], 'author': [{'given': 'A', 'family': 'Researcher'}],
             'published': {'date-parts': [[2024]]}, 'container-title': ['Example journal'],
             'DOI': '10.0000/fixture', 'type': 'journal-article', 'abstract': '<jats:p>Net capture methods</jats:p>'}]}})
    if host == 'api.semanticscholar.org':
        return httpx.Response(200, json={'data': [
            {'title': 'Net capture dynamics', 'year': 2024, 'externalIds': {'DOI': '10.0000/FIXTURE'},
             'authors': [{'name': 'A Researcher'}], 'publicationTypes': ['JournalArticle'],
             'openAccessPdf': {'url': 'https://example.org/fixture.pdf'}}]})
    if host == 'ntrs.nasa.gov':
        assert request.method == 'POST'
        assert json.loads(request.content)['page']['size'] == 12
        return httpx.Response(200, json={'results': [
            {'id': 20240000001, 'title': 'Net capture experiments', 'stiType': 'TECHNICAL_REPORT',
             'authorAffiliations': [{'meta': {'author': {'name': 'B Researcher'}}}],
             'publications': [{'publicationDate': '2023-01-01'}], 'downloadsAvailable': True}]})
    if host == 'export.arxiv.org':
        return httpx.Response(200, text='''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
        <id>https://arxiv.org/abs/2401.00000</id><title>Net capture simulation</title>
        <published>2024-01-01</published><summary>net capture dynamics</summary>
        <author><name>C Researcher</name></author><link title="pdf" href="https://arxiv.org/pdf/2401.00000"/>
        </entry></feed>''')
    raise AssertionError(host)


def test_search_merges_sources_keeps_provenance_and_caches():
    calls = []
    def respond(request):
        calls.append(request)
        return provider(request)
    with TestClient(create_app(settings(), httpx.MockTransport(respond))) as client:
        assert client.get('/api/reader/health').json()['service'] == 'paper-search'
        assert 'id="search-form"' in client.get('/reader/').text
        assert client.post('/api/reader/papers').status_code == 404
        result = client.post('/api/reader/search', json={'query': 'net capture dynamics'}).json()
        assert len(result['papers']) == 3
        merged = next(p for p in result['papers'] if p['doi'])
        assert merged['sources'] == ['Crossref', 'Semantic Scholar']
        assert merged['fulltext'] == 'https://example.org/fixture.pdf'
        assert merged['abstract'] == 'Net capture methods'
        nasa = next(p for p in result['papers'] if p['sources'] == ['NASA NTRS'])
        assert nasa['authors'] == ['B Researcher'] and nasa['year'] == 2023 and nasa['fulltext']
        assert any(p['type'] == '预印本' for p in result['papers'])
        assert len(calls) == 4
        cached = client.post('/api/reader/search', json={'query': 'net capture dynamics'}).json()
        assert len(calls) == 4 and all(s['cached'] for s in cached['sources'])


def test_partial_failure_does_not_erase_other_sources():
    def respond(request):
        if request.url.host == 'api.semanticscholar.org':
            return httpx.Response(429)
        if request.url.host == 'export.arxiv.org':
            return httpx.Response(200, text='<invalid>')
        return provider(request)
    with TestClient(create_app(settings(), httpx.MockTransport(respond))) as client:
        result = client.post('/api/reader/search', json={'query': 'net capture'}).json()
        assert len(result['papers']) == 2
        assert len([s for s in result['sources'] if s['state'] == 'error']) == 2
        assert any('限流' in s.get('message', '') for s in result['sources'])


def test_all_failed_is_distinct_from_no_matches():
    def failed(request):
        raise httpx.ConnectError('blocked', request=request)
    with TestClient(create_app(settings(), httpx.MockTransport(failed))) as client:
        result = client.post('/api/reader/search', json={'query': 'net capture'}).json()
        assert result['papers'] == [] and all(s['state'] == 'error' for s in result['sources'])


def test_model_absence_and_input_origin_validation():
    with TestClient(create_app(settings(public_origin='http://testserver'))) as client:
        result = client.post('/api/reader/analyze', json={'text': '绳网回收成功的新闻'}).json()
        assert result['topics'][0]['query'] == 'tether net capture dynamics'
        assert client.post('/api/reader/search', json={'query': '  '}).status_code == 422
        assert client.post('/api/reader/analyze', json={'text': 'a' * 6001}).status_code == 422
        assert client.post('/api/reader/analyze', json={'text': 'test'}, headers={'origin': 'https://evil.example'}).status_code == 403
    assert fallback_plan('长征某型号')['topics'][0]['query'] == '长征某型号'


def test_conflicting_dois_not_merged_and_unsafe_links_not_emitted():
    one = paper('Crossref', 'Same title', [], 2023, '', '10.0000/a', url='javascript:alert(1)')
    two = paper('arXiv', 'Same title', [], 2024, '', '10.0000/b', fulltext='javascript:alert(1)')
    records = merge_rank([one, two], 'unrelated')
    assert len(records) == 2 and all(p['relation'] == '待核对' for p in records)
    assert one['url'].startswith('https://doi.org/') and not two['fulltext']


def test_model_only_produces_topics_and_bad_formats_fall_back():
    async def exercise():
        config = Settings(model_key='test-fixture-key')
        def respond(request):
            payload = json.loads(request.content)
            assert '不生成论文' in payload['messages'][0]['content']
            return httpx.Response(200, json={'choices': [{'message': {'content': '{"topics": [{"name": "绳网回收", "query": "net capture dynamics"}]}'}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            result = await plan('绳网回收', config, client)
            assert result['method'] == 'AI 技术提取' and 'papers' not in result
        def bad(request):
            return httpx.Response(200, json={'choices': [{'message': {'content': '{"topics": ["broken"]}'}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(bad)) as client:
            result = await plan('绳网回收', config, client)
            assert result['method'] == '关键词识别' and '暂不可用' in result['notice']
    asyncio.run(exercise())


def test_news_entry_handoff_is_same_origin_and_does_not_leak_body_in_url():
    source = Path('web/news-reader.js').read_text(encoding='utf-8')
    assert ".href = '/assets/research.html?news=' + encodeURIComponent(id)" in source
    frontend = Path('reader_web/reader.js').read_text(encoding='utf-8-sig')
    assert 'innerHTML' not in frontend
    assert "fetch('/api/news/' + news" in frontend

def test_ungrounded_model_topics_fall_back_without_inventing_applications():
    async def exercise():
        def respond(request):
            return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({'topics': [
                {'name': '空间碎片捕获', 'query': 'space debris capture'}]}, ensure_ascii=False)}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            result = await plan('绳网回收', Settings(model_key='test-fixture-key'), client)
            assert result['method'] == '关键词识别'
            assert result['topics'][0]['query'] == 'tether net capture dynamics'
    asyncio.run(exercise())


def test_model_budget_falls_back_and_search_remains_available():
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"topics":[{"name":"绳网回收","query":"net capture"}]}'}}]})
    with TestClient(create_app(Settings(model_key='test-fixture-key', site_calls=1), httpx.MockTransport(respond))) as client:
        assert client.post('/api/reader/analyze', json={'text':'绳网回收'}).json()['method'] == 'AI 技术提取'
        result = client.post('/api/reader/analyze', json={'text':'绳网回收'}).json()
        assert result['method'] == '关键词识别' and '额度' in result['notice'] and len(calls) == 1
