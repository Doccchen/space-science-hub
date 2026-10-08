"""Isolated browser preview with fixture bodies and a fake, clearly labelled model."""
import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

import uvicorn
from cryptography.fernet import Fernet

from backend import ai, news, news_agent
from backend.app import app
from backend.html_sources import parse_detail
from backend.news_agent_client import NewsAnswer
from backend.news_context_store import Store

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'artifacts/news-agent-preview'
DATA.mkdir(parents=True, exist_ok=True)
news.DB_PATH = DATA / 'news.sqlite3'
FIXTURES = ROOT / 'tests/fixtures'
manifest = json.loads((FIXTURES / 'manifest.json').read_text(encoding='utf-8'))
raw = (FIXTURES / 'cnsa/detail-0.html').read_bytes()


class PreviewClient:
    async def ask(self, prompt, session=None, tool_context=None):
        return NewsAnswer('本地离线预览 · 此回答来自固定测试样例，未调用百炼。\n\n'
                          '新闻记载：2026年9月20日，力箭一号遥十八成功发射9颗卫星。[b0001]\n\n'
                          '模型补充背景（本预览未检索知识库）：一箭多星需要在入轨后按预定顺序释放卫星。'
                          '这类任务通常涉及载荷适配和分离控制；原文未逐项说明本次任务的技术难点。',
                          'preview-session', [], {'total_tokens': 0}, 'offline-preview')


@asynccontextmanager
async def lifespan(application):
    news.initialize()
    record = parse_detail('cnsa', raw, {'url': manifest['cnsa']['details'][0]['url']})
    news.store_records([record])
    with news.connect() as db:
        db.execute("UPDATE sources SET enabled=1 WHERE id='cnsa'")
    budget = ai.AIService(ai.Settings(db=DATA / 'ai.sqlite3'))
    budget.ensure_storage()
    service = news_agent.NewsAgentService(news_agent.Settings(enabled=True, context_enabled=True, key='offline-preview'),
                                         budget, Store(DATA / 'news-agent.sqlite3'), PreviewClient(), Fernet(Fernet.generate_key()))
    application.state.ai = budget
    application.state.news_agent = service
    with patch('backend.news_context.Publisher.get', return_value=(raw, 'text/html')):
        yield
    await service.close()


app.router.lifespan_context = lifespan
if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=8769, log_level='warning')
