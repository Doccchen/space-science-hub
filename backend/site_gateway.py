"""Local same-origin gateway; production may use the supplied Nginx locations."""
import os
from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse,StreamingResponse
from starlette.background import BackgroundTask

HOP={b'connection',b'keep-alive',b'proxy-authenticate',b'proxy-authorization',b'te',b'trailer',b'transfer-encoding',b'upgrade'}


def create_app(main_url=None,reader_url=None,transport=None):
    main_url=main_url or os.getenv('SITE_MAIN_UPSTREAM','http://127.0.0.1:18820')
    reader_url=reader_url or os.getenv('SITE_READER_UPSTREAM','http://127.0.0.1:18821')
    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(timeout=httpx.Timeout(90,connect=5),follow_redirects=False,transport=transport) as client:
            app.state.client=client;yield
    app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    @app.api_route('/{path:path}',methods=['GET','POST','PUT','PATCH','DELETE','HEAD','OPTIONS'])
    async def proxy(request:Request,path:str):
        is_reader=path=='reader' or path.startswith(('reader/','reader-assets/','api/reader/'))
        base=reader_url if is_reader else main_url
        url=base.rstrip('/')+'/'+path
        if request.url.query:url+='?'+request.url.query
        headers=[(k,v) for k,v in request.headers.raw if k.lower() not in HOP|{b'x-reader-client-ip',b'forwarded',b'x-forwarded-for',b'x-forwarded-host',b'x-forwarded-proto'}]
        headers.append((b'x-reader-client-ip',(request.client.host if request.client else 'unknown').encode()))
        try:
            upstream=request.app.state.client.build_request(request.method,url,headers=headers,content=request.stream())
            result=await request.app.state.client.send(upstream,stream=True)
        except httpx.HTTPError:
            return JSONResponse({'detail':'论文检索服务暂不可用。' if is_reader else '网站服务暂不可用。'},502)
        response=StreamingResponse(result.aiter_raw(),status_code=result.status_code,background=BackgroundTask(result.aclose))
        response.raw_headers=[(k,v) for k,v in result.headers.raw if k.lower() not in HOP]
        return response
    return app


app=create_app()
