"""Private ASGI acceptance using real Agent 2.0 and shared ledger, public switch stays off."""
import argparse
import asyncio
import json
import uuid
from dataclasses import replace
from pathlib import Path

import httpx
from fastapi import FastAPI

from backend import ai, ai_config, management_store, news_agent
from backend.bailian import AIError, public_text
from backend.news_agent_client import NewsAgentClient
from backend.news_context_store import Store


def sanitize_receipts(value, key, private_values):
    if isinstance(value,str):
        value = public_text(value,key,300)
        for private in private_values:
            if private:
                value = value.replace(private,'[已隐藏]')
        return value
    if isinstance(value,list):
        return [sanitize_receipts(item,key,private_values) for item in value]
    if isinstance(value,dict):
        return {name:sanitize_receipts(item,key,private_values) for name,item in value.items()}
    return value


async def run(args):
    settings = news_agent.Settings.environment()
    limits = ai.Settings.environment()
    if ai_config.tables_exist():
        with management_store.connection() as db:
            state = ai_config.state(db)
            limits = ai_config.load(ai_config.version(db, state['desired_version']), limits, state['desired_compat'])
    if settings.enabled or limits.enabled or not settings.key:
        raise AIError('configuration')
    report = {'mode':'backend_inline_context', 'mcp_verified':False, 'public_generation_enabled':False,
              'article_id':args.article_id, 'paid_calls':0, 'samples':[]}
    if not args.call:
        print(json.dumps(report)); return
    budget = ai.AIService(replace(limits, enabled=False, token_reservation=max(60000, limits.token_reservation)))
    with budget.connection() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='requests'").fetchone():
            raise AIError('storage')
        if db.execute("SELECT 1 FROM requests WHERE status='pending'").fetchone():
            raise AIError('capacity')
    budget.initialized = True
    schemas = set()
    receipts = []
    private_values = {settings.mcp_key,settings.workspace}
    def observe(event, payload):
        if not args.inspect_trace:
            return
        try:
            output = json.loads(payload).get('output') or {}
            if isinstance(output.get('session_id'),str):
                private_values.add(output['session_id'])
            thoughts = output.get('thoughts') or []
            for thought in thoughts:
                if isinstance(thought, dict):
                    # Shape only: never log planning text, tool payloads, or signed URLs.
                    schemas.add(json.dumps({name:type(value).__name__ for name,value in thought.items()},sort_keys=True))
                    receipt = {name:thought[name][:120] for name in ('action_name','action_type')
                               if isinstance(thought.get(name),str)}
                    observation = thought.get('observation')
                    if isinstance(observation,str) and observation:
                        try:
                            value = json.loads(observation)
                            receipt['observation_format'] = 'json'
                            def walk(node,depth=0):
                                if depth > 8:
                                    return []
                                found = []
                                if isinstance(node,dict):
                                    fields = {name:node[name] for name in ('doc_id','doc_name','document_id','document_name')
                                              if isinstance(node.get(name),str) and len(node[name]) <= 300
                                              and '://' not in node[name]}
                                    if fields:
                                        found.append(fields)
                                    for child in node.values():
                                        found.extend(walk(child,depth+1))
                                elif isinstance(node,list):
                                    for child in node[:100]:
                                        found.extend(walk(child,depth+1))
                                return found[:100]
                            receipt['document_metadata'] = walk(value)
                            receipt['observation_fields'] = list(value)[:40] if isinstance(value,dict) else type(value).__name__
                        except (ValueError,TypeError):
                            receipt['observation_format'] = 'non_json'
                        if receipt not in receipts:
                            receipts.append(receipt)
        except (ValueError,AttributeError,TypeError):
            pass
    provider = NewsAgentClient(settings.app_id, settings.key, settings.workspace, settings.region, timeout=120,
                               frame_observer=observe,has_thoughts=args.inspect_trace)
    class ObservedClient:
        async def ask(self, prompt, session=None, tool_context=None):
            report['paid_calls'] += 1
            report['samples'][-1].update(session_supplied=bool(session), tool_mapping_supplied=bool(tool_context))
            answer = await provider.ask(prompt, session, tool_context)
            report['samples'][-1]['usage'] = answer.usage
            return answer
    service = news_agent.NewsAgentService(replace(settings, enabled=True, mcp_enabled=False, mcp_verified=False, timeout=120),
        budget, Store(Path('/data/news-agent-inline-acceptance.sqlite3')), client=ObservedClient())
    if service.problem:
        raise AIError(service.problem)
    app = FastAPI(); app.state.news_agent = service; app.include_router(news_agent.router)
    transport = httpx.ASGITransport(app=app, client=('127.0.0.1',0))
    base = 'https://8.137.164.100:8080'
    try:
        async with httpx.AsyncClient(transport=transport,base_url=base,headers={'Origin':base}) as client:
            reply = await client.post(f'/api/news/{args.article_id}/conversations'); reply.raise_for_status()
            conversation = reply.json()['conversation_id']
            questions = [args.prompt or '请用两句话说明这篇新闻报道的事件和计划时间，并引用正文块编号。']
            if args.follow_up:
                questions.append('上文提到的飞船叫什么？请依据当前新闻回答，并引用正文块编号。')
            for question in questions:
                report['samples'].append({'session_supplied':False,'tool_mapping_supplied':False})
                body = {'conversation_id':conversation,'request_id':str(uuid.uuid4()),'question':question}
                reply = await client.post('/api/news-agent/messages',json=body); reply.raise_for_status()
                job = reply.json()['job_id']
                duplicate = await client.post('/api/news-agent/messages',json=body)
                if duplicate.status_code != 202 or duplicate.json()['job_id'] != job:
                    raise AIError('request_conflict')
                await asyncio.gather(*tuple(service.tasks))
                result = await client.get('/api/news-agent/jobs/' + job); result.raise_for_status()
                value = result.json()
                report['samples'][-1].update(stage=value['stage'], result=value['result'], error=value['error'],
                                             repeated_request_same_job=True)
                if value['stage'] != 'complete':
                    break
            history = await client.get('/api/news-agent/conversations/' + conversation)
            report['history_jobs'] = len(history.json().get('jobs',[]))
            # A second anonymous visitor must not read this private answer.
            async with httpx.AsyncClient(transport=transport,base_url=base) as stranger:
                report['other_visitor_blocked'] = (await stranger.get('/api/news-agent/jobs/' + job)).status_code == 404
        if args.inspect_trace:
            report['thought_field_schemas'] = [json.loads(value) for value in sorted(schemas)]
            report['tool_observation_receipts'] = sanitize_receipts(receipts,settings.key,private_values)
        path = Path(args.output); path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        summary = {key:value for key,value in report.items() if key != 'samples'}
        summary['samples'] = [{key:value for key,value in sample.items() if key != 'result'} for sample in report['samples']]
        print(json.dumps(summary,ensure_ascii=False))
    finally:
        await service.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--call',action='store_true')
    parser.add_argument('--follow-up',action='store_true')
    parser.add_argument('--article-id',type=int,default=362)
    parser.add_argument('--prompt')
    parser.add_argument('--inspect-trace',action='store_true')
    parser.add_argument('--output',default='/data/news-agent-inline-probe.json')
    args = parser.parse_args()
    if args.prompt is not None and not 1 <= len(args.prompt.strip()) <= 1500:
        parser.error('Prompt must contain 1-1500 characters')
    try:
        asyncio.run(run(args))
    except Exception:
        raise SystemExit('Private probe failed; no credentials printed. Check protected server state.') from None


if __name__ == '__main__': main()
