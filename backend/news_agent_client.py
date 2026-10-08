"""DashScope application completion SSE, separate from knowledge/chat."""
import asyncio
import json
import re
from dataclasses import dataclass

import httpx

from .bailian import AIError, public_text

BASES = {'beijing': 'https://dashscope.aliyuncs.com',
         'singapore': 'https://dashscope-intl.aliyuncs.com'}


@dataclass
class NewsAnswer:
    text: str
    session_id: str
    references: list
    usage: dict | None
    request_id: str | None


class ApplicationStream:
    def __init__(self, incremental=True):
        self.incremental = incremental
        self.text, self.session, self.request_id = '', '', None
        self.ended, self.frames, self.usage, self.references = False, 0, None, []

    def frame(self, event, payload):
        self.frames += 1
        if self.frames > 10000:
            raise AIError('upstream_format')
        if payload.strip() == '[DONE]':
            return  # Transport sentinel cannot prove a complete answer.
        try:
            data = json.loads(payload)
            if not isinstance(data, dict):
                raise ValueError()
            if event == 'error' or data.get('code') not in (None, '', 200, '200'):
                code = str(data.get('code', '')).lower()
                raise AIError('upstream_session_expired' if 'session' in code else 'upstream_error')
            output = data.get('output', {})
            if not isinstance(output, dict):
                raise ValueError()
            # Never consume thoughts, planning, tool payloads, or unknown choices formats.
            text = output.get('text', '')
            if not isinstance(text, str):
                raise ValueError()
            if self.ended and text:
                raise AIError('upstream_format')
            self.text = self.text + text if self.incremental else text or self.text
            if len(self.text) > 16000:
                raise AIError('answer_too_long')
            session = output.get('session_id')
            if session:
                if not isinstance(session, str) or len(session) > 256 or self.session and session != self.session:
                    raise ValueError()
                self.session = session
            finish = output.get('finish_reason')
            if finish == 'stop':
                self.ended = True
            elif finish not in (None, '', 'null'):
                raise AIError('incomplete_answer')
            if data.get('usage'):
                usage = data['usage']
                if not isinstance(usage, dict):
                    raise ValueError()
                models = usage.get('models', [])
                if not isinstance(models, list):
                    raise ValueError()
                total = usage.get('total_tokens')
                if total is None and models:
                    total = sum(model.get('input_tokens', 0) + model.get('output_tokens', 0) for model in models)
                if total is not None and (type(total) is not int or total < 0):
                    raise ValueError()
                self.usage = {'total_tokens': total}
            references = output.get('doc_references') or []
            if not isinstance(references, list):
                raise ValueError()
            # Agent 2.0 documents this legacy field as null. Empty is expected and
            # does not prove retrieval failure; textual citations need separate validation.
            # Preserve unexpected structured IDs for diagnosis; never publish URLs/content.
            for ref in references[:100]:
                if isinstance(ref, dict) and ref not in self.references:
                    self.references.append(ref)
            request_id = data.get('request_id')
            if request_id:
                if not isinstance(request_id, str) or len(request_id) > 256:
                    raise ValueError()
                self.request_id = request_id
        except (ValueError, TypeError, KeyError, AttributeError):
            raise AIError('upstream_format') from None

    def result(self, key):
        if not self.ended or not self.text.strip() or not self.session:
            raise AIError('incomplete_answer')
        return NewsAnswer(public_text(self.text, key, maximum=16000), self.session,
                          self.references, self.usage, self.request_id)


class NewsAgentClient:
    def __init__(self, app_id, key, workspace='', region='beijing', timeout=90, incremental=True, transport=None, frame_observer=None):
        if region not in BASES or not re.fullmatch(r'[a-f0-9]{32}', app_id):
            raise ValueError('Invalid application configuration')
        if workspace and not re.fullmatch(r'[A-Za-z0-9-]{1,100}', workspace):
            raise ValueError('Invalid workspace')
        self.url = BASES[region] + '/api/v1/apps/' + app_id + '/completion'
        self.key, self.workspace, self.timeout = key, workspace, timeout
        self.incremental, self.transport = incremental, transport
        self.frame_observer = frame_observer

    async def ask(self, prompt, session_id=None, tool_context=None):
        payload = {'input': {'prompt': prompt}, 'parameters': {'incremental_output': self.incremental}}
        if session_id:
            payload['input']['session_id'] = session_id
        if tool_context:
            # MCP header pass-through uses user_defined_params keyed by service ID.
            # This trusted mapping is separate from the model's prompt/tool arguments.
            payload['input']['biz_params'] = {'user_defined_params': tool_context}
        headers = {'Authorization': 'Bearer ' + self.key, 'X-DashScope-SSE': 'enable',
                   'Accept': 'text/event-stream'}
        if self.workspace:
            headers['X-DashScope-WorkSpace'] = self.workspace
        state = ApplicationStream(self.incremental)
        try:
            async with asyncio.timeout(self.timeout):
                async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport, trust_env=False) as client:
                    async with client.stream('POST', self.url, json=payload, headers=headers) as reply:
                        if reply.status_code != 200:
                            code = {401: 'upstream_auth', 403: 'upstream_auth', 429: 'upstream_rate_limit'}.get(reply.status_code, 'upstream_error')
                            raise AIError(code)
                        if 'text/event-stream' not in reply.headers.get('content-type', ''):
                            raise AIError('upstream_format')
                        event, lines, size = 'message', [], 0
                        async for line in reply.aiter_lines():
                            size += len(line.encode())
                            if size > 2_000_000 or len(line) > 200000:
                                raise AIError('upstream_format')
                            if not line:
                                if lines:
                                    payload_text = '\n'.join(lines)
                                    if self.frame_observer:
                                        self.frame_observer(event, payload_text)
                                    state.frame(event, payload_text)
                                event, lines = 'message', []
                            elif line.startswith('event:'):
                                event = line[6:].lstrip()
                            elif line.startswith('data:'):
                                lines.append(line[5:].lstrip(' '))
                        # A missing frame delimiter is an interrupted stream, even with stop in its buffer.
                        if lines:
                            raise AIError('incomplete_answer')
            return state.result(self.key)
        except (TimeoutError, httpx.TimeoutException):
            raise AIError('upstream_timeout', 504) from None
        except httpx.HTTPError:
            raise AIError('upstream_network') from None
