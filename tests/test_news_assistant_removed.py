"""Retired news assistant has no public/admin routes, UI or startup workers."""
import asyncio
from pathlib import Path
from unittest.mock import patch
import httpx
from backend import app as site,admin_app


def test_retired_routes_are_unavailable_and_main_routes_remain():
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=site.app),base_url='http://test') as client:
            for path in ['/api/news-agent/status','/api/news/1/agent-status','/api/news-agent/jobs/unknown','/api/news-mcp/mcp']:
                assert (await client.get(path)).status_code==404,path
            assert (await client.post('/api/news-agent/messages',json={})).status_code==404
            for path in ['/assets/news-agent.js','/assets/news-agent.css','/assets/news-agent-availability.js']:
                assert (await client.get(path)).status_code==404
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=admin_app.app),base_url='http://test') as client:
            assert (await client.get('/api/news-agent-limits')).status_code==404
            assert (await client.get('/news-limits.js')).status_code==404
            assert (await client.get('/health')).json()['status']=='ok'
            assert (await client.get('/ai-settings.js')).status_code==200
    asyncio.run(exercise())
    paths=set(site.app.openapi()['paths'])
    assert {'/api/news','/api/news/{article_id}/content','/api/ai/status'}<=paths


def test_startup_only_runs_existing_ai_and_news_jobs():
    class Runtime:
        service=object()
        async def loop(self):
            await asyncio.Event().wait()
        async def close(self):self.closed=True
    async def wait(*unused):await asyncio.Event().wait()
    runtime=Runtime()
    async def exercise():
        with patch.object(site.news,'initialize'),patch.object(site.resources.catalog,'load'),patch.object(site.ai_runtime,'startup',return_value=runtime),patch.object(site.ai,'housekeeping',wait),patch.dict('os.environ',{'COLLECT_ENABLED':'0'}):
            async with site.lifespan(site.app):
                assert site.app.state.ai is runtime.service
                assert not hasattr(site.app.state,'news_agent')
                assert not hasattr(site.app.state,'news_mcp_sdk')
            assert runtime.closed
    asyncio.run(exercise())


def test_frontend_has_no_agent_mount_or_polling_and_keeps_paper_entry():
    for name in ['web/index.html','web/news-ui.js','web/news-reader.js','admin_web/index.html','web/styles/pages.css']:
        text=Path(name).read_text(encoding='utf-8')
        for term in ['news-agent','newsAgentAvailability','新闻科普','reader-assistant','reader-split','news-limits.js']:
            assert term not in text,(name,term)
    assert '/reader/?news=' in Path('web/news-reader.js').read_text(encoding='utf-8')
    assert 'if (canRead)' in Path('web/news-ui.js').read_text(encoding='utf-8')
