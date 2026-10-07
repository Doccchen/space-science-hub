"""Encrypted configuration, runtime ACKs and budget-sharing tests; no live calls."""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import ai, ai_config as config, ai_runtime, admin_auth, management_store as store, news, resources
from backend.admin_app import app as admin_app
from backend.bailian import AIError, Answer

ORIGIN = 'http://127.0.0.1:18080'
SECRET = 'sk-FAKE_SECRET_123456789'


class FakeClient:
    def __init__(self): self.calls = []; self.error = None
    async def ask(self, messages, request_id):
        self.calls.append(messages)
        if self.error: raise self.error
        return Answer('测试正文',[{'name':'自有测试资料','positions':[0]}],{'total_tokens':42},'fake-provider-id',True)


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.old_news = news.DB_PATH
        news.DB_PATH = self.root / 'news.sqlite3'
        self.keyfile = self.root / 'master.key'; config.generate_key(self.keyfile)
        self.env = patch.dict(os.environ, {'MANAGEMENT_DB_PATH':str(self.root/'management.sqlite3'),
            'AI_MASTER_KEY_FILE':str(self.keyfile), 'AI_DB_PATH':str(self.root/'ai.sqlite3'),
            'ADMIN_ORIGIN':ORIGIN, 'AI_ENABLED':'1', 'DASHSCOPE_API_KEY':SECRET,
            'BAILIAN_WORKSPACE_ID':'llm-test', 'BAILIAN_AGENT_ID':'aid-test', 'AI_CONFIG_VERSION':'1',
            'COLLECT_ENABLED':'0', 'REVIEW_WORKER_ENABLED':'0'})
        self.env.start()
        self.network = patch('backend.bailian.BailianClient.ask', side_effect=AssertionError('live network forbidden'))
        self.network.start()
        news.initialize(); admin_auth.initialize_user('admin','ai-management-password')
        self.baseline = ai.Settings.environment(); config.initialize(self.baseline)
        self.provider = FakeClient(); self.service = ai.AIService(self.baseline,self.provider)
        self.runtime = ai_runtime.Runtime(self.service); self.sync()
        self.admin = TestClient(admin_app,base_url=ORIGIN); self.admin.__enter__()
        public = FastAPI(); public.include_router(ai.router); public.state.ai = self.service
        self.public = TestClient(public)
        result = self.admin.post('/api/login',json={'username':'admin','password':'ai-management-password'},headers={'Origin':ORIGIN})
        self.headers = {'Origin':ORIGIN,'X-CSRF-Token':result.json()['csrf']}

    def tearDown(self):
        self.public.close(); self.admin.__exit__(None,None,None)
        self.network.stop(); self.env.stop(); news.DB_PATH = self.old_news; self.temp.cleanup()

    def sync(self):
        self.runtime.sync(); self.service.client = self.provider

    def view(self):
        response = self.admin.get('/api/ai-config')
        self.assertEqual(response.status_code,200,response.text)
        self.assertNotIn(SECRET,response.text)
        return response.json()

    def save(self, changes=None, new_key=''):
        data = self.view()
        return self.admin.post('/api/ai-config/drafts',json={'revision':data['revision'],
            'config':{**data['draft']['config'], **(changes or {})}, 'new_key':new_key},headers=self.headers)

    def apply(self, invalidate=False):
        data = self.view()
        return self.admin.post('/api/ai-config/apply',json={'revision':data['revision'],'version':data['draft']['version'],
            'invalidate_sessions':invalidate},headers=self.headers)

    def session(self):
        return self.public.post('/api/ai/conversations').json()['conversation_id']

    def ask(self, identity):
        return self.public.post('/api/ai/ask',json={'conversation_id':identity,'request_id':str(uuid.uuid4()),'question':'测试问题'})

    def queue(self):
        return self.admin.post('/api/ai-config/test',json={'version':self.view()['draft']['version'],'fee_confirmed':True},headers=self.headers)

    def run_job(self):
        async def run():
            self.runtime.dispatch_test()
            await asyncio.gather(*self.runtime.tasks)
        with patch('backend.ai.BailianClient',return_value=self.provider):
            asyncio.run(run())

    def test_private_auth_csrf_and_no_secret_in_public_reads_or_database(self):
        other = TestClient(admin_app,base_url=ORIGIN)
        try: self.assertEqual(other.get('/api/ai-config').status_code,401)
        finally: other.close()
        self.assertEqual(self.admin.post('/api/ai-config/apply',json={},headers={'Origin':ORIGIN}).status_code,403)
        self.assertEqual(self.admin.post('/api/ai-config/apply',json={},headers={**self.headers,'Origin':'https://evil.test'}).status_code,403)
        self.assertEqual(self.public.get('/api/ai-config').status_code,404)
        self.assertNotIn(SECRET,self.public.get('/api/ai/status').text)
        data = self.view(); self.assertTrue(data['draft']['key_configured'])
        with store.connection() as db:
            row = config.version(db,1)
            self.assertNotIn(SECRET, json.dumps(row))
            self.assertEqual(config.load(row,self.baseline,'1').key,SECRET)

    def test_draft_has_no_runtime_effect_and_blank_key_preserves_ciphertext(self):
        with store.connection() as db: old = config.version(db,1)['encrypted_key']
        saved = self.save({'agent':'aid-next'})
        self.assertEqual(saved.status_code,200)
        self.sync(); self.assertEqual(self.service.settings.agent,'aid-test')
        with store.connection() as db:
            self.assertEqual(config.version(db,2)['encrypted_key'],old)
        self.assertEqual(len(self.provider.calls),0)

    def test_replaced_key_and_bad_input_never_echo_and_stale_revision_conflicts(self):
        replacement = 'sk-REPLACED_SECRET_12345'
        self.assertEqual(self.save(new_key=replacement).status_code,200)
        self.assertNotIn(replacement,json.dumps(self.view()))
        data = self.view()
        stale = self.admin.post('/api/ai-config/drafts',json={'revision':1,'config':data['draft']['config'],'new_key':''},headers=self.headers)
        self.assertEqual(stale.status_code,409)
        for changes in ({'timeout':121},{'concurrency':5},{'token_daily':1},{'enabled':'false'}, {'workspace':'evil.test/path'}):
            response = self.save(changes)
            self.assertEqual(response.status_code,400,response.text)
            self.assertNotIn(replacement,response.text)
        response = self.save(new_key=SECRET+'\nINJECTED')
        self.assertEqual(response.status_code,400)
        self.assertNotIn(SECRET,response.text)
        self.assertEqual(self.apply().status_code,200); self.sync()
        self.assertEqual(self.service.settings.key,replacement)

    def test_quota_only_apply_preserves_sessions_and_used_budget(self):
        identity = self.session(); self.assertEqual(self.ask(identity).status_code,200)
        self.assertEqual(self.save({'visitor_daily':1,'timeout':30}).status_code,200)
        self.assertEqual(self.apply().status_code,200)
        self.assertEqual(self.view()['status'],'pending')
        self.sync()
        self.assertEqual(self.service.settings.version,'1')
        self.assertEqual(self.ask(identity).json()['error']['code'],'daily_limit')
        self.assertEqual(self.service.daily_usage()['tokens_accounted'],42)
        self.assertEqual(self.view()['status'],'applied')

    def test_disable_restart_and_reenable_never_fall_back_to_enabled_environment(self):
        identity = self.session(); self.ask(identity)
        self.save({'enabled':False}); self.apply(); self.sync()
        self.assertFalse(self.public.get('/api/ai/status').json()['enabled'])
        fresh = ai_runtime.startup()
        self.assertEqual(fresh.service.problem,'disabled')
        self.assertEqual(fresh.service.daily_usage()['requests'],1)
        self.save({'enabled':True}); self.apply(); self.sync()
        self.assertEqual(self.ask(identity).json()['error']['code'],'session_expired')
        self.assertEqual(self.service.daily_usage()['requests'],1)

    def test_force_invalidate_same_version_waits_for_compatibility_ack(self):
        identity = self.session(); previous = self.service.settings.version
        self.assertEqual(self.apply(True).status_code,200)
        self.assertEqual(self.view()['status'],'pending')
        self.sync()
        self.assertNotEqual(self.service.settings.version,previous)
        self.assertEqual(self.ask(identity).json()['error']['code'],'session_expired')
        self.assertEqual(self.view()['status'],'applied')

    def test_wrong_or_missing_master_rejects_apply_and_keeps_running_version(self):
        self.save({'agent':'aid-next'}); self.apply()
        original = self.keyfile.read_bytes(); self.keyfile.write_bytes(Fernet.generate_key())
        self.runtime.sync()
        self.assertEqual(self.service.settings.agent,'aid-test')
        self.assertEqual(self.view()['status'],'failed')
        self.assertEqual(self.apply().status_code,503)
        self.keyfile.write_bytes(original); self.sync()
        self.assertEqual(self.service.settings.agent,'aid-next')
        self.keyfile.unlink()
        self.runtime.sync()
        self.assertEqual(self.view()['status'],'failed')
        self.assertEqual(self.save(new_key='sk-NEW_SECRET_12345').status_code,503)
        self.assertEqual(self.service.settings.agent,'aid-next')

    def test_restore_creates_new_version_and_never_resets_usage(self):
        identity = self.session(); self.ask(identity)
        self.save({'agent':'aid-next'}); self.apply(); self.sync()
        data = self.view(); self.assertTrue(data['can_restore'])
        result = self.admin.post('/api/ai-config/restore',json={'revision':data['revision']},headers=self.headers)
        self.assertEqual(result.status_code,200)
        self.assertGreater(result.json()['version'],2)
        self.sync(); self.assertEqual(self.service.settings.agent,'aid-test')
        self.assertEqual(self.service.daily_usage()['requests'],1)
        self.assertEqual(self.ask(identity).json()['error']['code'],'session_expired')

    def test_paid_test_requires_confirmation_and_shares_site_budget(self):
        response = self.admin.post('/api/ai-config/test',json={'version':1,'fee_confirmed':False},headers=self.headers)
        self.assertEqual(response.status_code,400)
        self.assertEqual(len(self.provider.calls),0)
        self.service.settings.site_daily = 1
        self.assertEqual(self.queue().status_code,202)
        self.assertEqual(len(self.provider.calls),0)
        self.run_job()
        self.assertEqual(self.view()['tests'][0]['state'],'done')
        self.assertEqual(self.service.daily_usage()['tokens_accounted'],42)
        self.assertEqual(self.ask(self.session()).json()['error']['code'],'daily_limit')
        self.assertEqual(len(self.provider.calls),1)

    def test_test_cannot_raise_live_budget_or_concurrency_using_draft(self):
        self.service.settings.site_daily = 1
        self.ask(self.session())
        self.save({'site_daily':100000})
        self.queue(); self.run_job()
        self.assertEqual(self.view()['tests'][0]['result']['error'],'daily_limit')
        self.assertEqual(len(self.provider.calls),1)
        with store.connection(write=True) as db: db.execute('DELETE FROM ai_test_jobs')
        self.service.active = self.service.settings.concurrency
        self.queue(); self.run_job()
        self.assertEqual(self.view()['tests'][0]['result']['error'],'capacity')
        self.assertEqual(self.service.active,self.service.settings.concurrency)
        self.service.active = 0

    def test_failed_test_keeps_reservation_no_retry_or_auto_apply(self):
        self.save({'agent':'aid-not-applied'})
        self.provider.error = AIError('upstream_auth')
        self.queue(); self.run_job(); self.run_job()
        self.assertEqual(len(self.provider.calls),1)
        self.assertEqual(self.view()['tests'][0]['result']['error'],'upstream_auth')
        self.assertEqual(self.service.settings.agent,'aid-test')
        self.assertEqual(self.service.daily_usage()['tokens_accounted'],20000)

    def test_tests_rate_limit_offline_heartbeat_and_restart_cancel(self):
        with store.connection(write=True) as db: db.execute('UPDATE ai_config_state SET heartbeat=?',(time.time()-10,))
        self.assertEqual(self.queue().status_code,503)
        self.sync(); self.queue()
        self.assertEqual(self.queue().status_code,429)
        ai_runtime.startup()
        self.assertEqual(self.view()['tests'][0]['result']['error'],'interrupted')
        self.assertEqual(len(self.provider.calls),0)
        with store.connection(write=True) as db:
            db.executemany('INSERT INTO ai_test_jobs VALUES(?,?,?,?,?,NULL)',[(uuid.uuid4().hex,1,'admin',time.time(),'done') for _ in range(2)])
        self.assertEqual(self.queue().status_code,429)

    def test_repeat_init_and_private_cli_export_do_not_overwrite_or_print_key(self):
        self.save({'timeout':10}); self.apply(); self.sync()
        result = config.initialize(replace(self.baseline,agent='aid-other'))
        self.assertFalse(result['imported'])
        self.assertEqual(self.view()['draft']['config']['timeout'],10)
        destination = self.root/'legacy.env'
        command = [sys.executable,str(resources.ROOT/'tools/ai_manage.py'),'export-env','--output',str(destination)]
        result = subprocess.run(command,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn(SECRET,result.stdout+result.stderr)
        self.assertIn('DASHSCOPE_API_KEY='+SECRET,destination.read_text())
        self.assertNotEqual(subprocess.run(command,capture_output=True).returncode,0)

    def test_missing_active_database_disables_ai_instead_of_environment_fallback(self):
        store.path().rename(store.path().with_suffix('.saved'))
        fresh = ai_runtime.startup()
        self.assertEqual(fresh.service.problem,'configuration')
        self.assertEqual(self.admin.get('/api/ai-config').status_code,503)


class InFlight(unittest.IsolatedAsyncioTestCase):
    async def test_inflight_completes_with_old_snapshot_and_capacity_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            start, finish = asyncio.Event(), asyncio.Event()
            class Delayed(FakeClient):
                async def ask(self,*args):
                    start.set(); await finish.wait(); return await super().ask(*args)
            first = Delayed(); second = FakeClient()
            settings = ai.Settings(enabled=True,key=SECRET,db=Path(directory)/'ai.sqlite3',concurrency=1)
            service = ai.AIService(settings,first)
            identity = service.create('owner')
            task = asyncio.create_task(service.ask(identity,'owner','ip',str(uuid.uuid4()),'question'))
            await start.wait()
            service.apply_settings(replace(settings,key='sk-NEXT_SECRET',version='2'),second)
            self.assertEqual(service.active,1)
            new = service.create('another')
            with self.assertRaises(AIError) as caught:
                await service.ask(new,'another','ip',str(uuid.uuid4()),'question')
            self.assertEqual(caught.exception.code,'capacity')
            service.apply_settings(replace(service.settings,enabled=False,version='3'),second)
            finish.set(); result = await task
            self.assertEqual(result['status'],'answered')
            self.assertEqual(service.active,0)
            self.assertEqual(len(first.calls),1); self.assertEqual(len(second.calls),0)
            with service.connection() as db:
                self.assertEqual(db.execute('SELECT status FROM requests').fetchone()[0],'complete')

    async def test_first_disabled_start_can_enable_without_recovering_live_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = ai.Settings(enabled=False,key=SECRET,db=Path(directory)/'ai.sqlite3')
            service = ai.AIService(settings)
            self.assertFalse(service.initialized)
            service.apply_settings(replace(settings,enabled=True),FakeClient())
            identity = service.create('owner')
            service.reserve(identity,'owner','ip',str(uuid.uuid4()),'pending')
            service.active = 1
            service.apply_settings(replace(service.settings,timeout=10),FakeClient())
            with service.connection() as db:
                self.assertEqual(db.execute('SELECT status FROM requests').fetchone()[0],'pending')
            self.assertEqual(service.active,1)


if __name__ == '__main__': unittest.main()
