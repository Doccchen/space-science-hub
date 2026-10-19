"""Temporary-session lifecycle, isolation, replacement and durable quotas."""
import time
import uuid
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient
from reader.legacy_app import create_app
from reader.config import Settings
from reader.store import Store
from reader import temporary


def pdf(text='A numerical method evaluates heat transfer in a channel. Temperature is 300 K.'):
    with pymupdf.open() as doc:
        page=doc.new_page();page.insert_text((50,55),'2. Numerical method');page.insert_textbox(pymupdf.Rect(50,90,500,500),text)
        return doc.tobytes()


@pytest.fixture
def environment(tmp_path):
    settings=Settings(data=tmp_path,model_key='',verify_answers=False,parse_timeout=10)
    app=create_app(settings)
    with TestClient(app) as client:
        assert client.post('/api/reader/session').status_code==200
        yield client,app,settings


def upload(client,content=None):
    response=client.post('/api/reader/papers',content=content or pdf(),headers={'Content-Type':'application/pdf','X-Filename':'test.pdf'})
    assert response.status_code==202,response.text
    return response.json()['paper']


def ready(client,item):
    for _ in range(120):
        detail=client.get('/api/reader/papers/'+item['id']).json()
        if detail['status'] not in ('queued','parsing'):
            assert detail['status'] in ('ready','partial'),detail
            return detail
        time.sleep(.05)
    pytest.fail('Parsing did not finish')


def test_unit_expiry_purges_files_blocks_answers_and_keeps_budget(tmp_path):
    store=Store(Settings(data=tmp_path))
    with store.connect() as db:
        db.execute('INSERT INTO visitors VALUES(?,?,?)',('owner',10,'network'))
        db.execute('INSERT INTO papers(id,owner,hash,filename,size,title,created,updated) VALUES(?,?,?,?,?,?,?,?)',('paper','owner','hash','paper.pdf',20,'title',1,1))
        db.execute('INSERT INTO blocks VALUES(?,?,?,?,?,?,?,?)',('block','paper',1,1,'方法与条件',0,'text','[]'))
        db.execute('INSERT INTO usage VALUES(?,?,?,?,?,?,?,?)',('call','owner','request',1,'done',1,1,200))
    (tmp_path/'files/paper.pdf').write_bytes(b'fixture')
    temporary.sweep(store,now=11)
    assert not (tmp_path/'files/paper.pdf').exists()
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM blocks').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM visitors').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM usage').fetchone()[0]==1
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='notes'").fetchone()


def test_unit_origin_and_ttl_configuration(tmp_path):
    for origin in ('https://example.com/path','https://name:secret@example.com','javascript:bad'):
        with pytest.raises(ValueError):Settings(data=tmp_path,public_origin=origin)
    with pytest.raises(ValueError):Settings(data=tmp_path,session_seconds=0)
    assert Settings(data=tmp_path,public_origin='https://example.com:8080').public_origin.endswith(':8080')


def test_current_reader_has_no_notes_or_personal_library(environment):
    client,_,_=environment
    assert client.get('/api/reader/current').json()['paper'] is None
    assert client.get('/api/reader/papers').status_code==405
    paper=ready(client,upload(client))
    assert client.get('/api/reader/current').json()['paper']['id']==paper['id']
    assert client.get(f'/api/reader/papers/{paper["id"]}/notes').status_code==404
    assert client.post(f'/api/reader/papers/{paper["id"]}/notes/draft').status_code==404
    assert client.get('/reader/').status_code==200


def test_failed_upload_preserves_current_and_successful_replacement_clears_old(environment):
    client,app,settings=environment
    old=ready(client,upload(client))
    bad=client.post('/api/reader/papers',content=b'%PDF-this-is-broken',headers={'Content-Type':'application/pdf'})
    assert bad.status_code==422
    assert client.get('/api/reader/current').json()['paper']['id']==old['id']
    duplicate=upload(client)
    assert duplicate['id']==old['id']
    new=ready(client,upload(client,pdf('A different paper examines combustion temperatures and boundary conditions.')))
    assert new['id']!=old['id']
    assert client.get('/api/reader/papers/'+old['id']).status_code==404
    assert not (settings.data/'files'/(old['id']+'.pdf')).exists()
    with app.state.store.connect() as db:assert db.execute('SELECT COUNT(*) FROM papers').fetchone()[0]==1


def test_foreign_session_and_end_clear(environment):
    client,app,settings=environment
    paper=ready(client,upload(client))
    other=TestClient(app);other.post('/api/reader/session')
    for suffix in ('','/file','/blocks','/answers','/pages/1.png'):
        assert other.get('/api/reader/papers/'+paper['id']+suffix).status_code==404
    assert client.post('/api/reader/end').status_code==200
    assert client.get('/api/reader/current').json()['paper'] is None
    assert not (settings.data/'files'/(paper['id']+'.pdf')).exists()


def test_ip_quota_survives_new_cookie_and_end(environment):
    client,app,settings=environment
    settings.ip_calls=1
    paper=ready(client,upload(client))
    session=client.post(f'/api/reader/papers/{paper["id"]}/sessions').json()
    body={'question':'What is the temperature?','session_id':session['id'],'request_key':uuid.uuid4().hex}
    assert client.post(f'/api/reader/papers/{paper["id"]}/ask',json=body).status_code==200
    client.post('/api/reader/end')
    other=TestClient(app);other.post('/api/reader/session')
    new=ready(other,upload(other))
    session=other.post(f'/api/reader/papers/{new["id"]}/sessions').json()
    body.update(session_id=session['id'],request_key=uuid.uuid4().hex)
    assert other.post(f'/api/reader/papers/{new["id"]}/ask',json=body).status_code==429


def test_public_https_origin_and_expiry(environment):
    client,app,settings=environment
    settings.public_origin='https://zhihang.example:8080'
    assert client.post('/api/reader/session',headers={'origin':settings.public_origin}).status_code==200
    assert client.post('/api/reader/session',headers={'origin':'https://evil.example'}).status_code==403
    with app.state.store.connect() as db:db.execute('UPDATE visitors SET expires=0')
    assert client.get('/api/reader/current').status_code==410
    assert client.post('/api/reader/session').status_code==200
    assert client.get('/api/reader/current').json()['paper'] is None
