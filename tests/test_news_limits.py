import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import admin_auth,ai,ai_config,news,news_agent,news_limits,management_store
from backend.admin_app import app as admin_app
from backend.bailian import AIError
from backend.news_agent_client import NewsAnswer
from backend.news_context_store import Store
from tools.migrate_news_usage import migrate


class IndependentLimits(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.old_news=news.DB_PATH;news.DB_PATH=self.root/'news.sqlite3'
        self.env=patch.dict(os.environ,{'MANAGEMENT_DB_PATH':str(self.root/'management.sqlite3'),
            'AI_DB_PATH':str(self.root/'ai.sqlite3'),'NEWS_AGENT_USAGE_DB_PATH':str(self.root/'news-usage.sqlite3'),
            'AI_MASTER_KEY_FILE':str(self.root/'master.key'),'ADMIN_ORIGIN':'http://127.0.0.1:18080'})
        self.env.start();news.initialize();ai_config.generate_key(self.root/'master.key')
        self.regular=ai.AIService(ai.Settings(enabled=True,key='fake-test-key',db=self.root/'ai.sqlite3',
            token_daily=20,token_reservation=10,visitor_daily=1,concurrency=1))
        ai_config.initialize(self.regular.settings);news_limits.initialize()
        self.news_budget=news_limits.budget(initialize=True);self.news_budget.ensure_storage()
        self.service=news_agent.NewsAgentService(news_agent.Settings(context_enabled=True),self.news_budget,Store(self.root/'news-agent.sqlite3'))

    def tearDown(self):
        self.env.stop();news.DB_PATH=self.old_news;self.temp.cleanup()

    def configure_news(self):
        before=news_limits.overview();values={**before['draft']['config'],'token_daily':90,'token_reservation':80,'visitor_daily':1,'concurrency':1}
        news_limits.save({'revision':before['revision'],'config':values},'test-admin')
        draft=news_limits.overview()
        news_limits.apply({'revision':draft['revision'],'version':draft['draft']['version']},'test-admin')
        news_limits.sync(self.service)

    def test_counts_tokens_and_capacity_are_independent(self):
        self.configure_news()
        conversation=self.regular.create('same-visitor')
        self.regular.reserve(conversation,'same-visitor','same-ip','request-1','question')
        self.regular.active=1
        ledger=self.news_budget.reserve_news('new-job','same-visitor','same-ip','news question')
        self.news_budget.finish_news(ledger,NewsAnswer('answer','session',[],{'total_tokens':5},'provider'))
        self.assertEqual(self.regular.daily_usage()['tokens_accounted'],10)
        self.assertEqual(self.news_budget.daily_usage()['tokens_accounted'],5)
        with self.assertRaises(AIError):self.news_budget.reserve_news('job-2','same-visitor','same-ip','another')
        self.assertEqual(self.regular.daily_usage()['requests'],1)
        self.assertEqual(self.service.problem,'disabled')
        self.assertFalse(self.service.settings.enabled)

    def test_general_config_change_does_not_change_news_limits(self):
        self.configure_news();before=news_limits.overview()
        ordinary=ai_config.overview();values={**ordinary['draft']['config'],'token_daily':200,'concurrency':4}
        ai_config.save_draft({'revision':ordinary['revision'],'config':values,'new_key':''},'test-admin')
        ordinary=ai_config.overview()
        ai_config.apply({'revision':ordinary['revision'],'version':ordinary['draft']['version'],'invalidate_sessions':False},'test-admin',self.regular.settings)
        news_limits.sync(self.service)
        self.assertEqual(news_limits.overview()['desired'],before['desired'])
        self.assertEqual(self.news_budget.settings.token_daily,90)
        self.assertEqual(self.news_budget.settings.concurrency,1)

    def test_timeout_update_retains_knowledge_observation_requests(self):
        from backend.news_agent_client import NewsAgentClient
        self.service.client=NewsAgentClient(self.service.settings.app_id,'fake-key')
        self.configure_news()
        self.assertTrue(self.service.client.has_thoughts)
        self.assertEqual(self.service.client.timeout,120)

    def test_migration_rejects_pending_target_without_changing_it(self):
        identity=self.news_budget.reserve_news('active','visitor','ip','question')
        with self.assertRaises(RuntimeError):migrate()
        with self.news_budget.connection() as db:
            self.assertEqual(db.execute('SELECT status FROM requests WHERE id=?',(identity,)).fetchone()[0],'pending')

    def test_missing_migrated_ledger_is_not_silently_recreated(self):
        migrate();news_limits.usage_path().unlink()
        with self.assertRaises(RuntimeError):migrate()
        self.assertFalse(news_limits.usage_path().exists())

    def test_legacy_news_usage_moves_once_without_losing_unknown_reservation(self):
        self.regular.settings=replace(self.regular.settings,token_daily=10000,visitor_daily=20)
        ordinary=self.regular.create('ordinary');ordinary_key,_,_=self.regular.reserve(ordinary,'ordinary','ordinary','ordinary-request','ordinary question')
        self.regular.finish_news(ordinary_key,error='fixture',no_call=True)
        first=self.regular.reserve_news('legacy-complete','news-a','news-a','news')
        self.regular.finish_news(first,NewsAnswer('answer','session',[],{'total_tokens':7},'provider'))
        second=self.regular.reserve_news('legacy-unknown','news-b','news-b','news')
        self.regular.finish_news(second,error='upstream_timeout')
        result=migrate();self.assertEqual(result['migrated_news_requests'],2)
        self.assertEqual(self.regular.daily_usage()['requests'],1)
        self.assertEqual(self.news_budget.daily_usage()['requests'],2)
        self.assertEqual(self.news_budget.daily_usage()['tokens_accounted'],17)
        self.assertTrue(Path(result['backup']).is_dir())
        self.assertEqual(migrate()['migrated_news_requests'],0)

    def test_stale_revision_invalid_values_and_missing_ledger_fail_closed(self):
        before=news_limits.overview()
        with self.assertRaises(management_store.ManagementError):news_limits.save({'revision':0,'config':before['draft']['config']},'admin')
        values={**before['draft']['config'],'token_daily':1,'token_reservation':2}
        with self.assertRaises(management_store.ManagementError):news_limits.save({'revision':before['revision'],'config':values},'admin')
        self.assertEqual(news_limits.overview()['revision'],before['revision'])
        news_limits.usage_path().unlink()
        with self.assertRaises(management_store.ManagementError):news_limits.budget()
        self.assertFalse(news_limits.usage_path().exists())

    def test_admin_endpoint_requires_auth_and_csrf(self):
        admin_auth.initialize_user('admin','independent-limits-test-password')
        origin='http://127.0.0.1:18080'
        with TestClient(admin_app,base_url=origin) as client:
            self.assertEqual(client.get('/api/news-agent-limits').status_code,401)
            login=client.post('/api/login',json={'username':'admin','password':'independent-limits-test-password'},headers={'Origin':origin})
            view=client.get('/api/news-agent-limits').json()
            body={'revision':view['revision'],'config':view['draft']['config']}
            self.assertEqual(client.post('/api/news-agent-limits/drafts',json=body,headers={'Origin':origin}).status_code,403)
            headers={'Origin':origin,'X-CSRF-Token':login.json()['csrf']}
            self.assertEqual(client.post('/api/news-agent-limits/drafts',json=body,headers=headers).status_code,200)


if __name__=='__main__':unittest.main()
