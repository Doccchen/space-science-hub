"""Independent news Agent limits and versioned administrator settings; no provider calls."""
import json
import os
import sqlite3
import time
from dataclasses import replace
from pathlib import Path
from contextlib import closing

from . import ai, management_store as store, news

FIELDS = ('timeout','concurrency','visitor_daily','ip_daily','site_daily','token_daily','token_reservation')
DEFAULTS = dict(timeout=120,concurrency=2,visitor_daily=20,ip_daily=30,site_daily=100,token_daily=200000,token_reservation=60000)


def baseline():
    values = {name:int(os.getenv('NEWS_AGENT_'+name.upper(),str(value))) for name,value in DEFAULTS.items()}
    return validate(values)


def validate(values):
    if not isinstance(values,dict) or set(values) != set(FIELDS):
        raise store.ManagementError('新闻 Agent 额度字段无效。',400)
    for name in FIELDS:
        maximum = 120 if name=='timeout' else 4 if name=='concurrency' else 10000000
        if type(values[name]) is not int or not 1 <= values[name] <= maximum:
            raise store.ManagementError('新闻 Agent 数值超出范围。',400)
    if values['token_reservation'] > values['token_daily']:
        raise store.ManagementError('新闻每次预留量不能超过新闻每日预算。',400)
    return values


def marker():
    return store.path().with_suffix('.news-limits-enabled')


def present():
    if not store.path().exists():
        if marker().exists(): raise store.ManagementError('新闻额度管理库丢失。',503)
        return False
    with store.connection() as db:
        exists = bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='news_limits_state'").fetchone())
    if marker().exists() and not exists: raise store.ManagementError('新闻额度配置表丢失。',503)
    return exists


def initialize():
    values = baseline()
    store.initialize()
    with store.connection(write=True) as db:
        db.execute('CREATE TABLE IF NOT EXISTS news_limits_versions(id INTEGER PRIMARY KEY,config TEXT NOT NULL,actor TEXT NOT NULL,created TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS news_limits_state(id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL,latest INTEGER NOT NULL,desired INTEGER NOT NULL,loaded INTEGER,previous INTEGER,heartbeat REAL,error TEXT,usage TEXT)')
        if not db.execute('SELECT 1 FROM news_limits_state WHERE id=1').fetchone():
            identity = db.execute('INSERT INTO news_limits_versions(config,actor,created) VALUES(?,?,?)',(json.dumps(values),'server-initialization',news.now())).lastrowid
            db.execute('INSERT INTO news_limits_state(id,revision,latest,desired) VALUES(1,1,?,?)',(identity,identity))
    marker().write_text('Independent news limits are authoritative\n')


def version(db,identity):
    if type(identity) is not int or identity < 1: raise store.ManagementError('新闻配置版本无效。',400)
    row = db.execute('SELECT * FROM news_limits_versions WHERE id=?',(identity,)).fetchone()
    if not row: raise store.ManagementError('新闻配置版本不存在。',404)
    return {'version':row['id'],'config':validate(json.loads(row['config'])),'actor':row['actor'],'created_at':row['created']}


def state(db):
    row=db.execute('SELECT * FROM news_limits_state WHERE id=1').fetchone()
    if not row:raise store.ManagementError('新闻额度状态不可用。',503)
    return dict(row)


def required():
    if not present(): raise store.ManagementError('新闻额度尚未在服务器初始化。',503)


def audit(db,actor,operation,identity):
    db.execute('INSERT INTO management_audit(resource_id,revision,actor,operation,created_at,summary) VALUES(NULL,?,?,?,?,?)',
               (identity,actor,operation,news.now(),json.dumps({'news_limits_version':identity})))


def save(body,actor):
    required()
    if not isinstance(body,dict) or set(body) != {'revision','config'}: raise store.ManagementError('新闻草稿格式无效。',400)
    values = validate(body['config'])
    with store.connection(write=True) as db:
        current = state(db)
        if type(body['revision']) is not int or body['revision'] != current['revision']: raise store.ManagementError('新闻额度已修改，请重新读取。')
        identity = db.execute('INSERT INTO news_limits_versions(config,actor,created) VALUES(?,?,?)',(json.dumps(values),actor,news.now())).lastrowid
        db.execute('UPDATE news_limits_state SET latest=?,revision=revision+1 WHERE id=1',(identity,))
        audit(db,actor,'news_limits_draft',identity)
    return {'version':identity}


def apply(body,actor):
    required()
    if not isinstance(body,dict) or set(body) != {'revision','version'}: raise store.ManagementError('新闻应用格式无效。',400)
    with store.connection(write=True) as db:
        current = state(db)
        if type(body['revision']) is not int or body['revision'] != current['revision']: raise store.ManagementError('新闻额度已修改，请重新读取。')
        identity = version(db,body['version'])['version']
        db.execute('UPDATE news_limits_state SET previous=desired,desired=?,revision=revision+1,error=NULL WHERE id=1',(identity,))
        audit(db,actor,'news_limits_apply',identity)
    return {'version':identity}


def overview():
    required()
    with store.connection() as db:
        current = state(db)
        result = {'revision':current['revision'],'draft':version(db,current['latest']),'desired':version(db,current['desired']),
                  'loaded':version(db,current['loaded']) if current['loaded'] else None,
                  'versions':[version(db,row[0]) for row in db.execute('SELECT id FROM news_limits_versions ORDER BY id DESC LIMIT 30')]}
    live = current['heartbeat'] and time.time()-current['heartbeat'] <= 5
    result.update(status='offline' if not live else 'failed' if current['error'] else 'applied' if current['loaded']==current['desired'] else 'pending',
                  heartbeat=current['heartbeat'],error=current['error'],usage=json.loads(current['usage']) if current['usage'] else None)
    return result


def usage_path():
    return Path(os.getenv('NEWS_AGENT_USAGE_DB_PATH',str(news.DB_PATH.parent/'news-agent-usage.sqlite3')))


def budget(values=None,*,initialize=False):
    if values is None:
        values = baseline()
        if present():
            with store.connection() as db:
                current = state(db); values = version(db,current['desired'])['config']
    path = usage_path()
    if marker().exists() and not initialize:
        if not path.is_file(): raise store.ManagementError('新闻用量库丢失，请恢复备份。',503)
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='requests'").fetchone():
                raise store.ManagementError('新闻用量表丢失，请恢复备份。',503)
    return ai.AIService(replace(ai.Settings(),enabled=False,db=path,**values))


def sync(service):
    if not present(): return
    if not service.budget.settings.db.is_file(): raise store.ManagementError('新闻用量库丢失。',503)
    with store.connection() as db:
        current = state(db); values = version(db,current['desired'])['config']
    # Limits only: no enabling, key changes, paid call or interruption of an active task.
    service.budget.settings = replace(service.budget.settings,**values)
    if service.settings.timeout != values['timeout']:
        service.settings = replace(service.settings,timeout=values['timeout'])
        if service.client:
            from .news_agent_client import NewsAgentClient
            service.client = NewsAgentClient(service.settings.app_id,service.settings.key,service.settings.workspace,
                                              service.settings.region,values['timeout'],has_thoughts=True)
    usage = service.budget.daily_usage()
    usage.update(enabled=not service.problem,application_id=service.settings.app_id,workspace=service.settings.workspace,region=service.settings.region)
    with store.connection(write=True) as db:
        if state(db)['desired'] == current['desired']:
            db.execute('UPDATE news_limits_state SET loaded=?,heartbeat=?,error=NULL,usage=? WHERE id=1',
                       (current['desired'],time.time(),json.dumps(usage)))
