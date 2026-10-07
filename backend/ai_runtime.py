"""Single-worker config synchronization and explicitly queued provider tests."""
import asyncio
import json
import sqlite3
import time
import uuid

from . import ai, ai_config as config, management_store as store
from .bailian import AIError


class Runtime:
    def __init__(self, service):
        self.service = service
        self.identity = uuid.uuid4().hex
        self.loaded = None
        self.compatibility = None
        self.tasks = set()
        self.started = False
        self.error = None

    def sync(self):
        if not config.tables_exist():
            return
        with store.connection() as db:
            state = config.state(db)
            desired = config.version(db, state['desired_version'])
            fallback = config.version(db, state['last_good_version']) if state['last_good_version'] else None
        if not self.started:
            # A restarted process never automatically repeats a requested paid test.
            with store.connection(write=True) as db:
                db.execute("UPDATE ai_test_jobs SET state='failed',result=? WHERE state IN ('queued','running')",
                           (json.dumps({'error':'interrupted','finished_at':time.time()}),))
            self.started = True
        error = None
        try:
            settings = config.load(desired, self.service.settings, state['desired_compat'])
            if self.loaded != desired['id'] or self.compatibility != state['desired_compat']:
                self.service.apply_settings(settings)
                self.loaded = desired['id']
                self.compatibility = state['desired_compat']
        except (store.ManagementError, AIError, sqlite3.Error, OSError):
            error = '目标配置加载失败；请检查主密钥、配置或数据库，运行配置已保留。'
            if self.loaded is None:
                if fallback:
                    try:
                        self.service.apply_settings(config.load(fallback,self.service.settings,state['last_good_compat']))
                        self.loaded = fallback['id']
                        self.compatibility = state['last_good_compat']
                    except (store.ManagementError,AIError,sqlite3.Error,OSError):
                        self.service.problem = 'configuration'
                else:
                    self.service.problem = 'configuration'
        self.error = error
        usage = None
        try:
            self.service.ensure_storage()
            usage = self.service.daily_usage()
        except (sqlite3.Error,OSError):
            error = 'AI 用量库暂不可用；请检查数据库和权限。'
        with store.connection(write=True) as db:
            # Do not acknowledge a target changed while loading/decrypting.
            actual = config.state(db)
            if actual['desired_version'] != state['desired_version'] or actual['desired_compat'] != state['desired_compat']:
                return
            if not error and self.loaded == state['desired_version']:
                if actual['last_good_version'] != self.loaded:
                    db.execute('UPDATE ai_config_state SET previous_version=last_good_version,last_good_version=?,last_good_compat=? WHERE id=1',
                               (self.loaded, state['desired_compat']))
                else:
                    db.execute('UPDATE ai_config_state SET last_good_compat=? WHERE id=1', (self.compatibility,))
            db.execute('UPDATE ai_config_state SET loaded_version=?,loaded_compat=?,heartbeat=?,runtime_id=?,error=?,attempted_version=?,usage=?,upstream_error=? WHERE id=1',
                       (self.loaded,self.compatibility,time.time(),self.identity,error,state['desired_version'],json.dumps(usage),self.service.last_upstream_error))

    async def run_test(self, job):
        try:
            with store.connection() as db:
                row = config.version(db, job['version'])
            candidate = config.load(row,self.service.settings,'admin-test')
            result = await self.service.test_configuration(candidate)
            status = 'done'
        except (AIError, store.ManagementError, sqlite3.Error, OSError) as error:
            result = {'error':error.code if isinstance(error,AIError) else 'configuration'}
            status = 'failed'
        except Exception:
            result, status = {'error':'incomplete_answer'}, 'failed'
        result['finished_at'] = time.time()
        with store.connection(write=True) as db:
            db.execute('UPDATE ai_test_jobs SET state=?,result=? WHERE id=?', (status,json.dumps(result),job['id']))
            config.audit(db,job['actor'],'ai_test_' + status,job['version'])

    def dispatch_test(self):
        if self.tasks or not config.tables_exist():
            return
        with store.connection(write=True) as db:
            job = db.execute("SELECT * FROM ai_test_jobs WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
            if not job:
                return
            job = dict(job)
            if time.time() - job['created'] > 300:
                db.execute("UPDATE ai_test_jobs SET state='failed',result=? WHERE id=?", (json.dumps({'error':'expired'}),job['id']))
                return
            db.execute("UPDATE ai_test_jobs SET state='running' WHERE id=?", (job['id'],))
        task = asyncio.create_task(self.run_test(job))
        self.tasks.add(task)
        task.add_done_callback(self.completed)

    def completed(self, task):
        self.tasks.discard(task)
        try:
            task.result()
        except (Exception, asyncio.CancelledError):
            pass  # A failed result write is diagnosed via state/heartbeat; never retry the paid call.

    async def loop(self):
        while True:
            try:
                self.sync()
                self.dispatch_test()
            except (store.ManagementError,sqlite3.Error,OSError):
                pass  # Stale heartbeat exposes unavailable management storage without stopping news.
            await asyncio.sleep(1)

    async def close(self):
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)


def startup():
    service = ai.service_from_env()
    runtime = Runtime(service)
    try:
        runtime.sync()
    except (store.ManagementError,sqlite3.Error,OSError):
        if config.ai_marker().exists():
            service.problem = 'configuration'
    try:
        service.ensure_storage()
    except (sqlite3.Error,OSError):
        service.problem = 'storage'
    return runtime
