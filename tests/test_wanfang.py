"""AI HUB contract fixtures; no real key, live API, or billable request."""
import asyncio
import json
from pathlib import Path

import httpx
import pytest

from reader.discovery import SearchService, fallback_plan, merge_rank, paper
from reader.wanfang import WanfangError, fetch
from tools.configure_wanfang import save_key


def record():
    return {'resource_type':'Periodical','fields':{
        'Id':'fixture20260001','Title':['栅格舵气动研究（测试样本）','Grid fin aerodynamics fixture'],
        'Creator':['测试作者甲','测试作者乙'],'PublishYear':2026,
        'PeriodicalTitle':['测试期刊'],'DOI':'10.0000/fixture','Abstract':['<p>栅格舵气动特性测试摘要</p>'],
        'HasFulltext':True,'FulltextPath':'private-fixture.pdf'}}


def test_live_typed_periodical_envelope_with_empty_fields_is_not_dropped():
    async def exercise():
        document={'resourceType':'Periodical','uid':'fixture-uid','fields':{},'Periodical':record()['fields']}
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'documents':[document],'numFound':1}))) as client:
            rows=await fetch('液氧煤油',client,'fixture-only-key')
        assert len(rows)==1,'Provider returned a document but the adapter silently dropped it'
        assert rows[0]['title']=='栅格舵气动研究（测试样本）'
        assert rows[0]['year']==2026 and rows[0]['sources']==['万方']
    asyncio.run(exercise())


@pytest.mark.parametrize('body',[
    {'documents':[{'fields':{}}],'numFound':1},
    {'documents':[],'numFound':10},
    {'documents':[],'num_found':10},
    {'code':'AUTH_PAYMENT_FAILED','message':'fixture-key','documents':[]},
])
def test_unparseable_or_payment_failures_are_not_reported_as_zero_matches(body):
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=body))) as client:
            with pytest.raises(WanfangError) as error:await fetch('液氧煤油',client,'fixture-key')
            assert 'fixture-key' not in str(error.value)
    asyncio.run(exercise())


def test_wanfang_sends_key_only_to_https_api_and_maps_metadata():
    async def exercise():
        def respond(request):
            assert str(request.url)=='https://api.wfdata.com/openwanfang/getQuery'
            assert request.headers['X-App-Key']=='fixture-only-key'
            body=json.loads(request.content)
            assert body['collections']==['OpenPeriodical'] and body['query']=='栅格舵'
            assert body['rows']==12 and body['start']==0
            return httpx.Response(200,json={'documents':[record()],'num_found':1})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            rows=await fetch('栅格舵',client,'fixture-only-key')
        row=rows[0]
        assert row['title']=='栅格舵气动研究（测试样本）' and len(row['authors'])==2
        assert row['abstract']=='栅格舵气动特性测试摘要' and row['year']==2026
        assert row['sources']==['万方'] and row['type']=='期刊论文'
        assert row['url']=='https://d.wanfangdata.com.cn/periodical/fixture20260001'
        assert row['fulltext']=='', 'Subscription full text must not be labeled as open access'
    asyncio.run(exercise())


@pytest.mark.parametrize('status,body',[(401,{}),(403,{}),(200,{'error':'fixture-key'}),(302,{})])
def test_failures_never_echo_credential_or_follow_redirect(status,body):
    async def exercise():
        calls=[]
        def respond(request):
            calls.append(request)
            return httpx.Response(status,json=body,headers={'location':'https://example.org/elsewhere'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond),follow_redirects=True) as client:
            with pytest.raises(WanfangError) as error:
                await fetch('栅格舵',client,'fixture-key')
            assert 'fixture-key' not in str(error.value) and len(calls)==1
    asyncio.run(exercise())


def test_optional_source_chinese_query_failure_isolation_and_cache():
    async def exercise():
        calls=[]
        def respond(request):
            calls.append(request)
            if request.url.host=='api.wfdata.com':
                assert json.loads(request.content)['query']=='栅格舵'
                return httpx.Response(200,json={'documents':[record()]})
            assert 'X-App-Key' not in request.headers
            return httpx.Response(503)
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            assert '万方' not in SearchService(client).sources
            service=SearchService(client,wanfang_key='fixture-only-key')
            result=await service.search('grid fin aerodynamics','栅格舵')
            assert len(result['sources'])==5 and len(result['papers'])==1
            assert result['papers'][0]['sources']==['万方']
            rows,status=await service.source('万方','栅格舵')
            assert status['cached'] and len([c for c in calls if c.url.host=='api.wfdata.com'])==1
            assert all(s['state']=='error' for s in result['sources'] if s['source']!='万方')
        merged=merge_rank([paper('Crossref','Different translated title',[],2025,'','10.0000/fixture'),result['papers'][0]],'栅格舵')
        assert len(merged)==1 and merged[0]['sources']==['Crossref','万方']
    asyncio.run(exercise())


def test_topics_keep_chinese_and_config_saving_preserves_other_settings(tmp_path):
    assert fallback_plan('栅格舵气动研究')['topics'][0]['query_zh']=='栅格舵'
    assert fallback_plan('某新技术')['topics'][0]['query_zh']=='某新技术'
    path=tmp_path/'.env.reader'
    path.write_text('READER_MODEL_KEY=fixture-model\nREADER_WANFANG_API_KEY=old-fixture\n',encoding='utf-8')
    save_key(path,'new-fixture')
    assert path.read_text().count('READER_WANFANG_API_KEY=')==1
    assert 'READER_MODEL_KEY=fixture-model' in path.read_text()
    with pytest.raises(ValueError):save_key(path,'invalid\nfixture')
    assert 'new-fixture' in path.read_text()
