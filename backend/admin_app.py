"""Private administrator web app. Never mount this app in the public service."""
import hashlib
import re
import json
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from . import news, admin_auth
from . import resource_admin, management_store, ai_admin, news_limits_admin

STATIC = Path(__file__).resolve().parent.parent/'admin_web'


@asynccontextmanager
async def lifespan(app):
    admin_auth.origin()
    news.initialize()
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(resource_admin.router)
app.include_router(ai_admin.router)
app.include_router(news_limits_admin.router)
app.add_exception_handler(management_store.ManagementError, resource_admin.management_error)


@app.middleware('http')
async def bounded_request(request, call_next):
    if request.method not in {'GET', 'HEAD'}:
        if request.headers.get('content-type', '').split(';')[0] != 'application/json':
            return JSONResponse({'detail': 'JSON required'}, status_code=415)
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 350_000:
                return JSONResponse({'detail': 'Request too large'}, status_code=413)
        request._body = bytes(data)
        try:
            if not isinstance(json.loads(data), dict):
                raise ValueError('JSON object required')
        except (ValueError, TypeError):
            return JSONResponse({'detail': 'JSON object required'}, status_code=400)
    response = await call_next(request)
    response.headers.update({'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
      'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'"})
    return response


@app.exception_handler(ValueError)
async def invalid(request, error):
    return JSONResponse({'detail': '输入或配置无效，请检查字段与数值范围。'}, status_code=400)


@app.exception_handler(KeyError)
async def missing_field(request, error):
    return JSONResponse({'detail': 'Required field missing'}, status_code=400)


@app.exception_handler(TimeoutError)
async def busy(request, error):
    return JSONResponse({'detail': '采集或维护任务正在占用写锁，请稍后重试。'}, status_code=409)


@app.get('/health')
def health():
    return {'status': 'ok'}


@app.get('/')
def homepage():
    return FileResponse(STATIC/'index.html')


@app.get('/admin.js')
def javascript():
    return FileResponse(STATIC/'admin.js', media_type='application/javascript')


@app.get('/admin.css')
def css():
    return FileResponse(STATIC/'admin.css', media_type='text/css')


@app.get('/brand.svg')
def brand():
    return FileResponse(STATIC/'brand.svg', media_type='image/svg+xml')


@app.get('/resources.js')
def resource_javascript():
    return FileResponse(STATIC/'resources.js', media_type='application/javascript')


@app.get('/ai-settings.js')
def ai_javascript():
    return FileResponse(STATIC/'ai-settings.js', media_type='application/javascript')


@app.get('/news-limits.js')
def news_limits_script():
    return FileResponse(STATIC/'news-limits.js',media_type='application/javascript')


@app.get('/covers/{filename}')
def resource_cover(filename: str, user=Depends(admin_auth.require)):
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*\.jpg', filename) or not (resource_admin.COVERS / filename).is_file():
        raise HTTPException(404, 'Cover not found')
    return FileResponse(resource_admin.COVERS / filename)


@app.post('/api/login')
async def login(request: Request):
    admin_auth.check_origin(request)
    data = await request.json()
    token, csrf = admin_auth.login(data.get('username', ''), data.get('password', ''))
    response = JSONResponse({'csrf': csrf})
    response.set_cookie(admin_auth.COOKIE, token, httponly=True, samesite='strict', secure=admin_auth.origin().startswith('https:'), max_age=admin_auth.SESSION_SECONDS, path='/')
    return response


@app.get('/api/session')
def session(user=Depends(admin_auth.require)):
    storage = {'enabled': True, 'kind': 'server', 'location': 'persistent_news_volume'}
    return {**user, 'storage': storage}


@app.post('/api/logout')
def logout(request: Request, user=Depends(admin_auth.require)):
    with news.connect() as conn:
        conn.execute('DELETE FROM admin_sessions WHERE token_hash=?', (hashlib.sha256(request.cookies[admin_auth.COOKIE].encode()).hexdigest(),))
    response = JSONResponse({'ok': True})
    response.delete_cookie(admin_auth.COOKIE, path='/')
    return response
