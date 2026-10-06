"""Offline AI protocol/session/budget regression tests; no provider calls."""
import asyncio
import json
import tempfile
import time
import unittest
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.ai import AIService, Settings, router
from backend.bailian import AIError, Answer, BailianClient, KnowledgeStream


def frame(step='generating',change='',content='',role='assistant',finish='',**kwargs):
    return json.dumps({'code':'200','request_id':'provider-request','output':{'choices':[
        {'message':{'role':role,'extra':{'step':step,'step_change':change},'content':content,**kwargs},
         'finish_reason':finish}]},'usage':{'total_tokens':42} if change=='generation_end' else None},ensure_ascii=False)


class FakeClient:
    def __init__(self):
        self.calls=[]
        self.error=None
    async def ask(self,messages,request_id):
        self.calls.append(messages)
        if self.error:
            raise self.error
        return Answer('说明 **概念**',[{'name':'测试文档','positions':[0,1]}],{'total_tokens':42},'provider-request',True)


class Sessions(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.settings=Settings(enabled=True,key='test-secret',db=Path(self.temp.name)/'ai.sqlite3')
        self.provider=FakeClient()
        self.service=AIService(self.settings,self.provider)
        app=FastAPI();app.include_router(router);app.state.ai=self.service
        self.client=TestClient(app)
        self.app=app
        self.session=self.client.post('/api/ai/conversations').json()['conversation_id']
    def tearDown(self):
        self.client.close();self.temp.cleanup()
    def ask(self,text='问题',request_id=None,session=None,client=None):
        return (client or self.client).post('/api/ai/ask',json={'conversation_id':session or self.session,
                       'request_id':request_id or str(uuid.uuid4()),'question':text})
    def test_history_and_idempotency(self):
        request=str(uuid.uuid4())
        first=self.ask(request_id=request)
        self.assertEqual(first.status_code,200)
        self.assertEqual(self.ask(request_id=request).json(),first.json())
        self.assertEqual(len(self.provider.calls),1)
        self.assertEqual(self.ask().status_code,200)
        self.assertEqual(len(self.provider.calls[-1]),3)
        self.assertEqual(first.json()['remaining_rounds'],4)
        self.assertEqual(self.ask('changed',request).status_code,409)
    def test_visitor_isolation(self):
        other=TestClient(self.app)
        try:
            self.assertEqual(self.ask(client=other).status_code,409)
            self.assertEqual(other.delete('/api/ai/conversations/'+self.session).status_code,409)
            self.assertEqual(len(self.provider.calls),0)
        finally:other.close()
    def test_clear_erases_history_and_invalidates_old_session(self):
        self.ask()
        self.assertEqual(self.client.delete('/api/ai/conversations/'+self.session).status_code,204)
        self.assertEqual(self.ask().status_code,409)
        with self.service.connection() as db:
            self.assertEqual(db.execute('SELECT history FROM conversations').fetchone()[0],'[]')
            self.assertIsNone(db.execute('SELECT result FROM requests').fetchone()[0])
    def test_daily_budget_persists_through_restart(self):
        self.settings.visitor_daily=1
        self.assertEqual(self.ask().status_code,200)
        self.app.state.ai=AIService(self.settings,self.provider)
        response=self.ask()
        self.assertEqual(response.status_code,429)
        self.assertEqual(response.json()['error']['code'],'daily_limit')
        self.assertEqual(len(self.provider.calls),1)
    def test_failed_call_reserves_quota_and_is_not_retried(self):
        self.provider.error=AIError('upstream_timeout',504)
        request=str(uuid.uuid4())
        self.assertEqual(self.ask(request_id=request).status_code,504)
        self.assertEqual(self.ask(request_id=request).status_code,409)
        self.assertEqual(len(self.provider.calls),1)
        with self.service.connection() as db:
            row=db.execute('SELECT tokens,reservation,status FROM requests').fetchone()
        self.assertIsNone(row['tokens']);self.assertEqual(row['reservation'],20000);self.assertEqual(row['status'],'error')
    def test_token_budget_rejects_before_provider_call(self):
        self.settings.token_daily=1
        self.assertEqual(self.ask().status_code,429)
        self.assertEqual(len(self.provider.calls),0)
    def test_origin_request_shape_and_limits(self):
        self.assertEqual(self.client.post('/api/ai/conversations',headers={'Origin':'https://other.invalid'}).status_code,403)
        self.assertEqual(self.ask('x'*1501).status_code,422)
        body={'conversation_id':self.session,'request_id':str(uuid.uuid4()),'question':'x','messages':[]}
        self.assertEqual(self.client.post('/api/ai/ask',json=body).status_code,422)
        self.assertEqual(self.ask('   ').status_code,422)
        self.assertNotIn('test-secret',self.client.get('/api/ai/status').text)
    def test_expired_and_config_changed_sessions(self):
        with self.service.connection() as db:db.execute('UPDATE conversations SET expires=?',(time.time()-1,))
        self.assertEqual(self.ask().status_code,409)
        self.assertEqual(len(self.provider.calls),0)
    def test_same_session_pending_and_global_capacity(self):
        owner=self.service_owner()
        self.service.reserve(self.session,owner,'ip',str(uuid.uuid4()),'first')
        self.assertEqual(self.ask().json()['error']['code'],'session_busy')
        fresh=self.client.post('/api/ai/conversations').json()['conversation_id']
        self.service.active=self.settings.concurrency
        self.assertEqual(self.ask(session=fresh).json()['error']['code'],'capacity')
    def service_owner(self):
        import hashlib
        return hashlib.sha256(self.client.cookies.get('space_ai_visitor').encode()).hexdigest()
    def test_round_limit(self):
        self.settings.rounds=1
        self.assertEqual(self.ask().json()['remaining_rounds'],0)
        self.assertEqual(self.ask().json()['error']['code'],'history_limit')
    def test_disabled_and_bad_config_do_not_break_status(self):
        self.app.state.ai=AIService(Settings())
        self.assertFalse(self.client.get('/api/ai/status').json()['enabled'])
        self.assertEqual(self.ask().status_code,503)
        self.app.state.ai=AIService(Settings(enabled=True))
        self.assertFalse(self.client.get('/api/ai/status').json()['enabled'])


class LateReply(unittest.IsolatedAsyncioTestCase):
    async def test_deleted_session_rejects_late_answer_but_records_usage(self):
        with tempfile.TemporaryDirectory() as folder:
            start,finish=asyncio.Event(),asyncio.Event()
            class Delayed(FakeClient):
                async def ask(self,*args):
                    start.set();await finish.wait();return await super().ask(*args)
            service=AIService(Settings(enabled=True,key='dummy',db=Path(folder)/'ai.sqlite3'),Delayed())
            session=service.create('owner')
            task=asyncio.create_task(service.ask(session,'owner','ip',str(uuid.uuid4()),'question'))
            await start.wait();service.delete(session,'owner');finish.set()
            with self.assertRaises(AIError):await task
            with service.connection() as db:
                row=db.execute('SELECT status,tokens,result FROM requests').fetchone()
                self.assertEqual(row['tokens'],42);self.assertEqual(row['status'],'error');self.assertIsNone(row['result'])


class Protocol(unittest.TestCase):
    def test_sources_no_raw_urls_and_no_source_fallback(self):
        state=KnowledgeStream()
        state.frame('message',frame('planning',content='hidden thinking'))
        state.frame('message',frame(content='answer test-secret https://private.invalid/?signature=secret'))
        state.frame('message',frame('tool_calling',role='tool',additional_kwargs={'extra_json':{'docs':[
            {'doc_name':'test','content':'evidence','page_number':[0,1],'doc_url':'https://private.invalid'}]}}))
        state.frame('message',frame(change='generation_end',finish='stop'))
        answer=state.result('test-secret')
        self.assertNotIn('private.invalid',answer.text);self.assertNotIn('test-secret',answer.text)
        self.assertNotIn('hidden thinking',answer.text);self.assertEqual(answer.sources,[{'name':'test','positions':[0,1]}])
        state.docs=[]
        self.assertFalse(state.result('').grounded)
        self.assertNotIn('answer',state.result('').text)
    def test_stream_error_even_after_generation_end(self):
        state=KnowledgeStream();state.frame('message',frame(change='generation_end',finish='stop',content='answer'))
        with self.assertRaises(AIError):state.frame('error','{"code":"AgentApp.NotFound"}')
    def test_http_errors_no_retries(self):
        calls=[]
        def handler(request):calls.append(request);return httpx.Response(429)
        client=BailianClient('llm-test','aid-test','dummy',transport=httpx.MockTransport(handler))
        with self.assertRaises(AIError) as error:asyncio.run(client.ask([{'role':'user','content':'q'}]))
        self.assertEqual(error.exception.code,'upstream_rate_limit');self.assertEqual(len(calls),1)
    def test_complete_sse_and_incomplete_sse(self):
        payload=': heartbeat\n\ndata: '+frame(content='answer')+'\n\ndata: '+frame(change='generation_end',finish='stop')+'\n\n'
        def handler(request):return httpx.Response(200,headers={'content-type':'text/event-stream'},content=payload)
        client=BailianClient('llm-test','aid-test','dummy',transport=httpx.MockTransport(handler))
        self.assertFalse(asyncio.run(client.ask([{'role':'user','content':'q'}])).grounded)
        payload='data: '+frame(content='partial')+'\n\ndata: [DONE]\n\n'
        with self.assertRaises(AIError):asyncio.run(client.ask([{'role':'user','content':'q'}]))


if __name__=='__main__':unittest.main()
