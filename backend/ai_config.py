"""Encrypted immutable AI drafts and explicit target versions in the shared store."""
import json
import os
import re
import sqlite3
import time
import uuid
from dataclasses import replace
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from . import management_store as store, news

FIELDS = ('enabled', 'workspace', 'agent', 'timeout', 'concurrency', 'visitor_daily', 'ip_daily',
          'site_daily', 'token_daily', 'token_reservation')
LIMITS = {'timeout':120, 'concurrency':4, 'visitor_daily':10000000, 'ip_daily':10000000,
          'site_daily':10000000, 'token_daily':10000000, 'token_reservation':10000000}


def cipher():
    try:
        return Fernet(Path(os.environ.get('AI_MASTER_KEY_FILE', '/run/secrets/site-management.key')).read_bytes().strip())
    except (OSError, ValueError, TypeError):
        raise store.ManagementError('解密主密钥不可用，请检查独立密钥文件与挂载权限。', 503) from None


def generate_key(target):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as handle:
        handle.write(Fernet.generate_key() + b'\n')


def validate(values, has_key):
    if not isinstance(values, dict) or set(values) != set(FIELDS) or type(values['enabled']) is not bool:
        raise store.ManagementError('AI 配置字段无效。', 400)
    if (not isinstance(values['workspace'], str) or not re.fullmatch(r'[A-Za-z0-9-]{1,100}', values['workspace'])
            or not isinstance(values['agent'], str) or not re.fullmatch(r'aid-[A-Za-z0-9-]{1,100}', values['agent'])):
        raise store.ManagementError('业务空间或知识问答服务 ID 格式无效。', 400)
    for field, maximum in LIMITS.items():
        if type(values[field]) is not int or not 1 <= values[field] <= maximum:
            raise store.ManagementError('AI 数值配置超出允许范围。', 400)
    if values['token_reservation'] > values['token_daily']:
        raise store.ManagementError('每次 Token 预留量不能超过每日预算。', 400)
    if values['enabled'] and not has_key:
        raise store.ManagementError('启用 AI 前请配置 API Key。', 400)
    return values


def tables_exist():
    if not store.path().exists():
        if ai_marker().exists():
            raise store.ManagementError('已启用的 AI 管理库丢失，请恢复备份。', 503)
        return False
    with store.connection() as db:
        exists = bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='ai_config_state'").fetchone())
    if ai_marker().exists() and not exists:
        raise store.ManagementError('AI 管理表丢失，请恢复备份。', 503)
    return exists


def ai_marker():
    return store.path().with_suffix('.ai-enabled')


def required():
    if not tables_exist():
        raise store.ManagementError('请先在服务器显式初始化 AI 后台配置。', 503)


def state(db):
    row = db.execute('SELECT * FROM ai_config_state WHERE id=1').fetchone()
    if row is None:
        raise store.ManagementError('AI 配置状态不可用。', 503)
    return dict(row)


def version(db, identity):
    if type(identity) is not int or identity < 1:
        raise store.ManagementError('配置版本无效。', 400)
    row = db.execute('SELECT * FROM ai_config_versions WHERE id=?', (identity,)).fetchone()
    if row is None:
        raise store.ManagementError('配置版本不存在。', 404)
    return dict(row)


def public(row):
    try:
        values = json.loads(row['config'])
        validate(values, bool(row['encrypted_key']))
    except (ValueError, TypeError, KeyError):
        raise store.ManagementError('配置版本内容无效。', 503) from None
    return {'version':row['id'], 'config':values, 'key_configured':bool(row['encrypted_key']),
            'created_at':row['created_at'], 'actor':row['actor']}


def load(row, baseline, compatibility):
    values = public(row)['config']
    encryption = cipher()
    key = ''
    if row['encrypted_key']:
        try:
            key = encryption.decrypt(row['encrypted_key'].encode()).decode()
        except (InvalidToken, UnicodeError, ValueError):
            raise store.ManagementError('配置密钥解密失败，已保留原运行配置。', 503) from None
    return replace(baseline, **values, key=key, version=compatibility)


