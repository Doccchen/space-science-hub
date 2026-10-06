"""Private administrator web app. Never mount this app in the public service."""
import asyncio
import hashlib
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Request, Query
from fastapi.responses import FileResponse, JSONResponse
from . import news, reading, admin_auth, review_store, review_worker
from .locking import operation_lock
from .reading_policy import source_policy
from .publisher_fetch import checked_url

STATIC = Path(__file__).resolve().parent.parent/'admin_web'


@asynccontextmanager
async def lifespan(app):
    admin_auth.origin()
    news.initialize()
    task = asyncio.create_task(review_worker.loop()) if os.environ.get('REVIEW_WORKER_ENABLED', '1') == '1' else None
    yield
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware('http')
async def bounded_request(request, call_next):
    if request.method not in {'GET', 'HEAD'}:
        if request.headers.get('content-type', '').split(';')[0] != 'application/json':
            return JSONResponse({'detail': 'JSON required'}, status_code=415)
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 350_000:
                return JSONResponse({'detail': 'Request too large'}, status_code=413)
        request._body = bytes(data)
        try:
            if not isinstance(json.loads(data), dict):
                raise ValueError('JSON object required')
        except (ValueError, TypeError):
            return JSONResponse({'detail': 'JSON object required'}, status_code=400)
    response = await call_next(request)
    response.headers.update({'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
      'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'"})
    return response


@app.exception_handler(ValueError)
async def invalid(request, error):
    return JSONResponse({'detail': str(error)}, status_code=409)


@app.exception_handler(KeyError)
async def missing_field(request, error):
    return JSONResponse({'detail': 'Required review field missing'}, status_code=400)


@app.exception_handler(TimeoutError)
async def busy(request, error):
    return JSONResponse({'detail': '采集或维护任务正在占用写锁，请稍后重试。'}, status_code=409)


@app.get('/health')
def health():
    return {'status': 'ok'}


@app.get('/')
def homepage():
    return FileResponse(STATIC/'index.html')


@app.get('/admin.js')
def javascript():
    return FileResponse(STATIC/'admin.js', media_type='application/javascript')


@app.get('/admin.css')
def css():
    return FileResponse(STATIC/'admin.css', media_type='text/css')


@app.post('/api/login')
async def login(request: Request):
    admin_auth.check_origin(request)
    data = await request.json()
    token, csrf = admin_auth.login(data.get('username', ''), data.get('password', ''))
    response = JSONResponse({'csrf': csrf})
    response.set_cookie(admin_auth.COOKIE, token, httponly=True, samesite='strict', secure=admin_auth.origin().startswith('https:'), max_age=admin_auth.SESSION_SECONDS, path='/')
    return response


@app.get('/api/session')
def session(user=Depends(admin_auth.require)):
    storage = {'enabled': True, 'kind': 'server', 'location': 'persistent_news_volume'}
    return {**user, 'storage': storage}


@app.post('/api/logout')
def logout(request: Request, user=Depends(admin_auth.require)):
    with news.connect() as conn:
        conn.execute('DELETE FROM admin_sessions WHERE token_hash=?', (hashlib.sha256(request.cookies[admin_auth.COOKIE].encode()).hexdigest(),))
    response = JSONResponse({'ok': True})
    response.delete_cookie(admin_auth.COOKIE, path='/')
    return response


@app.get('/api/articles')
def articles(page: int = Query(1, ge=1, le=10000), q: str = Query('', max_length=120), user=Depends(admin_auth.require)):
    with news.connect() as conn:
        rows = conn.execute('''SELECT a.id,a.title,a.source_id,s.name AS source_name,a.original_url,
          d.revision AS draft_revision,h.version,h.withdrawn FROM articles a JOIN sources s ON s.id=a.source_id
          LEFT JOIN review_drafts d ON d.article_id=a.id LEFT JOIN reading_heads h ON h.article_id=a.id
          WHERE a.source_id IN ('nasa','cnsa','cmse') AND a.title LIKE ? ORDER BY a.id DESC LIMIT 21 OFFSET ?''', ('%'+q+'%', (page-1)*20)).fetchall()
    return {'items': [dict(row) for row in rows[:20]], 'more': len(rows)>20}


@app.get('/api/articles/{article_id}')
def detail(article_id: int, user=Depends(admin_auth.require)):
    with news.connect() as conn:
        item = review_store.article(conn, article_id)
        draft = conn.execute('SELECT * FROM review_drafts WHERE article_id=?', (article_id,)).fetchone()
        edition = reading.editions(conn, [article_id]).get(article_id)
        document = json.loads(draft['document']) if draft else json.loads(edition['document']) if edition else None
        candidates = json.loads(draft['candidates']) if draft else []
        jobs = [dict(row) for row in conn.execute('SELECT id,kind,state,result FROM review_jobs WHERE article_id=? ORDER BY created_at DESC,rowid DESC LIMIT 10', (article_id,))]
        assets = [{**dict(row), 'current': bool(edition and row['content_version'] == edition['version'])}
                  for row in conn.execute('SELECT id,status,caption,credit,content_version FROM article_assets WHERE article_id=?', (article_id,))]
    return {'article': item, 'document': document, 'revision': draft['revision'] if draft else 0,
            'candidates': candidates, 'jobs': jobs, 'assets': assets,
            'public': reading.public_content(item, edition)}


@app.post('/api/articles/{article_id}/capture')
async def capture(article_id: int, request: Request, user=Depends(admin_auth.require)):
    data = await request.json()
    with operation_lock(news.DB_PATH, timeout=10), news.connect() as conn:
        item = review_store.article(conn, article_id)
        if source_policy(item['source_id']) != 'government_candidate':
            raise ValueError('This source is link-only')
        revision = conn.execute('SELECT revision FROM review_drafts WHERE article_id=?', (article_id,)).fetchone()
        actual = revision['revision'] if revision else 0
        if data.get('revision') != actual:
            raise ValueError('Draft changed; reload')
        job = review_worker.enqueue(conn, article_id, 'capture', {'actor': user['username'], 'revision': actual})
        review_store.audit(conn, user['username'], article_id, 'capture_queued', job)
    return {'job_id': job}


@app.post('/api/articles/{article_id}/draft')
async def draft(article_id: int, request: Request, user=Depends(admin_auth.require)):
    data = await request.json()
    revision = review_store.save_draft(article_id, data['document'], data['revision'], user['username'])
    return {'revision': revision}


@app.post('/api/articles/{article_id}/approve')
async def approve(article_id: int, request: Request, user=Depends(admin_auth.require)):
    data = await request.json()
    if data.get('license_checked') is not True or data.get('complete_checked') is not True:
        raise ValueError('Confirm text permission and completeness first')
    with operation_lock(news.DB_PATH, timeout=10), news.connect() as conn:
        item = review_store.article(conn, article_id)
        if source_policy(item['source_id']) != 'government_candidate':
            raise ValueError('This source is link-only')
        row = conn.execute('SELECT * FROM review_drafts WHERE article_id=?', (article_id,)).fetchone()
        if not row or row['revision'] != data.get('revision'):
            raise ValueError('Draft changed or missing; save/reload before approving')
        document = json.loads(row['document'])
        document.pop('publication_mode', None)
        document['completeness'] = 'complete_checked'
        document.update(reviewer=user['username'], reviewed_at=news.now())
        if not reading.permitted(document['permissions']['text']):
            raise ValueError('Specify a current public-web text permission')
        result = reading.publish(document, republish=data.get('republish') is True, conn=conn)
        conn.execute('UPDATE review_drafts SET document=?,revision=revision+1,updated_at=? WHERE article_id=?',
                     (reading.validate(document), news.now(), article_id))
        review_store.audit(conn, user['username'], article_id, 'approve', result['version'])
    return result


@app.post('/api/articles/{article_id}/withdraw')
async def withdraw(article_id: int, request: Request, user=Depends(admin_auth.require)):
    data = await request.json()
    reading.withdraw(article_id, user['username'], data.get('reason', ''))
    return {'withdrawn': True}


@app.post('/api/articles/{article_id}/images')
async def image(article_id: int, request: Request, user=Depends(admin_auth.require)):
    data = await request.json()
    if data.get('position_checked') is not True or type(data.get('block_index')) is not int:
        raise ValueError('Confirm this image belongs to the article and its display position')
    permission = data['permission']
    if not isinstance(permission, dict) or permission.get('status') not in reading.ALLOWED:
        raise ValueError('Confirm an image permission')
    for field in ('basis', 'rightsholder', 'third_party_check'):
        reading.plain(permission.get(field), 4000)
    if permission.get('expires_at'):
        from datetime import datetime
        if datetime.fromisoformat(permission['expires_at']).tzinfo is None:
            raise ValueError('Image expiry must include timezone')
    if permission.get('purpose') != 'public_web_image' or not reading.permitted(permission):
        raise ValueError('Image permission must cover public web display')
    for field in ('caption', 'credit'):
        reading.plain(data.get(field), 2000)
    with operation_lock(news.DB_PATH, timeout=10), news.connect() as conn:
        item = review_store.article(conn, article_id)
        edition = reading.editions(conn, [article_id]).get(article_id)
        if reading.public_content(item, edition)['reading_mode'] != 'full_text':
            raise ValueError('Publish reviewed text first')
        row = conn.execute('SELECT candidates,document,revision FROM review_drafts WHERE article_id=?', (article_id,)).fetchone()
        if not row or row['revision'] != data.get('revision') or hashlib.sha256(reading.validate(json.loads(row['document'])).encode()).hexdigest()[:24] != edition['version']:
            raise ValueError('Draft changed; publish the current draft before approving images')
        if not 0 <= data['block_index'] <= len(json.loads(row['document'])['blocks']):
            raise ValueError('Image position outside current text; select a new position')
        count = conn.execute('SELECT COUNT(*) FROM article_assets WHERE article_id=? AND content_version=?', (article_id, edition['version'])).fetchone()[0]
        queued = conn.execute("SELECT COUNT(*) FROM review_jobs WHERE article_id=? AND kind='image' AND state IN ('queued','running')", (article_id,)).fetchone()[0]
        if count+queued >= 5:
            raise ValueError('Maximum five images per edition')
        candidates = json.loads(row['candidates']) if row else []
        candidate = next((value for value in candidates if value['source_url'] == data.get('source_url')), None)
        if candidate is None:
            raise ValueError('Image must come from this captured draft')
        duplicate = conn.execute("SELECT 1 FROM article_assets WHERE article_id=? AND content_version=? AND source_url=? AND status='ready'", (article_id, edition['version'], candidate['source_url'])).fetchone()
        pending = conn.execute("SELECT 1 FROM review_jobs WHERE article_id=? AND kind='image' AND state IN ('queued','running') AND json_extract(payload,'$.source_url')=?", (article_id, candidate['source_url'])).fetchone()
        if duplicate or pending:
            raise ValueError('Image is already stored or queued')
        checked_url(item['source_id'], candidate['source_url'], image=True)
        payload = {**candidate, 'block_index': data['block_index'], 'caption': data['caption'], 'credit': data['credit'], 'permission': permission,
                   'version': edition['version'], 'actor': user['username']}
        payload['permission'].update(reviewer=user['username'], reviewed_at=news.now())
        job = review_worker.enqueue(conn, article_id, 'image', payload)
        review_store.audit(conn, user['username'], article_id, 'image_approved', job)
    return {'job_id': job}


@app.post('/api/assets/{asset_id}/withdraw')
async def withdraw_asset(asset_id: str, request: Request, user=Depends(admin_auth.require)):
    data = await request.json()
    reason = reading.plain(data.get('reason'), 2000)
    with news.connect() as conn:
        row = conn.execute('SELECT article_id FROM article_assets WHERE id=?', (asset_id,)).fetchone()
        if not row:
            raise ValueError('Asset not found')
        conn.execute("UPDATE article_assets SET status='withdrawn' WHERE id=?", (asset_id,))
        review_store.audit(conn, user['username'], row['article_id'], 'withdraw_image', reason)
    return {'withdrawn': True}
