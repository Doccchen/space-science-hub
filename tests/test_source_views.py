"""Provider grouping and real Wanfang offset pagination using offline contracts."""
import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from reader.app import create_app
from reader.config import Settings
from reader.wanfang import parse_page,request_options,WanfangError
from test_paper_discovery import provider


def wf_document(index,kind='Periodical'):
    fields={'Id':'fixture-'+str(index),'Title':['冲压发动机研究样本 '+str(index)],'Creator':['演示作者'],
            'PublishYear':2000+index%25,'Abstract':['离线测试摘要'],'DOI':'10.0000/source-'+str(index)}
    return {'resourceType':kind,'fields':{},kind:fields}


def test_explicit_topic_query_scopes_and_safe_phrase_escaping():
    options={'field':'topic','library':'papers','page':3,'page_size':20,'sort':'date','year_from':2020,'year_to':2026}
    payload=request_options('冲压发动机',options)
    assert payload['start']==40 and payload['rows']==20
    assert payload['collections']==['OpenPeriodical','OpenThesis','OpenConference']
    assert 'Title:"冲压发动机"' in payload['query'] and 'KeywordForSearch:' in payload['query'] and 'Abstract:' in payload['query']
    assert 'PublishYear:[2020 TO 2026]' in payload['query']
    assert payload['sort']['sorts'][0]=={'by':'PublishYear','order':'DESC'}
    escaped=request_options('a" OR Title:*',{'field':'title','library':'periodical'})['query']
    assert escaped=='Title:'+json.dumps('a" OR Title:*',ensure_ascii=False)
    assert len(request_options('冲压发动机',{'library':'all'})['collections'])==4


@pytest.mark.parametrize('options',[{'page':0},{'page':1001},{'page_size':200},{'library':'unknown'},{'year_from':2026,'year_to':2020}])
def test_invalid_filters_are_rejected_before_network(options):
    with pytest.raises(WanfangError):request_options('冲压发动机',options)


def test_counts_resource_types_and_provider_order_are_preserved():
    docs=[wf_document(i,kind) for i,kind in enumerate(['Periodical','Thesis','Conference','Patent'],start=1)]
    result=parse_page({'documents':docs,'numFound':'103'}, {'page':2,'page_size':20})
    assert result['total']==103 and result['has_more'] and result['page']==2
    assert [p['type'] for p in result['papers']]==['期刊论文','学位论文','会议论文','专利']
    assert [p['source_rank'] for p in result['papers']]==[21,22,23,24]
    assert '/thesis/' in result['papers'][1]['url'] and '/patent/' in result['papers'][3]['url']
    assert parse_page({'documents':[]},{'page':1,'page_size':20})['total'] is None
    assert not parse_page({'documents':[]})['pagination_supported']


def test_api_groups_original_source_order_and_fetches_only_selected_page(tmp_path,monkeypatch):
    monkeypatch.setenv('MANAGEMENT_DB_PATH',str(tmp_path/'not-initialized.sqlite3'))
    calls=[]
    def respond(request):
        calls.append(request)
        if request.url.host=='api.wfdata.com':
            body=json.loads(request.content);start=body['start'];size=body['rows']
            return httpx.Response(200,json={'documents':[wf_document(i) for i in range(start,start+min(size,45-start))],'numFound':45})
        return provider(request)
    with TestClient(create_app(Settings(model_key='',wanfang_key='fixture-only'),httpx.MockTransport(respond))) as client:
        initial=client.post('/api/reader/search',json={'query':'ramjet engine','query_zh':'冲压发动机','wanfang':{}})
        assert initial.status_code==200
        data=initial.json();group=next(g for g in data['source_results'] if g['source']=='万方')
        assert group['total']==45 and group['count']==20 and group['page_size']==20
        assert [p['provider_id'] for p in group['papers']]==['fixture-'+str(i) for i in range(20)]
        count=len(calls)
        second=client.post('/api/reader/search',json={'query':'ramjet engine','query_zh':'冲压发动机','source':'万方','wanfang':{'page':2}}).json()
        assert len(calls)==count+1 and calls[-1].url.host=='api.wfdata.com'
        assert json.loads(calls[-1].content)['start']==20
        assert len(second['source_results'])==1 and second['source_results'][0]['papers'][0]['provider_id']=='fixture-20'
        cached=client.post('/api/reader/search',json={'query':'ramjet engine','query_zh':'冲压发动机','source':'万方','wanfang':{'page':2}}).json()
        assert len(calls)==count+1 and cached['sources'][0]['cached']
        assert client.post('/api/reader/search',json={'query':'ramjet','source':'not-real'}).status_code==422
        assert client.post('/api/reader/search',json={'query':'ramjet','source':'ScienceDirect'}).status_code==400
        assert client.post('/api/reader/search',json={'query':'ramjet','wanfang':{'year_from':2026,'year_to':2020}}).status_code==422
