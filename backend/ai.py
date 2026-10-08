"""Anonymous, bounded AI sessions stored separately from the news database."""
import asyncio
import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .bailian import AIError, BailianClient

router = APIRouter(prefix='/api/ai', tags=['ai'])
COOKIE = 'space_ai_visitor'
MESSAGES = {
    'disabled':'知识库问答暂未开放。', 'configuration':'知识库问答正在配置，请稍后再试。',
    'session_expired':'此对话已结束或过期，请开始新对话。', 'session_busy':'当前对话正在回答，请等待完成。',
    'capacity':'当前提问较多，请稍后再试。', 'rate_limit':'提问过于频繁，请稍后再试。',
    'daily_limit':'今日问答额度已用完，请明天再试。', 'history_limit':'本次对话已达到长度上限，请开始新对话。',
    'request_conflict':'请求标识已使用，请重新提交。', 'upstream_auth':'知识库服务配置暂不可用。',
    'upstream_timeout':'回答等待超时，本次不会自动重试。请稍后再试。',
    'upstream_rate_limit':'知识库服务繁忙，请稍后再试。', 'upstream_network':'暂时无法连接知识库服务。',
    'upstream_error':'知识库服务暂时无法回答，请稍后再试。', 'upstream_format':'回答格式暂时无法识别。',
    'incomplete_answer':'未收到完整回答，请稍后再试。', 'answer_too_long':'本次回答过长，请缩小问题范围。',
    'storage':'对话暂时无法保存，请稍后再试。', 'origin':'请从本站页面发起问答。',
}


@dataclass
class Settings:
    enabled: bool = False
    key: str = ''
    workspace: str = 'llm-ep9bqc9mnw50k8e0'
    agent: str = 'aid-066ddd0b6e1e44d6bf7d620e0ac7c060'
    version: str = '1'
    db: Path = Path('/data/ai.sqlite3')
    secure_cookie: bool = False
    timeout: int = 60
    concurrency: int = 2
    visitor_daily: int = 20
    ip_daily: int = 30
    site_daily: int = 100
    minute_limit: int = 4
    token_daily: int = 200000
    token_reservation: int = 20000
    ttl: int = 3600
    rounds: int = 5

    @classmethod
    def environment(cls):
        from . import news
        values = dict(enabled=os.getenv('AI_ENABLED','0') == '1', key=os.getenv('DASHSCOPE_API_KEY',''),
                      workspace=os.getenv('BAILIAN_WORKSPACE_ID', cls.workspace),
                      agent=os.getenv('BAILIAN_AGENT_ID', cls.agent), version=os.getenv('AI_CONFIG_VERSION','1'),
                      db=Path(os.getenv('AI_DB_PATH',str(news.DB_PATH.parent/'ai.sqlite3'))),
                      secure_cookie=os.getenv('AI_COOKIE_SECURE','0') == '1')
        for name, env in [('timeout','AI_TIMEOUT_SECONDS'),('concurrency','AI_CONCURRENCY'),
                          ('visitor_daily','AI_VISITOR_DAILY_LIMIT'),('ip_daily','AI_IP_DAILY_LIMIT'),
                          ('site_daily','AI_SITE_DAILY_LIMIT'),('token_daily','AI_DAILY_TOKEN_LIMIT'),
                          ('token_reservation','AI_TOKEN_RESERVATION')]:
            value = int(os.getenv(env,str(getattr(cls,name))))
            if not 1 <= value <= 10000000:
                raise ValueError('invalid_setting')
            values[name] = value
        values['timeout'] = min(values['timeout'],120)
        values['concurrency'] = min(values['concurrency'],4)
        return cls(**values)


