"""Manual server-only knowledge-chat probe. No key file, website changes or retries."""
import argparse
import asyncio
import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path

DEFAULT_WORKSPACE = 'llm-ep9bqc9mnw50k8e0'
DEFAULT_AGENT = 'aid-066ddd0b6e1e44d6bf7d620e0ac7c060'


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    path.chmod(0o600)


def sanitize(value, secret=''):
    """Remove URLs entirely, credential-like fields and the exact API key."""
    if isinstance(value, dict):
        return {key: '[redacted]' if re.search(r'key|token|authorization|password|secret|url|uri', key, re.I)
                and key not in ('input_tokens', 'output_tokens', 'total_tokens', 'cached_tokens')
                else sanitize(item, secret) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize(item, secret) for item in value]
    if isinstance(value, str):
        if secret:
            value = value.replace(secret, '[redacted]')
        return re.sub(r'https?://[^\s<>"\)]+', '[url withheld]', value)
    return value


class ProbeStream:
    def __init__(self):
        self.answer = ''
        self.answer_chunks = []
        self.tool_returns = []
        self.trace = []
        self.docs = []
        self.calls = {}
        self.usage = None
        self.usage_frames = []
        self.request_ids = set()
        self.ended = False
        self.error = None
        self.events = 0
        self.bytes = 0

    def event(self, name, data):
        self.events += 1
        if self.events > 20000:
            raise ValueError('event_limit')
        if data.strip() == '[DONE]':
            self.trace.append({'event': 'DONE'})
            return  # DONE alone is not a verified generation_end.
        payload = json.loads(data)
        if not isinstance(payload, dict):
            raise ValueError('invalid_event_object')
        if payload.get('request_id'):
            self.request_ids.add(str(payload['request_id']))
        if name == 'error' or str(payload.get('code', '200')) != '200':
            self.error = {'type': 'business_error', 'code': str(payload.get('code', 'unknown'))[:100]}
            return
        choices = payload.get('output', {}).get('choices', [])
        if not isinstance(choices, list):
            raise ValueError('invalid_choices')
        for choice in choices:
            message = choice.get('message', {})
            extra = message.get('extra') or {}
            step, change = extra.get('step'), extra.get('step_change')
            role = message.get('role')
            for call in message.get('tool_calls') or []:
                function = call.get('function', {})
                self.calls[call.get('id')] = {'name': function.get('name'), 'arguments': function.get('arguments')}
            kwargs = message.get('additional_kwargs') or {}
            tool_data = kwargs.get('extra_json') or {}
            if isinstance(tool_data, str):
                tool_data = json.loads(tool_data)
            docs = tool_data.get('docs', []) if isinstance(tool_data, dict) else []
            if not isinstance(docs, list):
                raise ValueError('invalid_docs')
            if role == 'tool' and docs:
                self.docs.append({'tool_call_id': message.get('tool_call_id'), 'docs': docs})
            if role == 'tool':
                self.tool_returns.append({'tool_call_id': message.get('tool_call_id'), 'content': message.get('content')})
            if step == 'generating' and role == 'assistant':
                content = message.get('content', '')
                if isinstance(content, list):
                    content = ''.join(part.get('text', '') for part in content if part.get('type') == 'text')
                if not isinstance(content, str):
                    raise ValueError('invalid_answer_content')
                # Keep chunks for verification; delta vs cumulative is checked using real samples.
                self.answer += content
                self.answer_chunks.append(content)
                if len(self.answer) > 100000:
                    raise ValueError('answer_limit')
            finish = choice.get('finish_reason') or (message.get('response_metadata') or {}).get('finish_reason')
            self.trace.append({'event': name, 'role': role, 'step': step, 'change': change,
                               'finish_reason': finish, 'content_chars': len(str(message.get('content', ''))),
                               'tool_call_id': message.get('tool_call_id'),
                               'message_keys': sorted(message), 'extra_keys': sorted(extra)})
            if change == 'generation_end' and step == 'generating' and finish == 'stop':
                self.ended = True
                self.usage = payload.get('usage')
        if payload.get('usage') is not None:
            self.usage_frames.append(payload['usage'])  # Do not sum intermediate snapshots.

    async def read(self, lines):
        data, name = [], 'message'
        async for line in lines:
            self.bytes += len(line.encode('utf-8'))
            if self.bytes > 4_000_000:
                raise ValueError('stream_limit')
            if line == '':
                if data:
                    self.event(name, '\n'.join(data))
                data, name = [], 'message'
                if self.error:
                    return
            elif line.startswith(':'):
                continue
            elif line.startswith('data:'):
                data.append(line[5:].removeprefix(' '))
            elif line.startswith('event:'):
                name = line[6:].strip()
        if data:
            raise ValueError('unframed_eof')

    def summary(self):
        docs = [doc for group in self.docs for doc in group['docs']]
        indexes = [str(doc['_citation_index']) for doc in docs if isinstance(doc, dict) and '_citation_index' in doc]
        numeric = re.findall(r'\[(\d+)\]', self.answer)
        return {
            'transport_complete': bool(self.ended and not self.error),
            'error': self.error, 'answer_chars': len(self.answer),
            'generation_end_seen': self.ended, 'sse_events': self.events,
            'request_ids': sorted(self.request_ids), 'final_usage': self.usage,
            'usage_frame_count': len(self.usage_frames),
            'tool_names': sorted({str(call['name']) for call in self.calls.values()}),
            'doc_count': len(docs), 'doc_field_sets': sorted({','.join(sorted(doc)) for doc in docs if isinstance(doc, dict)}),
            'tool_returns_have_matching_call': all(group['tool_call_id'] in self.calls for group in self.docs) if self.docs else None,
            'doc_citation_indexes': indexes, 'simple_bracket_candidates': numeric,
            'bracket_candidates_without_matching_index': sorted(set(numeric) - set(indexes)),
            'semantic_support': 'not_automatically_verified',
            'citation_format': 'requires_manual_confirmation_from_private_detail',
        }


