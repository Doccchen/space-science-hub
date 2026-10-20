"""Private API management, encryption, runtime reload, and quota tests; no live calls."""
import asyncio
import json
from pathlib import Path

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend import admin_auth, ai_config, literature_config as config, management_store as store, news
from backend.admin_app import app as admin_app
from backend.app import app as public_app
from reader.config import Settings
from reader.provider_runtime import Runtime
from reader.sciencedirect import fetch as sd_fetch, ScienceDirectError

ORIGIN='http://127.0.0.1:18080'
KEY='fixture-private-key-123456'
TOKEN='fixture-insttoken-654321'


@pytest.fixture
def admin(tmp_path,monkeypatch):
    monkeypatch.setattr(news,'DB_PATH',tmp_path/'news.sqlite3')
    monkeypatch.setenv('MANAGEMENT_DB_PATH',str(tmp_path/'management.sqlite3'))
    monkeypatch.setenv('AI_MASTER_KEY_FILE',str(tmp_path/'master.key'))
    monkeypatch.setenv('ADMIN_ORIGIN',ORIGIN)
    ai_config.generate_key(tmp_path/'master.key')
    news.initialize();admin_auth.initialize_user('admin','fixture-password-2026')
    with TestClient(admin_app,base_url=ORIGIN) as client:
        response=client.post('/api/login',json={'username':'admin','password':'fixture-password-2026'},headers={'Origin':ORIGIN})
        client.headers.update({'Origin':ORIGIN,'X-CSRF-Token':response.json()['csrf']})
        yield client


def overview(client,provider='wanfang'):
    return next(p for p in client.get('/api/literature-config').json()['providers'] if p['provider']==provider)


def draft(client,provider='wanfang',key=KEY,token='',**changes):
    row=overview(client,provider)
    body={'revision':row['revision'],'config':{k:row['draft']['config'][k] for k in config.DEFAULT},
          'new_key':key,'new_insttoken':token,'clear_key':False,'clear_insttoken':False}
    body['config'].update(changes)
    return client.post('/api/literature-config/'+provider+'/drafts',json=body)


def apply(client,provider='wanfang'):
    row=overview(client,provider)
    return client.post('/api/literature-config/'+provider+'/apply',json={'revision':row['revision'],'version':row['draft']['version']})


def test_private_csrf_and_explicit_initialization(admin):
    assert admin.get('/api/literature-config').json()=={'initialized':False,'providers':[]}
    assert not store.path().exists()
    with TestClient(admin_app,base_url=ORIGIN) as anonymous:
        assert anonymous.get('/api/literature-config').status_code==401
    assert admin.post('/api/literature-config/initialize',json={},headers={'X-CSRF-Token':''}).status_code==403
    assert admin.post('/api/literature-config/initialize',json={}).status_code==200
    assert len(admin.get('/api/literature-config').json()['providers'])==2
    assert all(not p['applied']['config']['enabled'] for p in admin.get('/api/literature-config').json()['providers'])
    assert '/api/literature-config' not in public_app.openapi()['paths']


def test_encryption_no_key_echo_draft_apply_conflict_and_clear(admin):
    admin.post('/api/literature-config/initialize',json={})
    assert draft(admin,enabled=True,authorized=False).status_code==400
    assert draft(admin,enabled=True,authorized=True).status_code==200
    row=overview(admin)
    assert not row['applied']['config']['enabled'] and row['draft']['key_configured']
    assert KEY not in admin.get('/api/literature-config').text
    with store.connection() as db:
        text=''.join(r[0] for r in db.execute('SELECT encrypted_secrets FROM literature_versions'))
        audits=''.join(r[0] for r in db.execute('SELECT summary FROM management_audit'))
    assert KEY not in text+audits
    assert apply(admin).status_code==200
    stale=admin.post('/api/literature-config/wanfang/apply',json={'revision':row['revision'],'version':row['draft']['version']})
    assert stale.status_code==409
    assert draft(admin,key='',enabled=False).status_code==200
    assert overview(admin)['draft']['key_configured']
    assert apply(admin).status_code==200
    row=overview(admin)
    body={'revision':row['revision'],'config':{**config.DEFAULT},'new_key':'','new_insttoken':'','clear_key':True,'clear_insttoken':False}
    assert admin.post('/api/literature-config/wanfang/drafts',json=body).status_code==200
    assert not overview(admin)['draft']['key_configured']


def test_runtime_hot_reload_disable_restore_and_missing_master_fail_closed(admin):
    admin.post('/api/literature-config/initialize',json={})
    assert draft(admin,enabled=True,authorized=True).status_code==200
    assert apply(admin).status_code==200
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(503))) as client:
            runtime=Runtime(client,Settings(wanfang_key='fixture-stale-environment'))
            runtime.sync();assert '万方' in runtime.service.sources
            assert overview(admin)['status']=='applied'
            first=runtime.service
            runtime.sync();assert runtime.service is first
            draft(admin,key='',enabled=False);apply(admin);runtime.sync()
            assert '万方' not in runtime.service.sources
            row=overview(admin)
            assert admin.post('/api/literature-config/wanfang/restore',json={'revision':row['revision']}).status_code==200
            runtime.sync();assert '万方' in runtime.service.sources
            import os
            Path(os.environ['AI_MASTER_KEY_FILE']).write_bytes(Fernet.generate_key())
            runtime.sync();assert runtime.warning and '万方' not in runtime.service.sources
    asyncio.run(exercise())


