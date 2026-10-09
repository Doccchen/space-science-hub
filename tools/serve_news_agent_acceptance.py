"""Ephemeral SSH-only real browser acceptance. Never run on a public host binding."""
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
import json
import os

import uvicorn

from backend import ai, ai_config, management_store, news_agent, resources
from backend.app import app
from backend.bailian import AIError
from backend.news_context_store import Store
from tools.probe_news_agent import redact_frame, redact_stream_text


@asynccontextmanager
async def lifespan(application):
    settings, limits = news_agent.Settings.environment(), ai.Settings.environment()
    if ai_config.tables_exist():
        with management_store.connection() as db:
            state = ai_config.state(db)
            limits = ai_config.load(ai_config.version(db,state['desired_version']),limits,state['desired_compat'])
    if settings.enabled or limits.enabled or not settings.key:
        raise RuntimeError('Public generation must be off for private acceptance')
    budget = ai.AIService(replace(limits,enabled=False,concurrency=1,secure_cookie=False,token_reservation=max(60000,limits.token_reservation)))
    with budget.connection() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='requests'").fetchone() or db.execute("SELECT 1 FROM requests WHERE status='pending'").fetchone():
            raise RuntimeError('Existing idle ledger required')
    budget.initialized = True
    reserve = budget.reserve_news
    private_store = Store(Path('/data/news-agent-browser-acceptance.sqlite3'))
    with private_store.connection() as db:
        attempts = db.execute('SELECT COUNT(*) FROM news_agent_jobs').fetchone()[0]
    def bounded_reserve(*args):
        nonlocal attempts
        if attempts >= 2:
            raise AIError('daily_limit',429)
        result = reserve(*args)
        attempts += 1
        return result
    budget.reserve_news = bounded_reserve
    instance = news_agent.NewsAgentService(replace(settings,enabled=True,context_enabled=True,mcp_enabled=False,
        mcp_verified=False,secure_cookie=False,timeout=120),budget,private_store)
    if instance.problem:
        raise RuntimeError('Private acceptance configuration failed')
    resources.catalog.load()
    frames, private_values = [], {settings.mcp_key,settings.workspace}
    stream_ended = False
    def observe(event,payload):
        nonlocal stream_ended
        if stream_ended:
            frames.clear()
            stream_ended = False
        try:
            output = json.loads(payload).get('output') or {}
            if isinstance(output.get('session_id'),str):
                private_values.add(output['session_id'])
            frame = redact_frame(event,payload,settings.key,private_values)
            frame['tool_observations'] = []
            for thought in output.get('thoughts') or []:
                if isinstance(thought,dict) and thought.get('action_name') == 'search_knowledgebases' and thought.get('action_type') == 'api' and thought.get('observation'):
                    try:
                        value = json.loads(thought['observation'])
                    except (ValueError,TypeError):
                        continue
                    if isinstance(value,dict):
                        index = value.get('call_index')
                        frame['tool_observations'].append({'action_name':'search_knowledgebases',
                            'call_index':index if type(index) is int else None,'has_nodes':bool(value.get('nodes'))})
            frames.append(frame)
            if output.get('finish_reason') == 'stop':
                redact_stream_text(frames,settings.key,private_values)
                Path('/data/news-browser-stream.json').write_text(json.dumps(frames,ensure_ascii=False),encoding='utf-8')
                stream_ended = True
        except (ValueError,TypeError,AttributeError):
            pass
    instance.client.frame_observer = observe
    application.state.ai, application.state.news_agent = budget, instance
    try:
        yield
    finally:
        await instance.close()


app.router.lifespan_context = lifespan


@app.middleware('http')
async def private_notice(request, call_next):
    response = await call_next(request)
    if request.url.path == '/' and response.status_code == 200:
        # Mark the real website without changing its served assets or product flow.
        response.headers['X-News-Acceptance'] = 'private-real-model-max-two-calls'
    return response


if __name__ == '__main__':
    container = os.getenv('NEWS_BROWSER_ACCEPTANCE_CONTAINER') == '1' and Path('/.dockerenv').is_file()
    uvicorn.run(app,host='0.0.0.0' if container else '127.0.0.1',port=8769,log_level='warning',access_log=False)