def prepare(path):
    if path.exists():
        raise ValueError('questions_file_exists')
    question = input('输入一个你在百炼控制台确认知识库能回答的问题：\n> ').strip()
    if not 1 <= len(question) <= 1500:
        raise ValueError('question_length')
    cases = [
        {'name': 'supported', 'question': question, 'history_from': None},
        {'name': 'paraphrase', 'question': '请用适合初学者的语言解释这个问题，并保留知识库依据：' + question, 'history_from': None},
        {'name': 'followup', 'question': '你刚才的解释最需要注意什么适用条件？请依据同一知识库说明，不要补写资料没有提供的参数。', 'history_from': 'supported'},
        {'name': 'missing', 'question': '请给出虚构的“ZX-QA-不存在-20261006”发动机的实测比冲、测试日期和资料出处。若知识库没有该型号依据，请明确说明，不能推测数值。', 'history_from': None},
    ]
    write_json(path, {'cases': cases})
    print('已准备4个用例；默认只调用第1个。问题文件仅留服务器。')


async def run(args):
    import httpx  # Use the app container's installed dependency, never install on the server.
    secret = os.environ.get('DASHSCOPE_API_KEY', '').strip()
    if not secret:
        raise ValueError('missing_DASHSCOPE_API_KEY')
    workspace = os.environ.get('BAILIAN_WORKSPACE_ID', DEFAULT_WORKSPACE)
    agent = os.environ.get('BAILIAN_AGENT_ID', DEFAULT_AGENT)
    if not re.fullmatch(r'[a-zA-Z0-9-]+', workspace) or not re.fullmatch(r'aid-[a-zA-Z0-9-]+', agent):
        raise ValueError('invalid_service_identifiers')
    endpoint = f'https://{workspace}.cn-beijing.maas.aliyuncs.com/api/v2/apps/knowledge/chat'
    document = json.loads(args.questions.read_text(encoding='utf-8'))
    cases = document['cases'][:args.max_requests]
    if not cases or len(cases) > 4:
        raise ValueError('invalid_cases')
    for case in cases:
        if not isinstance(case['question'], str) or not 1 <= len(case['question']) <= 1800:
            raise ValueError('question_length')
        if case.get('history_from') not in (None, 'supported'):
            raise ValueError('invalid_history_reference')
    args.output.mkdir(parents=True, exist_ok=False)
    args.output.chmod(0o700)
    report = {'service': {'workspace': workspace, 'agent': agent}, 'attempted_requests': 0,
              'results': [], 'overall': 'requires_manual_review',
              'warning': 'API success and returned documents do not prove factual support or correct knowledge-base binding.'}
    history = {}
    async with httpx.AsyncClient(follow_redirects=False, trust_env=False,
                                 timeout=httpx.Timeout(15, connect=10)) as client:
        for case in cases:
            state = ProbeStream()
            messages = list(history.get(case.get('history_from'), []))
            messages.append({'role': 'user', 'content': case['question']})
            business_id = str(uuid.uuid4())
            body = {'input': {'messages': messages, 'request_id': business_id},
                    'parameters': {'agent_options': {'agent_id': agent}}, 'stream': True}
            start = time.monotonic()
            report['attempted_requests'] += 1
            http_status = None

            async def consume():
                nonlocal http_status
                async with client.stream('POST', endpoint, headers={'Authorization': 'Bearer ' + secret,
                                         'Accept': 'text/event-stream'}, json=body) as response:
                    http_status = response.status_code
                    if http_status != 200:
                        state.error = {'type': 'http_error', 'http_status': http_status}
                        return  # Do not log upstream body or retry a charged POST.
                    if 'text/event-stream' not in response.headers.get('content-type', '').lower():
                        state.error = {'type': 'unexpected_content_type'}
                        return
                    await state.read(response.aiter_lines())

            try:
                await asyncio.wait_for(consume(), timeout=args.timeout)
                if not state.ended and not state.error:
                    state.error = {'type': 'missing_generation_end'}
                elif not state.answer.strip() and not state.error:
                    state.error = {'type': 'empty_answer'}
            except (asyncio.TimeoutError, httpx.TimeoutException):
                state.error = {'type': 'timeout', 'upstream_billing': 'unknown'}
            except httpx.HTTPError:
                state.error = {'type': 'network_error', 'upstream_billing': 'unknown'}
            except (ValueError, TypeError, AttributeError, KeyError):
                state.error = {'type': 'response_protocol_error', 'upstream_billing': 'unknown'}
            result = state.summary()
            result.update({'case': case['name'], 'business_request_id': business_id, 'http_status': http_status,
                           'elapsed_seconds': round(time.monotonic() - start, 2), 'history_messages': len(messages) - 1})
            report['results'].append(sanitize(result, secret))
            detail = {'question': case['question'], 'answer': state.answer, 'answer_usable': result['transport_complete'],
                      'generation_chunks': state.answer_chunks, 'tool_returns': state.tool_returns,
                      'trace': state.trace, 'tool_calls': state.calls, 'tool_docs': state.docs,
                      'usage_frames_not_summed': state.usage_frames}
            write_json(args.output / (case['name'] + '-private.json'), sanitize(detail, secret))
            write_json(args.output / 'summary.json', report)
            print(json.dumps(sanitize(result, secret), ensure_ascii=False), flush=True)
            if not result['transport_complete']:
                print('已停止；未自动重试，未调用剩余问题。', flush=True)
                return 1
            history[case['name']] = messages + [{'role': 'assistant', 'content': state.answer}]
    print('探测完成；请人工对照控制台答案、知识库绑定和引用。', flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', type=Path)
    parser.add_argument('--live', action='store_true', help='Explicitly enable charged calls')
    parser.add_argument('--questions', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--max-requests', type=int, choices=(1, 4), default=1)
    parser.add_argument('--timeout', type=int, default=60)
    args = parser.parse_args()
    try:
        if args.prepare:
            prepare(args.prepare)
            return 0
        if not args.live or not args.questions or not args.output or not 5 <= args.timeout <= 180:
            parser.error('Live calls require --live --questions --output; timeout must be 5..180')
        return asyncio.run(run(args))
    except (ValueError, OSError, KeyError, ImportError) as error:
        # Never print exception strings: they can contain credentials or upstream text.
        print('准备/配置失败：' + type(error).__name__ + '。检查密钥环境变量、问题文件、输出目录和容器依赖。')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