def test_quota_survives_config_change_and_tests_share_budget(admin,monkeypatch):
    admin.post('/api/literature-config/initialize',json={})
    draft(admin,enabled=True,authorized=True,daily_limit=1);apply(admin)
    row=overview(admin);calls=[]
    original=httpx.AsyncClient
    def respond(request):
        calls.append(request)
        assert request.headers['X-App-Key']==KEY
        return httpx.Response(200,json={'documents':[]})
    monkeypatch.setattr('backend.literature_admin.httpx.AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(respond),**kwargs))
    body={'version':row['draft']['version'],'fee_confirmed':False}
    assert admin.post('/api/literature-config/wanfang/test',json=body).status_code==400
    assert not calls
    body['fee_confirmed']=True
    assert admin.post('/api/literature-config/wanfang/test',json=body).json()['ok']
    assert len(calls)==1 and overview(admin)['used_today']==1
    assert admin.post('/api/literature-config/wanfang/test',json=body).status_code==429
    draft(admin,key='',daily_limit=50)
    newer=overview(admin)['draft']['version']
    assert admin.post('/api/literature-config/wanfang/test',json={'version':newer,'fee_confirmed':True}).status_code==429
    assert len(calls)==1


def test_sciencedirect_headers_optional_token_no_fulltext_and_sanitized_errors():
    async def exercise():
        def respond(request):
            assert request.method=='PUT' and request.url.host=='api.elsevier.com'
            assert request.headers['X-ELS-APIKey']==KEY and request.headers['X-ELS-Insttoken']==TOKEN
            assert json.loads(request.content)['qs']=='grid fin'
            return httpx.Response(200,json={'resultsFound':1,'results':[{'title':'Grid fin fixture','doi':'10.0000/sd-fixture','authors':[{'name':'Fixture author'}],'publicationDate':'2024-01-01','sourceTitle':'Fixture journal','uri':'https://www.sciencedirect.com/science/article/pii/fixture','openAccess':False}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            rows=await sd_fetch('grid fin',client,KEY,TOKEN)
            assert rows[0]['sources']==['ScienceDirect'] and rows[0]['year']==2024 and not rows[0]['fulltext']
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(403,text=KEY+TOKEN))) as client:
            with pytest.raises(ScienceDirectError) as error:await sd_fetch('grid fin',client,KEY)
            assert KEY not in str(error.value) and TOKEN not in str(error.value)
    asyncio.run(exercise())


def test_saved_request_uses_applied_version_and_test_errors_are_redacted(admin,monkeypatch):
    admin.post('/api/literature-config/initialize',json={})
    draft(admin,'sciencedirect',token=TOKEN,enabled=True,authorized=True);apply(admin,'sciencedirect')
    row=overview(admin,'sciencedirect')
    original=httpx.AsyncClient
    monkeypatch.setattr('backend.literature_admin.httpx.AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(lambda r:httpx.Response(403,text=KEY+TOKEN)),**kwargs))
    result=admin.post('/api/literature-config/sciencedirect/test',json={'version':row['draft']['version'],'fee_confirmed':True})
    assert not result.json()['ok'] and KEY not in result.text and TOKEN not in result.text
    assert KEY not in admin.get('/api/literature-config').text
    with pytest.raises(config.ProviderLimit):config.reserve('sciencedirect',-1,100)


def test_missing_database_does_not_reenable_environment_credentials(admin):
    admin.post('/api/literature-config/initialize',json={})
    store.path().rename(store.path().with_suffix('.saved'))
    async def exercise():
        async with httpx.AsyncClient() as client:
            runtime=Runtime(client,Settings(wanfang_key=KEY));runtime.sync()
            assert runtime.warning and '万方' not in runtime.service.sources
    asyncio.run(exercise())


def test_search_budget_counts_real_calls_but_not_cache_hits(admin):
    admin.post('/api/literature-config/initialize',json={})
    draft(admin,enabled=True,authorized=True,daily_limit=1);apply(admin)
    async def exercise():
        calls=[]
        def respond(request):
            calls.append(request)
            return httpx.Response(200,json={'documents':[]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            runtime=Runtime(client,Settings());runtime.sync()
            assert (await runtime.service.source('万方','栅格舵'))[1]['state']=='ok'
            assert (await runtime.service.source('万方','栅格舵'))[1]['cached']
            assert len(calls)==1 and overview(admin)['used_today']==1
            _,status=await runtime.service.source('万方','发动机')
            assert status['state']=='error' and '额度' in status['message']
            assert len(calls)==1
    asyncio.run(exercise())
