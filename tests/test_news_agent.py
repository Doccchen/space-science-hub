"""Offline application SSE, original-body, isolation, budget and MCP acceptance."""
import asyncio
import json
import tempfile
import time
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import httpx
from cryptography.fernet import Fernet
from fastapi import FastAPI

from backend import ai, news, news_agent, news_context, news_mcp, reading
from backend.bailian import AIError
from backend.html_sources import parse_detail
from backend.news_agent_client import ApplicationStream, NewsAgentClient, NewsAnswer
from backend.news_context_store import Store

FIXTURES = Path(__file__).parent / 'fixtures'
MANIFEST = json.loads((FIXTURES / 'manifest.json').read_text(encoding='utf-8'))


def frame(text='', finish=None, **output):
    return 'data: ' + json.dumps({'output': {'text': text, 'session_id': 'cloud-private-session',
                                            'finish_reason': finish, **output},
                                 'usage': {'models': [{'input_tokens': 20, 'output_tokens': 10}]},
                                 'request_id': 'provider-1'}, ensure_ascii=False) + '\n\n'


class Protocol(unittest.IsolatedAsyncioTestCase):
    def test_real_application_sse_samples_replay(self):
        evidence = json.loads((FIXTURES / 'news-agent/application-real-20261008.json').read_text(encoding='utf-8'))
        self.assertEqual(evidence['provenance']['kind'], 'real_application_sse_redacted')
        for index, sample in enumerate(evidence['samples']):
            with self.subTest(round=index + 1):
                state = ApplicationStream()
                for frame_data in sample['frames']:
                    data = frame_data['data']
                    state.frame(frame_data['event'], data if isinstance(data, str) else json.dumps(data, ensure_ascii=False))
                answer = state.result('')
                self.assertEqual(answer.usage, sample['usage'])
                self.assertEqual(len(answer.references), sample['reference_count'])
                self.assertEqual(answer.session_id, 'sample-session')
                self.assertEqual(len(answer.text), [587, 1191][index])
                self.assertTrue(state.ended)
                self.assertEqual(len(sample['frames']), [321, 426][index])

    async def call(self, payload, incremental=True, status=200):
        self.calls = []
        def handler(request):
            self.calls.append(json.loads(request.content))
            return httpx.Response(status, headers={'Content-Type': 'text/event-stream'}, content=payload)
        client = NewsAgentClient('e366df4514cb4606b95821b9d03c387e', 'private-key',
                                 transport=httpx.MockTransport(handler), incremental=incremental)
        return await client.ask('question', 'previous', {'tool': {'X-News-Context': 'opaque'}})

    async def test_incremental_thoughts_null_references_and_usage(self):
        answer = await self.call(': heartbeat\n\n' + frame(thoughts=[{'thought': 'hidden'}], doc_references=None)
                                 + frame('正文') + frame(' [b0001]', 'stop'))
        self.assertEqual(answer.text, '正文 [b0001]')
        self.assertEqual(answer.usage['total_tokens'], 30)
        self.assertNotIn('hidden', answer.text)
        self.assertEqual(self.calls[0]['input']['session_id'], 'previous')
        self.assertIn('biz_params', self.calls[0]['input'])

    async def test_cumulative(self):
        self.assertEqual((await self.call(frame('a') + frame('ab', 'stop'), False)).text, 'ab')

    async def test_incomplete_business_error_and_no_retry(self):
        for payload in (frame('partial'), frame('partial') + 'data: [DONE]\n\n',
                        frame('complete', 'stop').rstrip(), frame('cut', 'length'),
                        frame('complete', 'stop') + 'event: error\ndata: {"code":"Failure"}\n\n'):
            with self.subTest(payload=payload), self.assertRaises(AIError):
                await self.call(payload)
            self.assertEqual(len(self.calls), 1)
        with self.assertRaises(AIError):
            await self.call('', status=429)
        self.assertEqual(len(self.calls), 1)

    async def test_multiline_data_and_sensitive_text(self):
        payload = frame('private-key https://private.invalid/?token=secret', 'stop').replace('{"output":', '{\ndata: "output":')
        answer = await self.call(payload)
        self.assertNotIn('private-key', answer.text)
        self.assertNotIn('private.invalid', answer.text)

    def test_session_changes_unknown_choices_and_oversize_rejected(self):
        state = ApplicationStream()
        state.frame('message', json.dumps({'output': {'text': 'one', 'session_id': 'a'}}))
        with self.assertRaises(AIError):
            state.frame('message', json.dumps({'output': {'text': 'two', 'session_id': 'b'}}))
        state = ApplicationStream()
        state.frame('message', json.dumps({'output': {'choices': [{'message': {'content': 'planning'}}]}}))
        with self.assertRaises(AIError):
            state.result('')
        with self.assertRaises(AIError):
            ApplicationStream().frame('message', json.dumps({'output': {'text': 'x' * 16001}}))

    def test_probe_samples_redact_credentials_sessions_thoughts_and_raw_docs(self):
        from tools.probe_news_agent import redact_frame
        payload = {'output': {'text': 'secret-key private-session older-session https://private.invalid/?token=key', 'session_id': 'private-session',
                              'thoughts': [{'thought': 'private-planning'}],
                              'doc_references': [{'doc_id': 'd1', 'doc_name': 'private-session', 'text':'private-doc', 'doc_url':'https://private.invalid'}]},
                   'usage': {'models': [{'input_tokens': 1, 'output_tokens': 2}]}}
        sample = redact_frame('message', json.dumps(payload), 'secret-key', ['older-session'])
        serialized = json.dumps(sample)
        for private in ('secret-key', 'private.invalid', 'private-session', 'older-session', 'private-planning', 'private-doc'):
            self.assertNotIn(private, serialized)
        self.assertTrue(sample['has_thoughts'])
        self.assertEqual(sample['data']['output']['session_id'], 'sample-session')


