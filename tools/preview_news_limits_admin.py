"""Isolated loopback administrator UI fixture; no real keys or network calls."""
import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

import uvicorn

from backend import admin_auth,ai,ai_config,ai_runtime,news,news_agent,news_limits
from backend.admin_app import app
from backend.news_context_store import Store

ROOT=Path(__file__).resolve().parents[1]/'artifacts/news-limits-admin-preview'
ROOT.mkdir(parents=True,exist_ok=True)
news.DB_PATH=ROOT/'news.sqlite3'
os.environ.update(MANAGEMENT_DB_PATH=str(ROOT/'management.sqlite3'),AI_DB_PATH=str(ROOT/'ai.sqlite3'),
    NEWS_AGENT_USAGE_DB_PATH=str(ROOT/'news-usage.sqlite3'),AI_MASTER_KEY_FILE=str(ROOT/'master.key'),ADMIN_ORIGIN='http://127.0.0.1:8771')


@asynccontextmanager
async def lifespan(application):
    news.initialize();admin_auth.initialize_user('preview','news-limits-preview-only')
    if not (ROOT/'master.key').exists():ai_config.generate_key(ROOT/'master.key')
    general=ai.AIService(ai.Settings(db=ROOT/'ai.sqlite3'))
    ai_config.initialize(general.settings);news_limits.initialize()
    budget=news_limits.budget(initialize=True);budget.ensure_storage()
    service=news_agent.NewsAgentService(news_agent.Settings(context_enabled=True),budget,Store(ROOT/'agent.sqlite3'))
    runtime=ai_runtime.Runtime(general)
    async def update():
        while True:
            runtime.sync();news_limits.sync(service);await asyncio.sleep(1)
    task=asyncio.create_task(update())
    with patch('backend.bailian.BailianClient.ask',side_effect=RuntimeError('Preview forbids network')),patch('backend.news_agent_client.NewsAgentClient.ask',side_effect=RuntimeError('Preview forbids network')):
        try:yield
        finally:
            task.cancel();await asyncio.gather(task,return_exceptions=True);await service.close()


app.router.lifespan_context=lifespan
if __name__=='__main__':uvicorn.run(app,host='127.0.0.1',port=8771,log_level='warning')
