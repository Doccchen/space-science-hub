"""Operator-only, opt-in application probe. Default checks configuration without calls."""
import argparse
import asyncio
import json
from pathlib import Path

from backend.bailian import AIError, public_text
from backend.news_agent import Settings
from backend.news_agent_client import NewsAgentClient


def redact_frame(event, payload, key, private_values=()):
    if payload.strip() == '[DONE]':
        return {'event': event, 'data': '[DONE]'}
    try:
        data = json.loads(payload)
        output = data.get('output') or {}
        private = [value for value in (*private_values, output.get('session_id')) if isinstance(value, str) and value]
        def clean(value, maximum=16000):
            value = public_text(value, key, maximum)
            for secret in private:
                value = value.replace(secret, '[已隐藏]')
            return value
        code = data.get('code')
        sample = {'event': event, 'data': {'code': clean(code, 100) if isinstance(code, str) else code, 'output': {}}}
        result = sample['data']['output']
        for name in ('text', 'finish_reason'):
            if isinstance(output.get(name), str):
                result[name] = clean(output[name])
        if output.get('session_id'):
            result['session_id'] = 'sample-session'
        references = output.get('doc_references') or []
        result['doc_references'] = [{name: clean(ref[name], 300) for name in ('doc_id', 'doc_name', 'index') if name in ref}
                                    for ref in references[:100] if isinstance(ref, dict)]
        sample['reference_fields'] = [{name: type(value).__name__ for name, value in ref.items()}
                                      for ref in references[:100] if isinstance(ref, dict)]
        sample['has_thoughts'] = bool(output.get('thoughts'))
        sample['output_fields'] = {name: type(value).__name__ for name, value in output.items()}
        usage = data.get('usage') or {}
        sample['data']['usage'] = {'models': [{name: model[name] for name in ('input_tokens', 'output_tokens') if type(model.get(name)) is int}
                                             for model in usage.get('models', []) if isinstance(model, dict)]}
        return sample
    except (ValueError, TypeError, AttributeError):
        return {'event': event, 'malformed': True}


async def run(args):
    if args.prompt is not None and (not args.prompt.strip() or len(args.prompt) > 1500):
        raise AIError('invalid_prompt', 422)
    settings = Settings.environment()
    report = {'application_id': settings.app_id, 'workspace': settings.workspace, 'region': settings.region,
              'key_configured': bool(settings.key), 'paid_calls': 0, 'scope': 'application_api_probe_only', 'samples': []}
    if args.call:
        if not settings.key:
            raise AIError('configuration')
        frames = []
        private_sessions = set()
        def observe(event, payload):
            try:
                session_id = (json.loads(payload).get('output') or {}).get('session_id')
                if isinstance(session_id, str) and session_id:
                    private_sessions.add(session_id)
            except (ValueError, AttributeError):
                pass
            frames.append(redact_frame(event, payload, settings.key, private_sessions))
        client = NewsAgentClient(settings.app_id, settings.key, settings.workspace, settings.region,
                                 frame_observer=observe)
        session = None
        first_question = args.prompt.strip() if args.prompt else '请简要介绍航天任务中“一箭多星”的基本含义。'
        follow_up = '请继续解释上文涉及的关键原理，并区分检索依据与补充背景。' if args.prompt else '上述概念中，卫星分离通常需要考虑什么？'
        for question in [first_question] + ([follow_up] if args.follow_up else []):
            report['paid_calls'] += 1
            error = None
            try:
                answer = await client.ask(question, session)
                session = answer.session_id
                outcome = {'complete': True, 'reference_count': len(answer.references), 'usage': answer.usage}
            except AIError as failure:
                error = failure.code
                outcome = {'complete': False, 'error': error}
            report['samples'].append({**outcome, 'frames': frames.copy()}); frames.clear()
            if error:
                break  # No automatic retry of a potentially charged call.
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key != 'samples'}, ensure_ascii=False))
    return 0 if all(sample['complete'] for sample in report['samples']) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--call', action='store_true', help='Explicitly make one potentially paid model call')
    parser.add_argument('--follow-up', action='store_true', help='Make one additional call using the returned session')
    parser.add_argument('--prompt', help='Use a specific non-sensitive test question, up to 1500 characters')
    parser.add_argument('--output', help='Save local redacted protocol evidence')
    args = parser.parse_args()
    try:
        return asyncio.run(run(args))
    except (AIError, ValueError) as error:
        print(json.dumps({'error': error.code if isinstance(error, AIError) else 'configuration'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
