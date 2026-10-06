"""Bounded knowledge-chat SSE adapter. No retries, planning output or private URLs."""
import asyncio
import json
import re
import uuid
from dataclasses import dataclass

import httpx


class AIError(Exception):
    def __init__(self, code, status=503):
        self.code, self.status = code, status
        super().__init__(code)


@dataclass
class Answer:
    text: str
    sources: list
    usage: dict | None
    request_id: str | None
    grounded: bool


def public_text(value, key='', maximum=12000):
    text = str(value or '')
    if key:
        text = text.replace(key, '[已隐藏]')
    text = re.sub(r'https?://[^\s<>"\)\]]+', '[链接未公开]', text)
    return text[:maximum]


class KnowledgeStream:
    def __init__(self):
        self.text = ''
        self.docs = []
        self.ended = False
        self.usage = None
        self.request_id = None
        self.events = 0

    def frame(self, event, content):
        self.events += 1
        if self.events > 20000:
            raise AIError('upstream_format')
        if content.strip() == '[DONE]':
            return
        try:
            data = json.loads(content)
            if not isinstance(data, dict):
                raise ValueError()
            if data.get('request_id'):
                self.request_id = str(data['request_id'])[:100]
            if event == 'error' or str(data.get('code', '200')) != '200':
                raise AIError('upstream_error')
            for choice in data.get('output', {}).get('choices', []):
                message = choice.get('message', {})
                extra = message.get('extra') or {}
                if message.get('role') == 'tool':
                    tool = (message.get('additional_kwargs') or {}).get('extra_json') or {}
                    if isinstance(tool, str):
                        tool = json.loads(tool)
                    docs = tool.get('docs', [])
                    if not isinstance(docs, list):
                        raise ValueError()
                    self.docs.extend(doc for doc in docs if isinstance(doc, dict))
                if message.get('role') == 'assistant' and extra.get('step') == 'generating':
                    text = message.get('content', '')
                    if isinstance(text, list):
                        text = ''.join(part.get('text', '') for part in text if part.get('type') == 'text')
                    if not isinstance(text, str):
                        raise ValueError()
                    self.text += text
                    if len(self.text) > 12000:
                        raise AIError('answer_too_long')
                finish = choice.get('finish_reason') or (message.get('response_metadata') or {}).get('finish_reason')
                if extra.get('step') == 'generating' and extra.get('step_change') == 'generation_end' and finish == 'stop':
                    self.ended = True
                    usage = data.get('usage')
                    if isinstance(usage, dict):
                        self.usage = {key: value for key, value in usage.items()
                                      if key in ('input_tokens','output_tokens','total_tokens','cached_tokens')
                                      and type(value) is int and value >= 0}
        except (ValueError, TypeError, AttributeError, KeyError):
            raise AIError('upstream_format') from None

    async def read(self, lines):
        event, data, size = 'message', [], 0
        async for line in lines:
            size += len(line.encode('utf-8'))
            if size > 2_000_000:
                raise AIError('upstream_format')
            if not line:
                if data:
                    self.frame(event, '\n'.join(data))
                event, data = 'message', []
            elif line.startswith('data:'):
                data.append(line[5:].removeprefix(' '))
            elif line.startswith('event:'):
                event = line[6:].strip()
        if data or not self.ended or not self.text.strip():
            raise AIError('incomplete_answer')

    def result(self, secret):
        sources, seen = [], set()
        for doc in self.docs:
            title = public_text(doc.get('doc_name') or doc.get('title'), secret, 200)
            evidence = doc.get('content')
            if not title or not isinstance(evidence, str) or not evidence.strip():
                continue
            pages = doc.get('page_number', [])
            if type(pages) is int:
                pages = [pages]
            pages = [p for p in pages if type(p) is int and 0 <= p <= 100000][:12] if isinstance(pages, list) else []
            marker = (title, tuple(pages))
            if marker in seen:
                continue
            seen.add(marker)
            sources.append({'name': title, 'positions': pages})
            if len(sources) >= 8:
                break
        grounded = bool(sources)
        text = public_text(self.text, secret) if grounded else '本次未取得可展示的知识库依据，暂时无法可靠回答。请补充问题中的具体概念，或换一个知识库覆盖的问题。'
        return Answer(text, sources, self.usage, self.request_id, grounded)


class BailianClient:
    def __init__(self, workspace, agent, key, timeout=60, transport=None):
        self.endpoint = f'https://{workspace}.cn-beijing.maas.aliyuncs.com/api/v2/apps/knowledge/chat'
        self.agent, self.key, self.timeout, self.transport = agent, key, timeout, transport

    async def ask(self, messages, request_id=None):
        state = KnowledgeStream()
        async def consume():
            async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=10), follow_redirects=False,
                                         trust_env=False, transport=self.transport) as client:
                async with client.stream('POST', self.endpoint, headers={'Authorization':'Bearer '+self.key,
                                         'Accept':'text/event-stream'}, json={
                    'input':{'messages':messages, 'request_id':request_id or str(uuid.uuid4())},
                    'parameters':{'agent_options':{'agent_id':self.agent}}, 'stream':True}) as response:
                    if response.status_code == 429:
                        raise AIError('upstream_rate_limit', 429)
                    if response.status_code in (401,403):
                        raise AIError('upstream_auth')
                    if response.status_code != 200:
                        raise AIError('upstream_error')
                    if 'text/event-stream' not in response.headers.get('content-type','').lower():
                        raise AIError('upstream_format')
                    await state.read(response.aiter_lines())
        try:
            await asyncio.wait_for(consume(), timeout=self.timeout)
        except (asyncio.TimeoutError, httpx.TimeoutException):
            raise AIError('upstream_timeout', 504) from None
        except httpx.HTTPError:
            raise AIError('upstream_network') from None
        return state.result(self.key)