def audit(db, actor, operation, identity):
    db.execute('INSERT INTO management_audit(resource_id,revision,actor,operation,created_at,summary) VALUES(NULL,?,?,?,?,?)',
               (identity, actor, operation, news.now(), json.dumps({'config_version':identity})))


def insert(db, values, encrypted, actor):
    return db.execute('INSERT INTO ai_config_versions(config,encrypted_key,actor,created_at) VALUES(?,?,?,?)',
                      (json.dumps(values), encrypted, actor, news.now())).lastrowid


def initialize(settings):
    # Explicit server-only import; never invoked by admin startup or a public request.
    values = {name:getattr(settings, name) for name in FIELDS}
    validate(values, bool(settings.key))
    encryption = cipher()
    encrypted = encryption.encrypt(settings.key.encode()).decode() if settings.key else None
    store.initialize()
    with store.connection(write=True) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS ai_config_versions(id INTEGER PRIMARY KEY,
          config TEXT NOT NULL, encrypted_key TEXT, actor TEXT NOT NULL, created_at TEXT NOT NULL)''')
        db.execute('''CREATE TABLE IF NOT EXISTS ai_config_state(id INTEGER PRIMARY KEY CHECK(id=1),
          revision INTEGER NOT NULL, latest_version INTEGER NOT NULL, desired_version INTEGER NOT NULL,
          desired_compat TEXT NOT NULL, loaded_version INTEGER, loaded_compat TEXT, last_good_version INTEGER,
          last_good_compat TEXT, previous_version INTEGER, heartbeat REAL, runtime_id TEXT,
          error TEXT, attempted_version INTEGER, usage TEXT, upstream_error TEXT)''')
        db.execute('''CREATE TABLE IF NOT EXISTS ai_test_jobs(id TEXT PRIMARY KEY, version INTEGER NOT NULL,
          actor TEXT NOT NULL, created REAL NOT NULL, state TEXT NOT NULL, result TEXT,
          FOREIGN KEY(version) REFERENCES ai_config_versions(id))''')
        existing = db.execute('SELECT 1 FROM ai_config_state WHERE id=1').fetchone()
        if not existing:
            identity = insert(db, values, encrypted, 'server-initialization')
            db.execute('INSERT INTO ai_config_state(id,revision,latest_version,desired_version,desired_compat) VALUES(1,1,?,?,?)',
                       (identity, identity, settings.version))
            audit(db, 'server-initialization', 'ai_initialize', identity)
    ai_marker().write_text('AI database config is authoritative\n', encoding='utf-8')
    return {'initialized':True, 'imported':not bool(existing)}


def check_revision(body, current):
    if type(body.get('revision')) is not int or body['revision'] != current['revision']:
        raise store.ManagementError('配置已被修改，请重新加载后核对。')


def save_draft(body, actor):
    required()
    if set(body) != {'revision', 'config', 'new_key'}:
        raise store.ManagementError('草稿格式无效。', 400)
    new_key = body['new_key']
    if not isinstance(new_key, str) or (new_key and not re.fullmatch(r'[A-Za-z0-9._-]{8,256}', new_key)):
        raise store.ManagementError('API Key 格式无效；未保存。', 400)
    with store.connection(write=True) as db:
        current = state(db); check_revision(body, current)
        previous = version(db, current['latest_version'])
        encrypted = cipher().encrypt(new_key.encode()).decode() if new_key else previous['encrypted_key']
        values = validate(body['config'], bool(encrypted))
        identity = insert(db, values, encrypted, actor)
        db.execute('UPDATE ai_config_state SET latest_version=?,revision=revision+1 WHERE id=1', (identity,))
        audit(db, actor, 'ai_draft', identity)
    return {'version':identity, 'revision':current['revision']+1}


def apply(body, actor, baseline, restore=False):
    required()
    allowed = {'revision'} if restore else {'revision', 'version', 'invalidate_sessions'}
    if set(body) != allowed or (not restore and type(body['invalidate_sessions']) is not bool):
        raise store.ManagementError('应用配置格式无效。', 400)
    with store.connection(write=True) as db:
        current = state(db); check_revision(body, current)
        identity = current['previous_version'] if restore else body['version']
        if identity is None:
            raise store.ManagementError('尚无可恢复的上一生效版本。')
        candidate = version(db, identity)
        incoming = load(candidate, baseline, current['desired_compat'])
        previous = load(version(db, current['desired_version']), baseline, current['desired_compat'])
        changed = any(getattr(incoming, field) != getattr(previous, field) for field in ('enabled','key','workspace','agent'))
        compatibility = uuid.uuid4().hex if changed or body.get('invalidate_sessions') or restore else current['desired_compat']
        if restore:
            identity = insert(db, public(candidate)['config'], candidate['encrypted_key'], actor)
        db.execute('UPDATE ai_config_state SET desired_version=?,desired_compat=?,revision=revision+1,error=NULL WHERE id=1',
                   (identity, compatibility))
        if restore:
            db.execute('UPDATE ai_config_state SET latest_version=? WHERE id=1', (identity,))
        audit(db, actor, 'ai_restore' if restore else 'ai_apply', identity)
    return {'version':identity, 'revision':current['revision']+1}


def queue_test(body, actor):
    required()
    if set(body) != {'version', 'fee_confirmed'} or body['fee_confirmed'] is not True:
        raise store.ManagementError('请明确确认实际测试会调用百炼并可能产生费用。', 400)
    now = time.time()
    with store.connection(write=True) as db:
        candidate = version(db, body['version'])
        current = state(db)
        if not current['heartbeat'] or now - current['heartbeat'] > 5:
            raise store.ManagementError('公开服务离线或心跳过期，无法执行测试。', 503)
        if not candidate['encrypted_key']:
            raise store.ManagementError('测试前请配置 API Key。', 400)
        if (db.execute("SELECT 1 FROM ai_test_jobs WHERE state IN ('queued','running')").fetchone()
                or db.execute('SELECT COUNT(*) FROM ai_test_jobs WHERE created>?', (now-3600,)).fetchone()[0] >= 3
                or db.execute('SELECT COUNT(*) FROM ai_test_jobs WHERE created>?', (now-86400,)).fetchone()[0] >= 10):
            raise store.ManagementError('测试次数已达限制或已有测试正在执行。', 429)
        identity = uuid.uuid4().hex
        db.execute('INSERT INTO ai_test_jobs VALUES(?,?,?,?,?,NULL)', (identity, candidate['id'], actor, now, 'queued'))
        audit(db, actor, 'ai_test_queued', candidate['id'])
    return {'job_id':identity, 'state':'queued'}


def overview():
    required()
    with store.connection() as db:
        current = state(db)
        latest = public(version(db, current['latest_version']))
        desired = public(version(db, current['desired_version']))
        loaded = public(version(db, current['loaded_version'])) if current['loaded_version'] else None
        versions = [public(dict(row)) for row in db.execute('SELECT * FROM ai_config_versions ORDER BY id DESC LIMIT 30')]
        jobs = [dict(row) for row in db.execute('SELECT id,version,created,state,result FROM ai_test_jobs ORDER BY created DESC LIMIT 5')]
    for job in jobs:
        job['result'] = json.loads(job['result']) if job['result'] else None
    live = bool(current['heartbeat'] and time.time() - current['heartbeat'] <= 5)
    status = 'offline' if not live else 'failed' if current['error'] else 'applied' if (current['loaded_version'] == current['desired_version'] and current['loaded_compat'] == current['desired_compat']) else 'pending'
    return {'revision':current['revision'], 'draft':latest, 'desired':desired, 'loaded':loaded,
            'status':status, 'heartbeat':current['heartbeat'], 'error':current['error'],
            'usage':json.loads(current['usage']) if current['usage'] else None, 'upstream_error':current['upstream_error'],
            'can_restore':bool(current['previous_version']), 'versions':versions, 'tests':jobs}
