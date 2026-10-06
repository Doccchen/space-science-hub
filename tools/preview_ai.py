"""Loopback-only UI preview using clearly labeled offline responses; never packaged."""
import os
from contextlib import asynccontextmanager
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
os.environ['COLLECT_ENABLED']='0'
os.environ['AI_ENABLED']='0'
os.environ['NEWS_DB_PATH']=str(ROOT/'data/reading-preview/news.sqlite3')

if __name__=='__main__':
    import uvicorn
    from fastapi.responses import HTMLResponse
    from backend.app import app
    from backend.ai import AIService,Settings
    from backend.bailian import Answer
    original=app.router.lifespan_context
    class OfflineClient:
        async def ask(self,messages,request_id):
            return Answer('这是用于检查界面布局的离线测试回答，未调用百炼。\n\n### 让概念更清楚\n这里展示段落、**重点文字**和检索资料展开区。\n\n* 页面保留问题与回答的阅读层次。\n* 下方来源为测试数据，不构成真实回答依据。',
                          [{'name':'离线测试资料（非真实检索）','positions':[0,13,14]}],{'total_tokens':0},'offline-preview',True)
    @asynccontextmanager
    async def lifespan(instance):
        async with original(instance):
            instance.state.ai=AIService(Settings(enabled=True,key='offline-preview',db=ROOT/'artifacts/ai-preview/ai.sqlite3',visitor_daily=1000,ip_daily=1000,site_daily=1000),OfflineClient())
            yield
    app.router.lifespan_context=lifespan
    @app.middleware('http')
    async def label(request,call_next):
        if request.url.path=='/':
            html=(ROOT/'web/index.html').read_text(encoding='utf-8').replace('基于本站专属知识库，把专业概念讲清楚。','离线界面预览 · 固定测试响应，不调用百炼。')
            return HTMLResponse(html)
        return await call_next(request)
    uvicorn.run(app,host='127.0.0.1',port=8094)
