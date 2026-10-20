"""News-to-paper search service, sharing the existing /reader/ entry."""
import asyncio
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .config import Settings
from .discovery import SearchService, plan
from .provider_runtime import Runtime

ROOT = Path(__file__).resolve().parent.parent


class Analysis(BaseModel):
    text: str = Field(min_length=2, max_length=6000)


class Search(BaseModel):
    query: str = Field(min_length=2, max_length=160)
    query_zh: str = Field(default='', max_length=160)


def create_app(settings=None, transport=None):
    settings = settings or Settings()
    entrants = deque(maxlen=300)
    active = asyncio.Semaphore(3)
    model_calls = deque(maxlen=settings.site_calls + 1)

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(timeout=httpx.Timeout(18, connect=6), transport=transport,
                                     follow_redirects=False, headers={'User-Agent': 'ZhihangPaperSearch/1.0'}) as client:
            app.state.client = client
            runtime=Runtime(client,settings);runtime.sync();app.state.providers=runtime
            task=asyncio.create_task(runtime.loop())
            try:yield
            finally:
                task.cancel()
                await asyncio.gather(task,return_exceptions=True)

    app = FastAPI(title='知航 · 论文查找', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware('http')
    async def boundary(request: Request, call_next):
        if request.url.path.startswith('/api/reader') and request.method == 'POST':
            expected = settings.public_origin or f'{request.url.scheme}://{request.url.netloc}'
            if request.headers.get('sec-fetch-site') == 'cross-site' or (request.headers.get('origin') and request.headers['origin'] != expected):
                return JSONResponse({'detail': '请从知航网站发起检索。'}, 403)
            now = time.monotonic()
            while entrants and entrants[0] < now - 60:
                entrants.popleft()
            if len(entrants) >= 30:
                return JSONResponse({'detail': '检索请求较多，请一分钟后再试。'}, 429)
            entrants.append(now)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        if request.url.path.startswith('/api/reader'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    async def run(operation):
        try:
            await asyncio.wait_for(active.acquire(), timeout=1)
        except TimeoutError:
            raise HTTPException(429, '正在处理其他检索，请稍后再试。') from None
        try:
            return await operation()
        finally:
            active.release()

    @app.get('/api/reader/health')
    def health():
        return {'status': 'ok', 'service': 'paper-search'}

    @app.get('/api/reader/config')
    def config():
        app.state.providers.sync()
        service=app.state.providers.service
        return {'model_enabled': bool(settings.model_key), 'max_input': 6000,
                'wanfang_enabled': '万方' in service.sources,
                'sciencedirect_enabled':'ScienceDirect' in service.sources,
                'source_count':len(service.sources),'warning':app.state.providers.warning}

    @app.post('/api/reader/analyze')
    async def analyze(body: Analysis):
        if len(body.text.strip()) < 2:
            raise HTTPException(422, '请输入新闻内容或技术名称。')
        async def analyze_once():
            if settings.model_key:
                now = time.monotonic()
                while model_calls and model_calls[0] < now - 86400:
                    model_calls.popleft()
                if len(model_calls) >= settings.site_calls:
                    from .discovery import fallback_plan
                    return {**fallback_plan(body.text.strip()), 'notice': '今日 AI 主题提取额度已用完，已切换关键词识别，可继续编辑检索词。'}
                model_calls.append(now)
            return await plan(body.text.strip(), settings, app.state.client)
        return await run(analyze_once)

    @app.post('/api/reader/search')
    async def search(body: Search):
        if len(body.query.strip()) < 2:
            raise HTTPException(422, '请填写检索词。')
        app.state.providers.sync()
        service=app.state.providers.service
        return await run(lambda: service.search(body.query.strip(), body.query_zh.strip()))

    @app.get('/reader')
    def slash():
        return RedirectResponse('/reader/', status_code=308)

    @app.get('/reader/')
    def home():
        return FileResponse(ROOT / 'reader_web/index.html', headers={'Cache-Control': 'no-cache'})

    app.mount('/reader-assets', StaticFiles(directory=ROOT / 'reader_web'), name='reader-assets')
    return app


app = create_app()
