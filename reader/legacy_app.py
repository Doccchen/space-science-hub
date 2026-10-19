"""Upload-and-read sessions. No accounts, personal library or note endpoints."""
import asyncio
import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime,timezone,timedelta
from pathlib import Path
from urllib.parse import unquote

from fastapi import FastAPI,Request,Response,Depends,HTTPException
from fastapi.responses import FileResponse,JSONResponse,RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
from .config import Settings
from .store import Store,uid
from . import worker,retrieval,temporary

ROOT=Path(__file__).resolve().parent.parent
COOKIE='zhihang_temporary'


class Question(BaseModel):
    question:str=Field(min_length=2,max_length=1500)
    session_id:str=Field(pattern=r'^[a-f0-9]{32}$')
    request_key:str=Field(pattern=r'^[a-zA-Z0-9-]{16,80}$')
    external_consent:bool=False


def create_app(settings=None):
    settings=settings or Settings()
    store=Store(settings)
    upload_lock=asyncio.Lock()
    model_limit=asyncio.Semaphore(2)
    entrants=deque(maxlen=1000)
    keyfile=store.root/'session.key'
    if not keyfile.exists():keyfile.write_bytes(secrets.token_bytes(32))
    key=keyfile.read_bytes()

    def sign(token):return hmac.new(key,token.encode(),hashlib.sha256).hexdigest()

    def network_key(request):
        peer=request.client.host if request.client else 'unknown'
        if peer in settings.trusted_proxies.split(','):
            forwarded=request.headers.get('x-reader-client-ip','')
            try:peer=str(ipaddress.ip_address(forwarded))
            except ValueError:pass
        return hmac.new(key,('network:'+peer).encode(),hashlib.sha256).hexdigest()

    async def clean_loop():
        while True:
            async with upload_lock:temporary.sweep(store)
            await asyncio.sleep(15)

    @asynccontextmanager
    async def lifespan(app):
        store.recover();temporary.sweep(store)
        jobs=[asyncio.create_task(worker.loop(store)),asyncio.create_task(clean_loop())]
        yield
        for job in jobs:job.cancel()
        await asyncio.gather(*jobs,return_exceptions=True)

    app=FastAPI(title='知航 · 上传即读',lifespan=lifespan,docs_url=None,redoc_url=None)
    app.state.store=store

    @app.middleware('http')
    async def boundary(request,call_next):
        if request.url.path.startswith('/api/reader') and request.method not in ('GET','HEAD','OPTIONS'):
            expected=settings.public_origin or f'{request.url.scheme}://{request.url.netloc}'
            if request.headers.get('sec-fetch-site')=='cross-site' or (request.headers.get('origin') and request.headers['origin']!=expected):
                return JSONResponse({'detail':'请从知航网站发起操作。'},403)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='same-origin'
        response.headers['X-Frame-Options']='SAMEORIGIN'
        if request.url.path.startswith('/api/reader'):response.headers['Cache-Control']='no-store'
        return response

    def owner(request:Request):
        cookie=request.cookies.get(COOKIE,'')
        if '.' not in cookie:raise HTTPException(401,'请重新开始临时阅读会话。')
        token,signature=cookie.split('.',1)
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}',token) or not hmac.compare_digest(signature.encode(),sign(token).encode()):
            raise HTTPException(401,'阅读会话无效。')
        identity=hashlib.sha256(token.encode()).hexdigest()
        with store.connect() as db:row=db.execute('SELECT expires FROM visitors WHERE owner=?',(identity,)).fetchone()
        if not row or row['expires']<=time.time():
            raise HTTPException(410,'临时阅读已到期，文件将被清理，请重新上传。')
        return identity

    def paper_for(paper_id,owner_id):
        with store.connect() as db:row=db.execute('SELECT * FROM papers WHERE id=? AND owner=?',(paper_id,owner_id)).fetchone()
        if not row:raise HTTPException(404,'未找到当前会话中的论文。')
        return dict(row)

    @app.get('/api/reader/health')
    def health():return {'status':'ok','service':'temporary-reader'}

    @app.get('/api/reader/config')
    def config():
        return {'max_bytes':settings.max_bytes,'max_pages':settings.max_pages,'session_seconds':settings.session_seconds,
                'model_enabled':bool(settings.model_key),'model':settings.model if settings.model_key else '',
                'verification_enabled':settings.verify_answers,'daily_calls':settings.daily_calls}

    @app.post('/api/reader/session')
    def start(request:Request,response:Response):
        try:identity=owner(request)
        except HTTPException:identity=None
        if not identity:
            now=time.monotonic()
            while entrants and entrants[0]<now-60:entrants.popleft()
            if len(entrants)>=30:raise HTTPException(429,'开始阅读的请求过多，请稍后再试。')
            entrants.append(now)
            token=secrets.token_urlsafe(32);identity=hashlib.sha256(token.encode()).hexdigest()
            expires=time.time()+settings.session_seconds
            with store.connect() as db:
                db.execute('INSERT INTO visitors VALUES(?,?,?)',(identity,expires,network_key(request)))
            response.set_cookie(COOKIE,token+'.'+sign(token),httponly=True,secure=settings.secure_cookie,
                                samesite='strict',path='/api/reader',max_age=settings.session_seconds)
        return {'started':True}

    @app.get('/api/reader/current')
    def current(owner_id=Depends(owner)):
        with store.connect() as db:
            paper=db.execute('SELECT * FROM papers WHERE owner=? ORDER BY created DESC LIMIT 1',(owner_id,)).fetchone()
            expires=db.execute('SELECT expires FROM visitors WHERE owner=?',(owner_id,)).fetchone()['expires']
        return {'paper':store.public(paper) if paper else None,'expires':expires}

    @app.post('/api/reader/end')
    async def end(owner_id=Depends(owner)):
        async with upload_lock:
            ids=temporary.discard(store,owner_id)
            for _ in range(20):
                if not temporary.remove_files(store,ids):break
                await asyncio.sleep(.1)
            else:raise HTTPException(503,'阅读记录已清除，文件仍被解析进程占用，后台将继续清理。')
        return {'cleared':True,'message':'当前原文件、解析数据、任务和问答已清除；匿名用量记录保留用于限额。'}

    @app.post('/api/reader/papers',status_code=202)
    async def upload(request:Request,owner_id=Depends(owner)):
        if request.headers.get('content-type','').split(';')[0]!='application/pdf':raise HTTPException(415,'请选择 PDF 文件。')
        filename=unquote(request.headers.get('x-filename','paper.pdf'))[:250]
        if not filename.lower().endswith('.pdf'):raise HTTPException(415,'文件扩展名须为 .pdf。')
        paper_id=uid();target=store.root/'files'/(paper_id+'.upload');size=0;digest=hashlib.sha256()
        async with upload_lock:
            temporary.sweep(store)
            with store.connect() as db:
                used=db.execute('SELECT COALESCE(SUM(size),0) FROM papers').fetchone()[0]
            try:
                with target.open('wb') as output:
                    async for chunk in request.stream():
                        size+=len(chunk)
                        if size>settings.max_bytes or size+used>settings.site_storage_bytes:
                            raise HTTPException(413,'文件超过上传上限，或临时存储已满，请稍后再试。')
                        output.write(chunk);digest.update(chunk)
                import pymupdf
                try:
                    with pymupdf.open(target) as document:
                        if not document.is_pdf or document.needs_pass or not 1<=len(document)<=settings.max_pages:raise ValueError()
                except Exception:raise HTTPException(422,'PDF 无法读取、已加密或页数超限；原阅读文件未替换。') from None
                with store.connect() as db:
                    duplicate=db.execute('SELECT * FROM papers WHERE owner=? AND hash=?',(owner_id,digest.hexdigest())).fetchone()
                    if duplicate:return {'paper':store.public(duplicate),'duplicate':True}
                    recent=db.execute('SELECT COUNT(*) FROM upload_events WHERE created>? AND ip_digest=?',(time.time()-86400,network_key(request))).fetchone()[0]
                    if recent>=20:raise HTTPException(429,'本网络今天的上传次数已达上限，请稍后再试。')
                now=time.time();task_id=uid()
                # Replace only after the new PDF has passed upload validation.
                target.replace(store.root/'files'/(paper_id+'.pdf'))
                try:
                  with store.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    previous=[r['id'] for r in db.execute('SELECT id FROM papers WHERE owner=?',(owner_id,))]
                    db.execute('DELETE FROM papers WHERE owner=?',(owner_id,))
                    db.execute('INSERT INTO papers(id,owner,hash,filename,size,title,created,updated) VALUES(?,?,?,?,?,?,?,?)',
                               (paper_id,owner_id,digest.hexdigest(),filename,size,filename.rsplit('.',1)[0],now,now))
                    db.execute('INSERT INTO tasks(id,paper,owner,version,state,attempt,created,updated) VALUES(?,?,?,?,?,?,?,?)',
                               (task_id,paper_id,owner_id,1,'queued',1,now,now))
                    db.execute('INSERT INTO upload_events VALUES(?,?,?)',(uid(),network_key(request),now))
                except Exception:
                    (store.root/'files'/(paper_id+'.pdf')).unlink(missing_ok=True)
                    raise
                temporary.remove_files(store,previous)
                return {'paper':store.public(paper_for(paper_id,owner_id)),'task_id':task_id,'duplicate':False}
            finally:target.unlink(missing_ok=True)

    @app.get('/api/reader/papers/{paper_id}')
    def detail(paper_id: str, owner_id=Depends(owner)):
        paper = paper_for(paper_id, owner_id)
        with store.connect() as db:
            tasks = [dict(r) for r in db.execute('SELECT id,version,state,attempt,error,duration,created,updated FROM tasks WHERE paper=? AND owner=? ORDER BY created DESC', (paper_id, owner_id))]
        return {**store.public(paper), 'tasks': tasks}

    @app.delete('/api/reader/papers/{paper_id}')
    async def delete(paper_id: str, owner_id=Depends(owner)):
        async with upload_lock:
            paper_for(paper_id,owner_id)
            temporary.discard(store,owner_id,paper_id)
        return {'deleted':True}

    @app.post('/api/reader/papers/{paper_id}/reparse', status_code=202)
    def reparse(paper_id: str, owner_id=Depends(owner)):
        now, task_id = time.time(), uid()
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM papers WHERE id=? AND owner=?', (paper_id, owner_id)).fetchone()
            if not row:
                raise HTTPException(404, '未找到该文献。')
            count = db.execute('SELECT COUNT(*) FROM tasks WHERE paper=?', (paper_id,)).fetchone()[0]
            if row['status'] in ('queued', 'parsing') or count >= 3:
                raise HTTPException(409, '正在解析或已达每文献三次解析上限。')
            version = row['version']+1
            db.execute("UPDATE papers SET version=?,status='queued',error='',updated=? WHERE id=?", (version, now, paper_id))
            db.execute('INSERT INTO tasks(id,paper,owner,version,state,attempt,created,updated) VALUES(?,?,?,?,?,?,?,?)',
                       (task_id, paper_id, owner_id, version, 'queued', count+1, now, now))
        return {'task_id': task_id, 'version': version}

    @app.get('/api/reader/tasks/{task_id}')
    def task_status(task_id: str, owner_id=Depends(owner)):
        with store.connect() as db:
            row = db.execute('SELECT id,paper,version,state,attempt,error,duration,created,updated FROM tasks WHERE id=? AND owner=?', (task_id, owner_id)).fetchone()
        if not row:
            raise HTTPException(404, '未找到任务。')
        return dict(row)

    @app.get('/api/reader/papers/{paper_id}/file')
    def original(paper_id: str, owner_id=Depends(owner)):
        paper_for(paper_id, owner_id)
        return FileResponse(store.root / 'files' / (paper_id+'.pdf'), media_type='application/pdf',
                            headers={'Content-Disposition': 'inline; filename="paper.pdf"'})

    @app.get('/api/reader/papers/{paper_id}/pages/{page}.png')
    def page_image(paper_id: str, page: int, owner_id=Depends(owner)):
        paper = paper_for(paper_id, owner_id)
        coverage = json.loads(paper['coverage'])
        if paper['status'] not in ('ready', 'partial') or not 1 <= page <= coverage.get('pages', 0):
            raise HTTPException(404, '该页尚不可读取。')
        # Rendering is bounded by a fixed pixel width, independent of malicious PDF dimensions.
        import pymupdf
        try:
            with pymupdf.open(store.root / 'files' / (paper_id+'.pdf')) as pdf:
                rect = pdf[page-1].rect
                scale = min(1.5, 1500/max(rect.width, rect.height, 1))
                pixmap = pdf[page-1].get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
                return Response(pixmap.tobytes('png'), media_type='image/png')
        except Exception:
            raise HTTPException(422, '此页渲染失败，请打开原始 PDF 核对。') from None

    @app.get('/api/reader/papers/{paper_id}/blocks')
    def parsed_blocks(paper_id: str, version: int | None = None, owner_id=Depends(owner)):
        paper = paper_for(paper_id, owner_id)
        version = version or paper['version']
        return {'version': version, 'stale': version != paper['version'],
                'items': [retrieval.citation(b, paper) for b in store.blocks(paper_id, version)]}

    @app.get('/api/reader/papers/{paper_id}/map')
    def reading_map(paper_id: str, owner_id=Depends(owner)):
        paper = paper_for(paper_id, owner_id)
        return {'version': paper['version'], 'coverage': json.loads(paper['coverage']),
                'groups': retrieval.map_sections(store.blocks(paper_id, paper['version']), paper)}

    @app.post('/api/reader/papers/{paper_id}/sessions')
    def reading_session(paper_id: str, owner_id=Depends(owner)):
        paper = paper_for(paper_id, owner_id)
        if paper['status'] not in ('ready', 'partial'):
            raise HTTPException(409, '请等待解析完成。')
        session_id = uid()
        with store.connect() as db:
            db.execute('INSERT INTO sessions VALUES(?,?,?,?,?)', (session_id, paper_id, owner_id, paper['version'], time.time()))
        return {'id': session_id, 'paper_id': paper_id, 'version': paper['version']}

    @app.get('/api/reader/papers/{paper_id}/answers')
    def history(paper_id: str, owner_id=Depends(owner)):
        paper_for(paper_id, owner_id)
        with store.connect() as db:
            rows = db.execute('SELECT id,version,question,result,state,created FROM answers WHERE paper=? AND owner=? ORDER BY created', (paper_id, owner_id)).fetchall()
        return {'items': [{**dict(r), 'result': json.loads(r['result']) if r['result'] else None} for r in rows]}

    @app.post('/api/reader/papers/{paper_id}/ask')
    async def ask(paper_id: str, body: Question, request: Request, owner_id=Depends(owner)):
        paper = paper_for(paper_id, owner_id)
        if settings.model_key and not body.external_consent:
            raise HTTPException(400, '请确认将当前问题和检索片段发送给已配置的外部模型服务。')
        question = body.question.strip()
        if len(question) < 2:
            raise HTTPException(422, '请输入至少两个有效字符。')
        answer_id = uid()
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            session = db.execute('SELECT * FROM sessions WHERE id=? AND paper=? AND owner=?', (body.session_id, paper_id, owner_id)).fetchone()
            if not session:
                raise HTTPException(404, '未找到该阅读会话。')
            if session['version'] != paper['version'] or paper['status'] not in ('ready', 'partial'):
                raise HTTPException(409, '解析版本已改变，请重新打开文献。')
            old = db.execute('SELECT * FROM answers WHERE owner=? AND request_key=?', (owner_id, body.request_key)).fetchone()
            if old:
                if old['paper'] != paper_id or old['version'] != paper['version'] or old['question'] != question:
                    raise HTTPException(409, '重复请求标识与原问题不一致。')
                if old['result']:
                    return json.loads(old['result'])
                raise HTTPException(409, '该请求已处理或已中断，不会自动重复调用。')
            if db.execute('SELECT 1 FROM usage WHERE owner=? AND request_key=?', (owner_id, body.request_key)).fetchone():
                raise HTTPException(409, '该请求标识已使用，请创建新问题。')
            day_start = datetime.now(timezone(timedelta(hours=8))).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            used = db.execute('SELECT COUNT(*) FROM usage WHERE owner=? AND created>=?', (owner_id, day_start)).fetchone()[0]
            network_used=db.execute('SELECT COUNT(*) FROM network_usage WHERE ip_digest=? AND created>=?',(network_key(request),day_start)).fetchone()[0]
            site = db.execute('SELECT COUNT(*),COALESCE(SUM(tokens),0) FROM usage WHERE created>=?', (day_start,)).fetchone()
            reservation = (32000 if settings.verify_answers else 16000) if settings.model_key else 0
            running = db.execute("SELECT COUNT(*) FROM usage WHERE state='running'").fetchone()[0]
            if used >= settings.daily_calls or network_used >= settings.ip_calls or site[0] >= settings.site_calls or site[1]+reservation > settings.site_tokens or running >= 2:
                raise HTTPException(429, '今日问答额度已用完或并发已满，请稍后再试。')
            db.execute('INSERT INTO answers VALUES(?,?,?,?,?,?,?,?,?)',
                       (answer_id, paper_id, owner_id, paper['version'], body.request_key, question, None, 'running', time.time()))
            db.execute('INSERT INTO usage(id,owner,request_key,created,state,model,tokens) VALUES(?,?,?,?,?,?,?)',
                       (answer_id, owner_id, body.request_key, time.time(), 'running', int(bool(settings.model_key)), reservation))
            db.execute('INSERT INTO network_usage VALUES(?,?,?)',(answer_id,network_key(request),time.time()))
        started = time.monotonic()
        try:
            async with model_limit:
                result = await asyncio.wait_for(retrieval.answer(settings, paper, store.blocks(paper_id, paper['version']), question), 45)
            result.update({'id': answer_id, 'question': question, 'duration_seconds': round(time.monotonic()-started, 3)})
            with store.connect() as db:
                model_called = result['mode'] == 'model'
                tokens_used = result['usage'].get('total_tokens', reservation) if model_called else 0
                db.execute("UPDATE usage SET state='done',duration=?,tokens=?,model=? WHERE id=?", (time.monotonic()-started, tokens_used, int(model_called), answer_id))
                current = db.execute('SELECT version FROM papers WHERE id=? AND owner=?', (paper_id, owner_id)).fetchone()
                if not current or current['version'] != paper['version']:
                    db.execute("UPDATE answers SET state='interrupted' WHERE id=?", (answer_id,))
                    raise HTTPException(409, '生成期间文献已删除或重新解析，结果已作废。')
                db.execute("UPDATE answers SET result=?,state='done' WHERE id=?", (json.dumps(result, ensure_ascii=False), answer_id))
            return result
        except HTTPException:
            with store.connect() as db:
                db.execute("UPDATE usage SET state='interrupted',duration=? WHERE id=? AND state='running'", (time.monotonic()-started, answer_id))
                db.execute("UPDATE answers SET state='interrupted' WHERE id=? AND state='running'", (answer_id,))
            raise
        except BaseException as error:
            with store.connect() as db:
                db.execute("UPDATE answers SET state='failed' WHERE id=?", (answer_id,))
                db.execute("UPDATE usage SET state='failed',duration=? WHERE id=?", (time.monotonic()-started, answer_id))
            if isinstance(error, asyncio.CancelledError):
                raise
            if isinstance(error, retrieval.ModelFailure):
                raise HTTPException(502, str(error)) from None
            raise HTTPException(502, '问答未完成：模型连接、响应格式或引用验证失败。未自动重试；本次请求已记录。') from None


    @app.get('/reader')
    def slash():return RedirectResponse('/reader/',status_code=308)

    @app.get('/reader/')
    def home():return FileResponse(ROOT/'reader_web/index.html')

    app.mount('/reader-assets',StaticFiles(directory=ROOT/'reader_web'),name='reader-assets')
    return app

app=create_app()
