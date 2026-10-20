"""Encrypted, versioned literature-provider settings in the existing private store."""
import json
import time
from datetime import datetime, timedelta, timezone

from cryptography.fernet import InvalidToken

from . import ai_config, management_store as store, news

PROVIDERS = {'wanfang':'万方', 'sciencedirect':'ScienceDirect'}
DEFAULT = {'enabled':False, 'timeout':18, 'daily_limit':100, 'authorized':False}


class ProviderLimit(ValueError):
    pass


def marker():
    return store.path().with_suffix('.literature-enabled')


def available():
    if not store.path().exists():
        if marker().exists():
            raise store.ManagementError('文献 API 管理库丢失，请恢复备份。',503)
        return False
    with store.connection() as db:
        exists = bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='literature_state'").fetchone())
    if marker().exists() and not exists:
        raise store.ManagementError('文献 API 配置表不可用。',503)
    return exists


def initialize(actor='server-initialization'):
    ai_config.cipher()  # Fail before writing if the shared master key is unavailable.
    if marker().exists() and not store.path().exists():
        raise store.ManagementError('不能覆盖丢失的文献 API 管理库。',503)
    store.initialize()
    with store.connection(write=True) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS literature_versions(id INTEGER PRIMARY KEY,
          provider TEXT NOT NULL, config TEXT NOT NULL, encrypted_secrets TEXT NOT NULL,
          actor TEXT NOT NULL, created_at TEXT NOT NULL)''')
        db.execute('''CREATE TABLE IF NOT EXISTS literature_state(provider TEXT PRIMARY KEY,
          revision INTEGER NOT NULL, draft INTEGER NOT NULL, applied INTEGER NOT NULL,
          previous INTEGER, loaded INTEGER, heartbeat REAL, error TEXT)''')
        db.execute('''CREATE TABLE IF NOT EXISTS literature_calls(id INTEGER PRIMARY KEY,
          provider TEXT NOT NULL, version INTEGER NOT NULL, created REAL NOT NULL,
          day TEXT NOT NULL, kind TEXT NOT NULL, actor TEXT NOT NULL, state TEXT NOT NULL,
          result TEXT)''')
        db.execute('CREATE INDEX IF NOT EXISTS literature_calls_day ON literature_calls(provider,day)')
        for provider in PROVIDERS:
            if db.execute('SELECT 1 FROM literature_state WHERE provider=?',(provider,)).fetchone():
                continue
            identity = insert(db,provider,DEFAULT,{'key':'','insttoken':''},actor)
            db.execute('INSERT INTO literature_state(provider,revision,draft,applied) VALUES(?,1,?,?)',
                       (provider,identity,identity))
            audit(db,provider,actor,'initialize',identity)
    marker().write_text('Literature database configuration is authoritative\n',encoding='utf-8')
    return {'initialized':True}


def required(provider):
    if provider not in PROVIDERS:
        raise store.ManagementError('未知文献来源。',404)
    if not available():
        raise store.ManagementError('请先初始化文献 API 管理。',503)


def state(db, provider):
    row=db.execute('SELECT * FROM literature_state WHERE provider=?',(provider,)).fetchone()
    if row is None:
        raise store.ManagementError('文献 API 配置不存在。',503)
    return dict(row)


def version(db,provider,identity):
    row=db.execute('SELECT * FROM literature_versions WHERE provider=? AND id=?',(provider,identity)).fetchone()
    if row is None:
        raise store.ManagementError('配置版本不存在。',404)
    return dict(row)


def decrypt(row):
    try:
        result=json.loads(ai_config.cipher().decrypt(row['encrypted_secrets'].encode()).decode())
        if set(result)!={'key','insttoken'}:
            raise ValueError()
        return result
    except (InvalidToken,ValueError,UnicodeError,TypeError):
        raise store.ManagementError('文献 API 密钥解密失败，请检查主密钥挂载。',503) from None


def public(row):
    return {'version':row['id'],'config':json.loads(row['config']),
            'key_configured':bool(json.loads(row['config']).get('key_configured')),
            'token_configured':bool(json.loads(row['config']).get('token_configured')),
            'created_at':row['created_at'],'actor':row['actor']}


def insert(db,provider,config,secrets,actor):
    value={**{k:config[k] for k in DEFAULT},'key_configured':bool(secrets['key']),
           'token_configured':bool(secrets['insttoken'])}
    encrypted=ai_config.cipher().encrypt(json.dumps(secrets).encode()).decode()
    return db.execute('INSERT INTO literature_versions(provider,config,encrypted_secrets,actor,created_at) VALUES(?,?,?,?,?)',
                      (provider,json.dumps(value),encrypted,actor,news.now())).lastrowid


def audit(db,provider,actor,operation,identity):
    db.execute('INSERT INTO management_audit(resource_id,revision,actor,operation,created_at,summary) VALUES(NULL,?,?,?,?,?)',
               (identity,actor,'literature_'+operation,news.now(),json.dumps({'provider':provider,'version':identity})))


def check_revision(body,current):
    if type(body.get('revision')) is not int or body['revision']!=current['revision']:
        raise store.ManagementError('配置已修改，请重新读取后操作。')


def save(provider,body,actor):
    required(provider)
    if set(body)!={'revision','config','new_key','new_insttoken','clear_key','clear_insttoken'}:
        raise store.ManagementError('配置字段无效。',400)
    config=body['config']
    if (not isinstance(config,dict) or set(config)!=set(DEFAULT)
        or type(config['enabled']) is not bool or type(config['authorized']) is not bool
        or type(config['timeout']) is not int or not 5<=config['timeout']<=60
        or type(config['daily_limit']) is not int or not 1<=config['daily_limit']<=10000):
        raise store.ManagementError('配置或额度范围无效。',400)
    for name in ('new_key','new_insttoken'):
        value=body[name]
        if not isinstance(value,str) or len(value)>4096 or any(ord(c)<33 or ord(c)>126 for c in value):
            raise store.ManagementError('密钥格式无效，未保存。',400)
    if type(body['clear_key']) is not bool or type(body['clear_insttoken']) is not bool:
        raise store.ManagementError('密钥清除选项无效。',400)
    with store.connection(write=True) as db:
        current=state(db,provider);check_revision(body,current)
        secrets=decrypt(version(db,provider,current['draft']))
        for field,new,clear in [('key','new_key','clear_key'),('insttoken','new_insttoken','clear_insttoken')]:
            if body[new] and body[clear]:
                raise store.ManagementError('不能同时替换和清除同一个密钥。',400)
            if body[clear]:secrets[field]=''
            elif body[new]:secrets[field]=body[new]
        if provider=='wanfang':secrets['insttoken']=''
        if config['enabled'] and (not secrets['key'] or not config['authorized']):
            raise store.ManagementError('启用前请配置 Key 并确认拥有本站使用权限。',400)
        identity=insert(db,provider,config,secrets,actor)
        db.execute('UPDATE literature_state SET draft=?,revision=revision+1 WHERE provider=?',(identity,provider))
        audit(db,provider,actor,'draft',identity)
    return {'version':identity}


def apply(provider,body,actor,restore=False):
    required(provider)
    if set(body)!=({'revision'} if restore else {'revision','version'}):
        raise store.ManagementError('应用参数无效。',400)
    with store.connection(write=True) as db:
        current=state(db,provider);check_revision(body,current)
        identity=current['previous'] if restore else body['version']
        if type(identity) is not int:
            raise store.ManagementError('没有可恢复的配置版本。',400)
        row=version(db,provider,identity);decrypt(row)
        config=json.loads(row['config'])
        if config['enabled'] and (not config['key_configured'] or not config['authorized']):
            raise store.ManagementError('此版本尚不具备启用条件。',400)
        db.execute('UPDATE literature_state SET applied=?,previous=?,revision=revision+1,error=NULL WHERE provider=?',
                   (identity,current['applied'],provider))
        audit(db,provider,actor,'restore' if restore else 'apply',identity)
    return {'version':identity,'status':'pending'}


def day():
    return datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d')


def reserve(provider,identity,limit,kind='search',actor='public'):
    required(provider)
    with store.connection(write=True) as db:
        current=state(db,provider)
        if kind=='search' and current['applied']!=identity:
            raise ProviderLimit('文献来源配置已变化，请重新检索。')
        active=json.loads(version(db,provider,current['applied'])['config'])
        if kind=='search' and not active['enabled']:
            raise ProviderLimit('该文献来源已停用。')
        limit=min(limit,active['daily_limit'])
        count=db.execute('SELECT COUNT(*) FROM literature_calls WHERE provider=? AND day=?',(provider,day())).fetchone()[0]
        if count>=limit:raise ProviderLimit('该文献来源今日调用额度已用完。')
        now=time.time()
        if kind=='test':
            hourly=db.execute("SELECT COUNT(*) FROM literature_calls WHERE provider=? AND kind='test' AND created>?",(provider,now-3600)).fetchone()[0]
            daily=db.execute("SELECT COUNT(*) FROM literature_calls WHERE provider=? AND kind='test' AND created>?",(provider,now-86400)).fetchone()[0]
            if hourly>=3 or daily>=10:raise ProviderLimit('连接测试过于频繁，请稍后再试。')
        return db.execute('INSERT INTO literature_calls(provider,version,created,day,kind,actor,state) VALUES(?,?,?,?,?,?,?)',
                          (provider,identity,now,day(),kind,actor,'started')).lastrowid


def finish(identity,result):
    with store.connection(write=True) as db:
        db.execute('UPDATE literature_calls SET state=?,result=? WHERE id=?',
                   ('done' if result.get('ok') else 'failed',json.dumps(result),identity))


def overview():
    if not available():return {'initialized':False,'providers':[]}
    items=[]
    with store.connection() as db:
        for provider,name in PROVIDERS.items():
            current=state(db,provider)
            recent=[dict(r) for r in db.execute("SELECT version,created,state,result FROM literature_calls WHERE provider=? AND kind='test' ORDER BY id DESC LIMIT 5",(provider,))]
            for test in recent:test['result']=json.loads(test['result']) if test['result'] else None
            used=db.execute('SELECT COUNT(*) FROM literature_calls WHERE provider=? AND day=?',(provider,day())).fetchone()[0]
            items.append({'provider':provider,'name':name,'revision':current['revision'],
                'draft':public(version(db,provider,current['draft'])),
                'applied':public(version(db,provider,current['applied'])),
                'loaded_version':current['loaded'],'heartbeat':current['heartbeat'],'error':current['error'],
                'status':'offline' if not current['heartbeat'] or time.time()-current['heartbeat']>10 else 'failed' if current['error'] else 'applied' if current['loaded']==current['applied'] else 'pending',
                'can_restore':bool(current['previous']),'used_today':used,'tests':recent,
                'versions':[public(dict(r)) for r in db.execute('SELECT * FROM literature_versions WHERE provider=? ORDER BY id DESC LIMIT 20',(provider,))]})
    return {'initialized':True,'providers':items}


def runtime_settings():
    if not available():return None
    result={}
    with store.connection() as db:
        for provider in PROVIDERS:
            current=state(db,provider);row=version(db,provider,current['applied'])
            values=json.loads(row['config'])
            secrets=decrypt(row) if values['enabled'] else {'key':'','insttoken':''}
            result[provider]={'version':row['id'],**values,**secrets}
    return result


def acknowledge(settings,error=None):
    if not available():return
    with store.connection(write=True) as db:
        for provider,value in (settings or {}).items():
            db.execute('UPDATE literature_state SET loaded=?,heartbeat=?,error=? WHERE provider=? AND applied=?',
                       (None if error else value['version'],time.time(),error,provider,value['version']))


def acknowledge_failure():
    if not available():return
    with store.connection(write=True) as db:
        db.execute('UPDATE literature_state SET loaded=NULL,heartbeat=?,error=?',
                   (time.time(),'文献 API 配置加载失败，请检查共享数据库与主密钥挂载。'))