class FakeClient:
    def __init__(self):
        self.calls, self.error, self.service = [], None, None
        self.start, self.finish = None, None

    async def ask(self, prompt, session=None, token_mapping=None):
        self.calls.append((prompt, session, token_mapping))
        if self.start:
            self.start.set()
            await self.finish.wait()
        if self.error:
            raise self.error
        if token_mapping and self.service:
            token = next(iter(token_mapping.values()))['X-News-Context']
            scope = json.loads(self.service.cipher.decrypt(token.encode()))
            await self.service.read_tool(token, scope['article_id'])
        return NewsAnswer('说明 [b0001] [b9999] <script>alert(1)</script>', 'private-upstream-session',
                          [{'doc_id': 'invented'}], {'total_tokens': 30}, 'provider-1')


class NewsWork(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.old_path = news.DB_PATH
        news.DB_PATH = self.root / 'news.sqlite3'
        news.initialize()
        self.raw = (FIXTURES / 'cnsa/detail-0.html').read_bytes()
        self.url = MANIFEST['cnsa']['details'][0]['url']
        record = parse_detail('cnsa', self.raw, {'url': self.url})
        news.store_records([record])
        with news.connect() as db:
            db.execute("UPDATE sources SET enabled=1 WHERE id='cnsa'")
        self.store = Store(self.root / 'news-agent.sqlite3')
        self.budget = ai.AIService(ai.Settings(enabled=True, key='test', db=self.root / 'ai.sqlite3'))
        self.provider = FakeClient()
        self.settings = news_agent.Settings(enabled=True, context_enabled=True, key='dummy')
        self.service = news_agent.NewsAgentService(self.settings, self.budget, self.store, self.provider, Fernet(Fernet.generate_key()))
        self.assertIsNone(self.service.problem)
        self.fetch = patch('backend.news_context.Publisher.get', return_value=(self.raw, 'text/html'))
        self.mock_fetch = self.fetch.start()
        self.app = FastAPI(); self.app.include_router(news_agent.router); self.app.include_router(ai.router)
        self.app.state.news_agent = self.service; self.app.state.ai = self.budget
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://test')
        reply = await self.http.post('/api/news/1/conversations')
        self.identity = reply.json()['conversation_id']

    async def asyncTearDown(self):
        await self.service.close()
        await self.http.aclose()
        self.fetch.stop()
        news.DB_PATH = self.old_path
        self.folder.cleanup()

    async def submit(self, request_id=None, question='这次有什么进展？', identity=None, explanation=False):
        payload = {'conversation_id': identity or self.identity, 'request_id': request_id or str(uuid.uuid4())}
        if not explanation:
            payload['question'] = question
        return await self.http.post('/api/news/1/explanation-jobs' if explanation else '/api/news-agent/messages', json=payload)

    async def finish_jobs(self):
        await asyncio.gather(*self.service.tasks)

    async def test_two_rounds_idempotency_private_draft_and_no_session_leak(self):
        request_id = str(uuid.uuid4())
        first = await self.submit(request_id, explanation=True)
        await self.finish_jobs()
        self.assertEqual(first.status_code, 202)
        again = await self.submit(request_id, explanation=True)
        self.assertEqual(first.json(), again.json())
        self.assertEqual(len(self.provider.calls), 1)
        job = (await self.http.get('/api/news-agent/jobs/' + first.json()['job_id'])).json()
        self.assertEqual(job['stage'], 'complete')
        self.assertEqual(job['result']['news_citations'], ['b0001'])
        self.assertNotIn('[b9999]', job['result']['answer'])
        self.assertEqual(job['result']['knowledge_evidence'], 'unverified')
        self.assertNotIn('private-upstream-session', json.dumps(job))
        await self.submit(); await self.finish_jobs()
        self.assertEqual(self.provider.calls[-1][1], 'private-upstream-session')
        self.assertEqual(self.mock_fetch.call_count, 1)
        self.assertEqual((await self.http.get('/api/news/1/explanation')).json(), {'explanation': None})
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT status FROM news_explanations').fetchone()[0], 'draft')
            self.assertNotIn('private-upstream-session', db.execute('SELECT session FROM news_agent_conversations').fetchone()[0])

    async def test_owner_origin_payload_and_cross_article_isolation(self):
        first = await self.submit(); await self.finish_jobs()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://test') as other:
            self.assertEqual((await other.get('/api/news-agent/jobs/' + first.json()['job_id'])).status_code, 404)
            self.assertEqual((await other.delete('/api/news-agent/conversations/' + self.identity)).status_code, 404)
        self.assertEqual((await self.http.post('/api/news/1/conversations', headers={'Origin': 'http://evil'})).status_code, 403)
        extra = {'conversation_id': self.identity, 'request_id': str(uuid.uuid4()), 'question': 'x', 'session_id': 'evil'}
        self.assertEqual((await self.http.post('/api/news-agent/messages', json=extra)).status_code, 422)
        payload = {'conversation_id': self.identity, 'request_id': str(uuid.uuid4())}
        self.assertEqual((await self.http.post('/api/news/2/explanation-jobs', json=payload)).status_code, 409)
        with self.assertRaises(AIError):
            await self.service.read_tool('model-invented-token', 1)

    async def test_shared_global_visitor_budget_and_capacity(self):
        await self.submit(); await self.finish_jobs()
        self.budget.settings.visitor_daily = 1
        generic = await self.http.post('/api/ai/conversations')
        response = await self.http.post('/api/ai/ask', json={'conversation_id': generic.json()['conversation_id'],
                                            'request_id': str(uuid.uuid4()), 'question': 'x'})
        self.assertEqual(response.json()['error']['code'], 'daily_limit')
        self.assertEqual((await self.submit()).status_code, 429)
        self.budget.settings.visitor_daily = 20
        self.budget.active = self.budget.settings.concurrency
        self.assertEqual((await self.submit()).json()['error']['code'], 'capacity')
        self.budget.active = 0

    async def test_legacy_ai_cookie_migrates_without_invalidating_old_conversation(self):
        self.http.cookies.clear()
        cookie = 'b' * 64
        self.http.cookies.set(ai.COOKIE, cookie, domain='test.local', path='/api/ai')
        old = (await self.http.post('/api/ai/conversations')).json()['conversation_id']
        # Simulate pre-upgrade browser state: only the narrow cookie, already-owned conversation.
        self.http.cookies.clear()
        self.http.cookies.set(ai.COOKIE, cookie, domain='test.local', path='/api/ai')
        self.assertEqual((await self.http.post('/api/ai/visitor')).status_code, 204)
        self.assertEqual((await self.http.post('/api/news/1/conversations')).status_code, 200)
        import hashlib
        with self.budget.connection() as db:
            self.budget.conversation(db, old, hashlib.sha256(cookie.encode()).hexdigest())
        response = await self.http.delete('/api/ai/conversations/' + old)
        self.assertEqual(response.status_code, 204)
        self.assertEqual((await self.http.post('/api/ai/visitor', headers={'Origin':'https://evil'})).status_code, 403)

    async def test_body_refresh_changes_content_version_and_invalidates_session(self):
        await self.submit(); await self.finish_jobs()
        with self.store.connection() as db:
            db.execute('DELETE FROM news_contexts')
        self.mock_fetch.return_value = (b'<div class="wz_conten"><p>Updated body</p></div>', 'text/html')
        await self.service.context.read(1)
        self.assertEqual((await self.submit()).json()['error']['code'], 'context_changed')
        self.assertEqual(len(self.provider.calls), 1)

    async def test_body_change_or_withdrawal_stops_old_session(self):
        with news.connect() as db:
            db.execute("UPDATE articles SET content_hash='changed' WHERE id=1")
        self.assertEqual((await self.submit()).json()['error']['code'], 'context_changed')
        self.assertEqual(len(self.provider.calls), 0)
        self.assertEqual((await self.http.delete('/api/news-agent/conversations/' + self.identity)).status_code, 204)

    async def test_failure_and_restart_do_not_retry(self):
        self.provider.error = AIError('upstream_timeout')
        request_id = str(uuid.uuid4())
        result = await self.submit(request_id); await self.finish_jobs()
        await self.submit(request_id)
        self.assertEqual(len(self.provider.calls), 1)
        with self.store.connection() as db:
            db.execute("UPDATE news_agent_jobs SET stage='generating'")
        self.store.interrupt()
        self.assertEqual((await self.http.get('/api/news-agent/jobs/' + result.json()['job_id'])).json()['stage'], 'interrupted')
        with self.budget.connection() as db:
            self.assertIsNone(db.execute('SELECT tokens FROM requests').fetchone()[0])

    async def test_delete_during_generation_erases_late_reply_but_accounts_usage(self):
        self.provider.start, self.provider.finish = asyncio.Event(), asyncio.Event()
        result = await self.submit()
        await self.provider.start.wait()
        await self.http.delete('/api/news-agent/conversations/' + self.identity)
        self.provider.finish.set(); await self.finish_jobs()
        self.assertEqual((await self.http.get('/api/news-agent/jobs/' + result.json()['job_id'])).status_code, 404)
        with self.store.connection() as db:
            self.assertIsNone(db.execute('SELECT result FROM news_agent_jobs').fetchone()[0])
            self.assertIsNone(db.execute('SELECT session FROM news_agent_conversations').fetchone()[0])
        with self.budget.connection() as db:
            self.assertEqual(db.execute('SELECT tokens FROM requests').fetchone()[0], 30)

    async def test_context_dedup_partial_table_and_pending_cooldown(self):
        self.mock_fetch.return_value = (b'<div class="wz_conten"><p>Original</p><ul><li>One</li><li>Two</li></ul>'
                                        b'<table><tr><td>27</td><td>km</td></tr></table></div>', 'text/html')
        results = await asyncio.gather(self.service.context.read(1), self.service.context.read(1))
        self.assertEqual(self.mock_fetch.call_count, 1)
        self.assertEqual(results[0]['read_status'], 'full')
        self.assertEqual([b['type'] for b in results[0]['blocks']], ['paragraph', 'list', 'table'])
        with self.store.connection() as db: db.execute('DELETE FROM news_contexts')
        self.mock_fetch.return_value = (b'<div class="wz_conten"><div>Omitted</div><p>part</p></div>', 'text/html')
        await self.submit(); await self.finish_jobs()
        self.assertEqual(len(self.provider.calls), 0)
        self.assertEqual((await self.service.context.read(1))['read_status'], 'partial')
        self.assertEqual(self.mock_fetch.call_count, 2)

    async def test_mcp_transport_auth_and_scoped_tool(self):
        self.settings.mcp_enabled = self.settings.mcp_verified = True
        self.settings.mcp_key = 'service-' + 'a' * 32; self.settings.plugin_code = 'news-tool'
        self.provider.service = self.service
        result = await self.submit(); await self.finish_jobs()
        job = (await self.http.get('/api/news-agent/jobs/' + result.json()['job_id'])).json()
        self.assertEqual(job['stage'], 'complete')
        with self.store.connection() as db:
            row = db.execute('SELECT tool_calls,tool_read_version FROM news_agent_jobs').fetchone()
            self.assertEqual(row['tool_calls'], 1); self.assertTrue(row['tool_read_version'])
        sdk, transport = news_mcp.build(lambda: self.service)
        app = FastAPI(); app.mount('/tool', transport)
        async with sdk.session_manager.run(), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            request = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {}}
            self.assertEqual((await client.post('/tool/mcp', json=request)).status_code, 401)
            headers = {'Authorization': 'Bearer ' + self.settings.mcp_key, 'Accept': 'application/json, text/event-stream'}
            reply = await client.post('/tool/mcp', json=request, headers=headers)
            self.assertEqual(reply.status_code, 200)
            self.assertEqual(reply.json()['result']['tools'][0]['name'], 'read_news')
            request.update(method='tools/call', params={'name': 'read_news', 'arguments': {'article_id': 1}})
            reply = await client.post('/tool/mcp', json=request, headers=headers)
            self.assertEqual(reply.json()['result']['structuredContent']['read_status'], 'blocked')

    async def test_all_registered_sources_have_explicit_support(self):
        self.assertEqual(set(news.SOURCES), set(news_context.SOURCE_REGISTRY))
        self.assertEqual(news_context.SOURCE_REGISTRY['esa']['status'], 'unsupported')
        for source in ('cnsa', 'cmse', 'cas_space', 'landspace'):
            for index, sample in enumerate(MANIFEST[source]['details']):
                raw = (FIXTURES / source / f'detail-{index}.html').read_bytes()
                record = parse_detail(source, raw, {'url': sample['url']})
                news.store_records([record])
                with news.connect() as db:
                    db.execute('UPDATE sources SET enabled=1 WHERE id=?', (source,))
                    article_id = db.execute('SELECT id FROM articles WHERE original_url=?', (sample['url'],)).fetchone()[0]
                self.mock_fetch.return_value = (raw, 'text/html')
                context = await self.service.context.read(article_id)
                self.assertIn(context['read_status'], {'full', 'partial'}, (source, index, context))
                self.assertTrue(context['blocks'])

    async def test_valid_tool_token_cannot_change_article_exceed_budget_or_survive_delete(self):
        self.provider.start, self.provider.finish = asyncio.Event(), asyncio.Event()
        result = await self.submit()
        await self.provider.start.wait()
        with self.store.connection() as db:
            conversation = dict(db.execute('SELECT * FROM news_agent_conversations WHERE id=?', (self.identity,)).fetchone())
        token = self.service.tool_token(result.json()['job_id'], conversation)
        with self.assertRaises(AIError): await self.service.read_tool(token, 2)
        with self.assertRaises(AIError): await self.service.read_tool(token + 'bad', 1)
        self.settings.mcp_enabled = True
        self.settings.mcp_key = 'test-' + 'c' * 32
        sdk, transport = news_mcp.build(lambda: self.service)
        tool_app = FastAPI(); tool_app.mount('/tools', transport)
        async with sdk.session_manager.run(), httpx.AsyncClient(transport=httpx.ASGITransport(app=tool_app), base_url='http://test') as client:
            headers = {'Authorization': 'Bearer ' + self.settings.mcp_key, 'X-News-Context': token,
                       'Accept': 'application/json, text/event-stream'}
            reply = await client.post('/tools/mcp', headers=headers,
                                      json={'jsonrpc':'2.0','id':1,'method':'tools/call',
                                            'params':{'name':'read_news','arguments':{'article_id':1}}})
            self.assertEqual(reply.json()['result']['structuredContent']['read_status'], 'full')
        self.settings.mcp_enabled = False
        for _ in range(2):
            self.assertEqual((await self.service.read_tool(token, 1))['read_status'], 'full')
        with self.assertRaises(AIError): await self.service.read_tool(token, 1)
        scope = json.loads(self.service.cipher.decrypt(token.encode())); scope['expires'] = 0
        expired = self.service.cipher.encrypt(json.dumps(scope).encode()).decode()
        with self.assertRaises(AIError): await self.service.read_tool(expired, 1)
        self.service.delete(self.identity, conversation['owner'])
        with self.assertRaises(AIError): await self.service.read_tool(token, 1)
        self.provider.finish.set(); await self.finish_jobs()

    async def test_pending_fetch_remains_deduplicated_after_caller_timeout(self):
        release, started = threading.Event(), threading.Event()
        def slow_fetch(*args, **kwargs):
            started.set(); release.wait(timeout=2)
            return self.raw, 'text/html'
        self.mock_fetch.side_effect = slow_fetch
        self.service.context.timeout = .01
        try:
            first = await self.service.context.read(1)
            self.assertTrue(started.is_set())
            second = await self.service.context.read(1)
            self.assertEqual(first['read_status'], 'pending')
            self.assertEqual(second['read_status'], 'pending')
            self.assertEqual(self.mock_fetch.call_count, 1)
        finally:
            release.set()
        await asyncio.gather(*self.service.context.tasks.values())
        self.assertEqual((await self.service.context.read(1))['read_status'], 'full')

    async def test_withdrawal_after_cache_stops_generation(self):
        await self.service.context.read(1)
        with news.connect() as db: db.execute("UPDATE sources SET enabled=0 WHERE id='cnsa'")
        self.assertEqual((await self.service.context.read(1))['read_status'], 'withdrawn')
        self.assertEqual((await self.submit()).json()['error']['code'], 'withdrawn')
        self.assertEqual(len(self.provider.calls), 0)


if __name__ == '__main__':
    unittest.main()