class AIService:
    def __init__(self, settings, client=None):
        self.settings = settings
        self.problem = None
        self.client = client or BailianClient(settings.workspace,settings.agent,settings.key,settings.timeout)
        self.active = 0
        self.initialized = False
        self.last_upstream_error = None
        if not settings.enabled:
            self.problem = 'disabled'
        elif not settings.key or not re.fullmatch(r'[A-Za-z0-9-]+',settings.workspace) or not re.fullmatch(r'aid-[A-Za-z0-9-]+',settings.agent):
            self.problem = 'configuration'
        else:
            try:
                self.initialize()
                self.initialized = True
            except OSError:
                self.problem = 'storage'
            except sqlite3.Error:
                self.problem = 'storage'

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.settings.db, timeout=.3)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def initialize(self):
        self.settings.db.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
              CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                version TEXT NOT NULL, expires REAL NOT NULL, history TEXT NOT NULL DEFAULT '[]', deleted INTEGER NOT NULL DEFAULT 0);
              CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY, conversation TEXT NOT NULL, owner TEXT NOT NULL,
                ip TEXT NOT NULL, fingerprint TEXT NOT NULL, created REAL NOT NULL, status TEXT NOT NULL,
                reservation INTEGER NOT NULL, tokens INTEGER, usage TEXT, provider_id TEXT, result TEXT, error TEXT);
              CREATE INDEX IF NOT EXISTS requests_created ON requests(created);
              CREATE INDEX IF NOT EXISTS requests_owner ON requests(owner,created);
              CREATE INDEX IF NOT EXISTS requests_ip ON requests(ip,created);
            ''')
            # A single worker may have stopped during a charged request; retain its quota reservation.
            db.execute("UPDATE requests SET status='error',error='incomplete_answer' WHERE status='pending'")

    def ready(self):
        if self.problem:
            raise AIError(self.problem)

    def ensure_storage(self):
        if not self.initialized:
            self.initialize()
            self.initialized = True

    def apply_settings(self, settings, client=None):
        if settings.db != self.settings.db:
            raise AIError('configuration')
        if settings.enabled and (not settings.key or not re.fullmatch(r'[A-Za-z0-9-]+', settings.workspace)
                                 or not re.fullmatch(r'aid-[A-Za-z0-9-]+', settings.agent)):
            raise AIError('configuration')
        self.ensure_storage()
        # No await: readers capture this pair before starting the upstream request.
        self.settings = settings
        self.client = client or BailianClient(settings.workspace, settings.agent, settings.key, settings.timeout)
        self.problem = None if settings.enabled else 'disabled'
        self.last_upstream_error = None

    def cleanup(self, db, now):
        db.execute("UPDATE conversations SET history='[]',deleted=1 WHERE expires<?",(now,))
        db.execute("UPDATE requests SET result=NULL WHERE conversation IN (SELECT id FROM conversations WHERE deleted=1)")
        db.execute('DELETE FROM requests WHERE created<?',(now-30*86400,))
        db.execute('DELETE FROM conversations WHERE expires<?',(now-30*86400,))

    def create(self, owner):
        self.ready()
        import uuid
        identity, now = str(uuid.uuid4()), time.time()
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            self.cleanup(db,now)
            # Bound anonymous session allocation independently of charged calls.
            count = db.execute('SELECT COUNT(*) FROM conversations WHERE deleted=0').fetchone()[0]
            mine = db.execute('SELECT COUNT(*) FROM conversations WHERE owner=? AND deleted=0',(owner,)).fetchone()[0]
            if count >= 1000 or mine >= 5:
                raise AIError('capacity',429)
            db.execute('INSERT INTO conversations(id,owner,version,expires) VALUES(?,?,?,?)',
                       (identity,owner,self.settings.version,now+self.settings.ttl))
        return identity

    def conversation(self, db, identity, owner, version=None):
        row = db.execute('SELECT * FROM conversations WHERE id=? AND owner=?',(identity,owner)).fetchone()
        if not row or row['deleted'] or row['expires'] < time.time() or row['version'] != (version or self.settings.version):
            raise AIError('session_expired',409)
        return row

    def delete(self, identity, owner):
        self.ready()
        with self.connection() as db:
            self.conversation(db,identity,owner)
            db.execute("UPDATE conversations SET deleted=1,history='[]' WHERE id=?",(identity,))
            db.execute('UPDATE requests SET result=NULL WHERE conversation=?',(identity,))

    def reserve(self, identity, owner, ip, request_id, question, settings=None):
        settings = settings or self.settings
        now, fingerprint = time.time(), hashlib.sha256(question.encode()).hexdigest()
        identity_key = hashlib.sha256((owner+request_id).encode()).hexdigest()
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            self.cleanup(db,now)
            conversation = self.conversation(db,identity,owner,settings.version)
            existing = db.execute('SELECT * FROM requests WHERE id=?',(identity_key,)).fetchone()
            if existing:
                if existing['conversation'] != identity or existing['fingerprint'] != fingerprint:
                    raise AIError('request_conflict',409)
                if existing['status'] == 'complete' and existing['result']:
                    return identity_key, None, json.loads(existing['result'])
                raise AIError(existing['error'] or 'session_busy',409)
            if db.execute("SELECT 1 FROM requests WHERE conversation=? AND status='pending'",(identity,)).fetchone():
                raise AIError('session_busy',409)
            if self.active >= settings.concurrency:
                raise AIError('capacity',429)
            history = json.loads(conversation['history'])
            if len(history)//2 >= settings.rounds or sum(len(item['content']) for item in history)+len(question)>16000:
                raise AIError('history_limit',409)
            self.check_budget(db, owner, ip, settings, now)
            db.execute('INSERT INTO requests(id,conversation,owner,ip,fingerprint,created,status,reservation) VALUES(?,?,?,?,?,?,?,?)',
                       (identity_key,identity,owner,ip,fingerprint,now,'pending',settings.token_reservation))
        return identity_key, history+[{'role':'user','content':question}], None

    async def ask(self, identity, owner, ip, request_id, question):
        self.ready()
        settings, client = replace(self.settings), self.client
        key, messages, cached = self.reserve(identity,owner,ip,request_id,question,settings)
        if cached is not None:
            return cached
        self.active += 1
        try:
            answer = await client.ask(messages, request_id)
            result = {'request_id':request_id,'conversation_id':identity,
                      'status':'answered' if answer.grounded else 'insufficient', 'answer':answer.text,
                      'sources':answer.sources,'source_label':'本次检索资料',
                      'notice':'检索资料不代表逐条结论已核实；位置为接口原始定位，页码口径尚未核实。',
                      'remaining_rounds':max(0,settings.rounds-len(messages)//2-1)}
            with self.connection() as db:
                db.execute('UPDATE requests SET tokens=?,usage=?,provider_id=? WHERE id=?',
                           ((answer.usage or {}).get('total_tokens'),json.dumps(answer.usage),answer.request_id,key))
            with self.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                self.conversation(db,identity,owner,settings.version)
                history = messages+[{'role':'assistant','content':answer.text}]
                db.execute('UPDATE conversations SET history=? WHERE id=?',(json.dumps(history,ensure_ascii=False),identity))
                db.execute("UPDATE requests SET status='complete',result=? WHERE id=?",(json.dumps(result,ensure_ascii=False),key))
            return result
        except BaseException as error:
            code = error.code if isinstance(error,AIError) else 'incomplete_answer'
            self.last_upstream_error = code
            with self.connection() as db:
                db.execute("UPDATE requests SET status='error',error=?,result=NULL WHERE id=?",(code,key))
            raise
        finally:
            self.active -= 1

    async def test_configuration(self, candidate, client=None):
        """One short paid test, charged to the same ledger and process-wide capacity."""
        import uuid
        self.ensure_storage()
        current = replace(self.settings)
        settings = replace(candidate, timeout=min(20,candidate.timeout,current.timeout),
                           concurrency=min(candidate.concurrency,current.concurrency),
                           site_daily=min(candidate.site_daily,current.site_daily),
                           token_daily=min(candidate.token_daily,current.token_daily),
                           token_reservation=max(candidate.token_reservation,current.token_reservation))
        if not settings.key:
            raise AIError('configuration')
        identity, now = 'admin-test-' + uuid.uuid4().hex, time.time()
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if self.active >= settings.concurrency:
                raise AIError('capacity',429)
            day = int((now+8*3600)//86400)*86400-8*3600
            count,tokens = db.execute('SELECT COUNT(*),COALESCE(SUM(COALESCE(tokens,reservation)),0) FROM requests WHERE created>=?',(day,)).fetchone()
            if count >= settings.site_daily or tokens + settings.token_reservation > settings.token_daily:
                raise AIError('daily_limit',429)
            db.execute('INSERT INTO requests(id,conversation,owner,ip,fingerprint,created,status,reservation) VALUES(?,?,?,?,?,?,?,?)',
                       (identity,'admin-test','admin-test','admin-test','fixed-test',now,'pending',settings.token_reservation))
        self.active += 1
        try:
            client = client or BailianClient(settings.workspace,settings.agent,settings.key,settings.timeout)
            answer = await client.ask([{'role':'user','content':'请简要介绍此知识库涵盖的主要主题。'}], identity)
            tokens = (answer.usage or {}).get('total_tokens')
            with self.connection() as db:
                db.execute("UPDATE requests SET status='complete',tokens=?,usage=?,provider_id=? WHERE id=?",
                           (tokens,json.dumps(answer.usage),answer.request_id,identity))
            return {'grounded':answer.grounded, 'source_count':len(answer.sources), 'tokens':tokens}
        except BaseException as error:
            code = error.code if isinstance(error,AIError) else 'incomplete_answer'
            with self.connection() as db:
                db.execute("UPDATE requests SET status='error',error=? WHERE id=?", (code, identity))
            raise
        finally:
            self.active -= 1

    def daily_usage(self):
        day = int((time.time()+8*3600)//86400)*86400-8*3600
        with self.connection() as db:
            row = db.execute('SELECT COUNT(*),COALESCE(SUM(COALESCE(tokens,reservation)),0),SUM(CASE WHEN status=\'pending\' THEN reservation ELSE 0 END) FROM requests WHERE created>=?', (day,)).fetchone()
        return {'requests':row[0], 'tokens_accounted':row[1], 'pending_reservation':row[2] or 0,
                'active':self.active, 'day_timezone':'Asia/Shanghai'}

    def reserve_news(self, job_id, owner, ip, question):
        """News calls share the existing global/visitor/IP ledger even if general chat is off."""
        self.ensure_storage()
        settings, now = self.settings, time.time()
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            ledger_id = 'news-' + job_id
            if db.execute('SELECT 1 FROM requests WHERE id=?', (ledger_id,)).fetchone():
                raise AIError('interrupted', 409)
            self.check_budget(db, owner, ip, settings, now)
            db.execute('INSERT INTO requests(id,conversation,owner,ip,fingerprint,created,status,reservation) VALUES(?,?,?,?,?,?,?,?)',
                       (ledger_id, ledger_id, owner, ip, hashlib.sha256(question.encode()).hexdigest(), now, 'pending', settings.token_reservation))
        return ledger_id

    def check_budget(self, db, owner, ip, settings, now):
        """Called inside the caller's ledger write transaction."""
        if self.active >= settings.concurrency:
            raise AIError('capacity', 429)
        day = int((now + 8 * 3600) // 86400) * 86400 - 8 * 3600
        for column, value, limit in [('owner', owner, settings.visitor_daily), ('ip', ip, settings.ip_daily)]:
            if db.execute(f'SELECT COUNT(*) FROM requests WHERE {column}=? AND created>=?', (value, day)).fetchone()[0] >= limit:
                raise AIError('daily_limit', 429)
        if db.execute('SELECT COUNT(*) FROM requests WHERE owner=? AND created>=?', (owner, now - 60)).fetchone()[0] >= settings.minute_limit:
            raise AIError('rate_limit', 429)
        count, tokens = db.execute('SELECT COUNT(*),COALESCE(SUM(COALESCE(tokens,reservation)),0) FROM requests WHERE created>=?', (day,)).fetchone()
        if count >= settings.site_daily or tokens + settings.token_reservation > settings.token_daily:
            raise AIError('daily_limit', 429)

    def finish_news(self, ledger_id, answer=None, error=None):
        with self.connection() as db:
            db.execute('UPDATE requests SET status=?,tokens=?,usage=?,provider_id=?,error=? WHERE id=?',
                       ('error' if error else 'complete', (answer.usage or {}).get('total_tokens') if answer else None,
                        json.dumps(answer.usage) if answer else None, answer.request_id if answer else None,
                        error, ledger_id))


def service_from_env():
    try:
        return AIService(Settings.environment())
    except (ValueError,TypeError):
        service = AIService(Settings())
        service.problem = 'configuration'
        return service


async def housekeeping(instance):
    while True:
        await asyncio.sleep(60)
        try:
            with instance.connection() as db:
                instance.cleanup(db,time.time())
        except sqlite3.Error:
            pass  # A later request also cleans up; AI storage issues do not stop news.


def service(request):
    instance = getattr(request.app.state,'ai',None)
    if instance is None:
        raise AIError('disabled')
    return instance


def identity(request):
    value = request.cookies.get(COOKIE) or request.cookies.get('space_news_visitor','')
    if not re.fullmatch(r'[a-f0-9]{64}',value):
        value = secrets.token_hex(32)
    return value, hashlib.sha256(value.encode()).hexdigest()


def origin_check(request):
    origin = request.headers.get('origin')
    if request.headers.get('sec-fetch-site') == 'cross-site' or (origin and origin != str(request.base_url).rstrip('/')):
        raise AIError('origin',403)


def error_response(error):
    return JSONResponse({'error':{'code':error.code,'message':MESSAGES.get(error.code,MESSAGES['upstream_error'])}},
                        status_code=error.status,headers={'Cache-Control':'no-store'})


class AskBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    conversation_id: UUID
    request_id: UUID
    question: str = Field(min_length=1,max_length=1500)


@router.get('/status')
def status(request: Request, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    try:
        instance = service(request)
        return {'enabled':not instance.problem,'message':MESSAGES.get(instance.problem,'基于本站专属知识库回答。'),
                'max_question_chars':1500,'max_rounds':instance.settings.rounds,'history_retention_seconds':instance.settings.ttl}
    except AIError:
        return {'enabled':False,'message':MESSAGES['disabled'],'max_question_chars':1500,'max_rounds':5,'history_retention_seconds':3600}


@router.post('/conversations')
def create_conversation(request: Request):
    try:
        origin_check(request)
        instance = service(request)
        cookie, owner = identity(request)
        response = JSONResponse({'conversation_id':instance.create(owner)},headers={'Cache-Control':'no-store'})
        response.set_cookie(COOKIE,cookie,max_age=86400,httponly=True,samesite='strict',secure=instance.settings.secure_cookie,path='/api')
        return response
    except AIError as error:
        return error_response(error)
    except sqlite3.Error:
        return error_response(AIError('storage'))
    except Exception:
        return error_response(AIError('upstream_error'))


@router.post('/visitor')
async def migrate_visitor(request: Request):
    """Inherit the old /api/ai cookie before starting news; no new owner or paid call."""
    try:
        origin_check(request)
        cookie, _ = identity(request)
        instance = service(request)
        response = Response(status_code=204, headers={'Cache-Control': 'no-store'})
        for name in (COOKIE, 'space_news_visitor'):
            response.set_cookie(name, cookie, max_age=86400, httponly=True, samesite='strict',
                                secure=instance.settings.secure_cookie, path='/api')
        return response
    except AIError as error:
        return error_response(error)


@router.delete('/conversations/{conversation_id}')
def delete_conversation(conversation_id: UUID, request: Request):
    try:
        origin_check(request)
        service(request).delete(str(conversation_id),identity(request)[1])
        return Response(status_code=204,headers={'Cache-Control':'no-store'})
    except AIError as error:
        return error_response(error)
    except sqlite3.Error:
        return error_response(AIError('storage'))


@router.post('/ask')
async def ask(body: AskBody, request: Request):
    try:
        origin_check(request)
        question = body.question.strip()
        if not question:
            return error_response(AIError('request_conflict',422))
        # Use the actual connection peer; do not trust arbitrary X-Forwarded-For.
        ip = hashlib.sha256((request.client.host if request.client else 'unknown').encode()).hexdigest()
        result = await service(request).ask(str(body.conversation_id),identity(request)[1],ip,str(body.request_id),question)
        return JSONResponse(result,headers={'Cache-Control':'no-store'})
    except AIError as error:
        return error_response(error)
    except sqlite3.Error:
        return error_response(AIError('storage'))
    except Exception:
        return error_response(AIError('upstream_error'))
