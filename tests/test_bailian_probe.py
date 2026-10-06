"""Offline protocol checks; never call the provider or read real credentials."""
import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from tools.probe_bailian import ProbeStream, run, sanitize


def frame(step='generating', change='', content='', finish='', role='assistant', **kwargs):
    return json.dumps({'code': '200', 'request_id': 'test-request', 'output': {'choices': [
        {'message': {'role': role, 'content': content, 'extra': {'step': step, 'step_change': change}, **kwargs},
         'finish_reason': finish}]}}, ensure_ascii=False)


async def lines(values):
    for value in values:
        yield value


class ProbeTests(unittest.TestCase):
    def test_planning_hidden_and_final_usage_not_summed(self):
        state = ProbeStream()
        state.event('message', frame('planning', content='private planning'))
        state.event('message', frame(content='回答'))
        final = json.loads(frame(change='generation_end', finish='stop'))
        final['usage'] = {'total_tokens': 20}
        state.event('message', json.dumps(final))
        self.assertEqual(state.answer, '回答')
        self.assertNotIn('private planning', json.dumps(state.trace))
        self.assertEqual(state.summary()['final_usage'], {'total_tokens': 20})
        self.assertTrue(state.summary()['transport_complete'])

    def test_done_alone_and_abrupt_eof_are_not_success(self):
        state = ProbeStream()
        state.event('message', frame(content='partial'))
        state.event('message', '[DONE]')
        self.assertFalse(state.summary()['transport_complete'])
        with self.assertRaisesRegex(ValueError, 'unframed_eof'):
            asyncio.run(ProbeStream().read(lines(['data: ' + frame(content='partial')])))

    def test_sse_comments_multiline_json_and_empty_packets(self):
        state = ProbeStream()
        event = frame(content='中文回答')
        split = event.index('"output"')
        asyncio.run(state.read(lines([': heartbeat', '', 'event: message',
                                      'data: ' + event[:split], 'data: ' + event[split:], '',
                                      'data: {}', '', 'data: ' + frame(change='generation_end', finish='stop'), ''])))
        self.assertEqual(state.answer, '中文回答')
        self.assertTrue(state.summary()['transport_complete'])

    def test_business_error_after_end_invalidates_success(self):
        state = ProbeStream()
        state.event('message', frame(change='generation_end', finish='stop', content='answer'))
        state.event('error', '{"code":"AgentApp.NotFound","message":"private details"}')
        self.assertFalse(state.summary()['transport_complete'])
        self.assertNotIn('private details', json.dumps(state.summary()))

    def test_tools_linked_but_numeric_candidates_are_not_semantic_proof(self):
        state = ProbeStream()
        state.event('message', frame('tool_calling', tool_calls=[{'id': 'call1', 'function': {'name': 'semantic_search'}}]))
        state.event('message', frame('tool_calling', role='tool', tool_call_id='call1',
                                    additional_kwargs={'extra_json': {'docs': [{'_citation_index': 1, 'text': 'evidence'}]}}))
        state.event('message', frame(content='answer [1] [2]'))
        summary = state.summary()
        self.assertTrue(summary['tool_returns_have_matching_call'])
        self.assertEqual(summary['bracket_candidates_without_matching_index'], ['2'])
        self.assertEqual(summary['semantic_support'], 'not_automatically_verified')

    def test_credentials_and_signed_urls_redacted_recursively(self):
        value = {'api_key': 'secret', 'nested': ['secret https://private.example/doc?signature=abc'],
                 'file_url': 'https://private.example/', 'input_tokens': 2}
        sanitized = sanitize(value, 'secret')
        text = json.dumps(sanitized)
        self.assertNotIn('private.example', text)
        self.assertNotIn('signature', text)
        self.assertNotIn('secret', text)
        self.assertEqual(sanitized['input_tokens'], 2)

    def invoke(self, handler, max_requests=4):
        client_class = httpx.AsyncClient
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            questions = root / 'questions.json'
            questions.write_text(json.dumps({'cases': [
                {'name': 'supported', 'question': 'supported', 'history_from': None},
                {'name': 'paraphrase', 'question': 'paraphrase', 'history_from': None},
                {'name': 'followup', 'question': 'followup', 'history_from': 'supported'},
                {'name': 'missing', 'question': 'missing', 'history_from': None}]}))
            args = SimpleNamespace(questions=questions, output=root/'results', max_requests=max_requests, timeout=5)
            def factory(**kwargs):
                return client_class(transport=httpx.MockTransport(handler), **kwargs)
            with patch.dict(os.environ, {'DASHSCOPE_API_KEY': 'test-key', 'BAILIAN_WORKSPACE_ID': 'llm-test', 'BAILIAN_AGENT_ID': 'aid-test'}), patch('httpx.AsyncClient', factory):
                status = asyncio.run(run(args))
            summary = json.loads((args.output/'summary.json').read_text())
            return status, summary

    def test_live_path_error_stops_suite_without_retry(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(401, text='test-key upstream private error')
        status, summary = self.invoke(handler)
        self.assertEqual(len(requests), 1)
        self.assertEqual(status, 1)
        self.assertEqual(summary['attempted_requests'], 1)
        self.assertNotIn('test-key', json.dumps(summary))

    def test_live_path_followup_has_only_its_expected_history(self):
        payloads = []
        def handler(request):
            payloads.append(json.loads(request.content))
            self.assertEqual(request.headers['Authorization'], 'Bearer test-key')
            self.assertTrue(payloads[-1]['stream'])
            stream = 'data: ' + frame(content='answer') + '\n\ndata: ' + frame(change='generation_end', finish='stop') + '\n\n'
            return httpx.Response(200, headers={'content-type':'text/event-stream'}, content=stream)
        status, summary = self.invoke(handler)
        self.assertEqual(status, 0)
        self.assertEqual([len(payload['input']['messages']) for payload in payloads], [1,1,3,1])
        self.assertEqual(payloads[2]['input']['messages'][0]['content'], 'supported')
        self.assertEqual(summary['attempted_requests'], 4)


if __name__ == '__main__':
    unittest.main()
