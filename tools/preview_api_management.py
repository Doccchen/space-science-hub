"""Private localhost API-management preview with isolated data and mock providers."""
import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'artifacts/api-management-preview'
DATA.mkdir(parents=True,exist_ok=True)
os.environ.update({'NEWS_DB_PATH':str(DATA/'news.sqlite3'),'MANAGEMENT_DB_PATH':str(DATA/'management.sqlite3'),
                   'AI_MASTER_KEY_FILE':str(DATA/'master.key'),'ADMIN_ORIGIN':'http://127.0.0.1:8100',
                   'COLLECT_ENABLED':'0','AI_ENABLED':'0'})

import httpx
import uvicorn
from backend import admin_auth, ai, ai_config, news
from backend.admin_app import app, lifespan as admin_lifespan
from reader.config import Settings
from reader.provider_runtime import Runtime


def provider(request):
    if request.url.host=='api.wfdata.com':return httpx.Response(200,json={'documents':[],'num_found':0})
    if request.url.host=='api.elsevier.com':return httpx.Response(200,json={'results':[],'resultsFound':0})
    raise httpx.ConnectError('Offline preview only',request=request)


OriginalClient=httpx.AsyncClient
def offline_client(**kwargs):return OriginalClient(transport=httpx.MockTransport(provider),**kwargs)
httpx.AsyncClient=offline_client


@asynccontextmanager
async def lifespan(application):
    async with admin_lifespan(application):
        async with offline_client(timeout=15) as client:
            runtime=Runtime(client,Settings(wanfang_key='',model_key=''))
            task=asyncio.create_task(runtime.loop())
            try:yield
            finally:task.cancel();await asyncio.gather(task,return_exceptions=True)


def main():
    if not (DATA/'master.key').exists():ai_config.generate_key(DATA/'master.key')
    news.initialize()
    with news.connect() as db:exists=db.execute('SELECT 1 FROM admin_user').fetchone()
    if not exists:admin_auth.initialize_user('preview','local-preview-2026')
    ai_config.initialize(ai.Settings(enabled=False,key='',workspace='preview',agent='aid-preview',db=DATA/'ai.sqlite3'))
    app.router.lifespan_context=lifespan
    print('Offline isolated preview: http://127.0.0.1:8100 | preview / local-preview-2026 | Do not enter real keys',flush=True)
    uvicorn.run(app,host='127.0.0.1',port=8100,log_level='warning')


if __name__=='__main__':main()
