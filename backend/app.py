import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Path as PathParam, Query, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import news
from . import resources
from . import reading
from . import ai
from . import ai_runtime
from . import news_policy
from . import news_agent, news_mcp

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "web"


async def scheduled_collection():
    # Sequential rounds prevent overlaps; production CMD uses exactly one worker.
    interval = max(300, int(os.environ.get("COLLECT_INTERVAL_SECONDS", "3600")))
    while True:
        try:
            await news.collect_all()
        except Exception:
            logging.exception("Collection round failed")
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app):
    news.initialize()
    resources.catalog.load()
    runtime = ai_runtime.startup()
    app.state.ai = runtime.service
    app.state.news_agent = news_agent.NewsAgentService(news_agent.Settings.environment(), app.state.ai)
    news_cleanup = asyncio.create_task(app.state.news_agent.housekeeping())
    # SDK managers are single-lifespan objects. Recreate for tests/restarts.
    app.state.news_mcp_sdk, fresh_mcp = news_mcp.build(lambda: getattr(app.state, 'news_agent', None))
    mcp_app.app = fresh_mcp.app
    mcp_manager = app.state.news_mcp_sdk.session_manager.run()
    await mcp_manager.__aenter__()
    ai_cleanup = asyncio.create_task(ai.housekeeping(app.state.ai))
    ai_sync = asyncio.create_task(runtime.loop())
    task = asyncio.create_task(scheduled_collection()) if os.environ.get("COLLECT_ENABLED", "1") == "1" else None
    from . import auto_fulltext
    auto_task = asyncio.create_task(auto_fulltext.loop()) if task and os.environ.get('GOVERNMENT_FULLTEXT_AUTO', '1') == '1' else None
    from . import news_thumbnails
    thumbnail_task = asyncio.create_task(news_thumbnails.loop()) if task and os.environ.get('NEWS_THUMBNAILS_ENABLED','0')=='1' else None
    yield
    news_cleanup.cancel()
    await asyncio.gather(news_cleanup, return_exceptions=True)
    await app.state.news_agent.close()
    await mcp_manager.__aexit__(None, None, None)
    ai_sync.cancel()
    try:
        await ai_sync
    except asyncio.CancelledError:
        pass
    await runtime.close()
    if thumbnail_task:
        thumbnail_task.cancel()
        try: await thumbnail_task
        except asyncio.CancelledError: pass
    if ai_cleanup:
        ai_cleanup.cancel()
        try:
            await ai_cleanup
        except asyncio.CancelledError:
            pass
    if auto_task:
        auto_task.cancel()
        try:
            await auto_task
        except asyncio.CancelledError:
            pass
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Space News", lifespan=lifespan, docs_url=None, redoc_url=None)
app.include_router(resources.router)
app.include_router(ai.router)
app.include_router(news_agent.router)
app.state.news_mcp_sdk, mcp_app = news_mcp.build(lambda: getattr(app.state, 'news_agent', None))
app.mount('/api/news-mcp', mcp_app)


@app.get("/api/health")
def health():
    with news.connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    return {"status": "ok", "articles": count}


@app.get("/api/news/sources")
def sources():
    # No raw upstream errors exposed on the public endpoint.
    return {"items": [{**row, "last_error": bool(row["last_error"])} for row in news.sources_status()],
            'geographic_regions': [{'id': key, 'name': name} for key, name in news.GEOGRAPHIC_REGIONS.items()]}


@app.get("/api/news")
def articles(response: Response, source: str | None = None, cursor: str | None = Query(None, max_length=500),
             limit: int = Query(20, ge=1, le=50), category: str | None = None,
             region: str | None = None, geographic_region: str | None = None,
             page: int | None = Query(None, ge=1, le=1000000), page_size: int | None = Query(None, ge=1, le=50),
             snapshot: int | None = Query(None, ge=0, le=9223372036854775807)):
    try:
        result = news.list_articles(source, cursor, limit, category, region, geographic_region, page, page_size, snapshot)
        with news.connect() as conn:
            result['items'] = reading.public_rows(conn, result['items'])
        response.headers['Cache-Control'] = 'no-store'
        return result
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@app.get("/api/news/{article_id}")
def article(response: Response, article_id: int = PathParam(ge=1, le=9223372036854775807)):
    with news.connect() as conn:
        row = conn.execute("""SELECT a.*,s.name AS source_name,s.region,s.publisher_kind,s.enabled AS source_enabled,
            s.geographic_region,s.country_code FROM articles a
            JOIN sources s ON s.id=a.source_id WHERE a.id=?""", (article_id,)).fetchone()
        if row is None or news_policy.excluded_item(row):
            raise HTTPException(404, "Article not found")
        result = reading.public_rows(conn, [row])[0]
    response.headers['Cache-Control'] = 'no-store'
    return result


@app.get('/api/news/{article_id}/content')
def article_content(response: Response, article_id: int = PathParam(ge=1, le=9223372036854775807)):
    with news.connect() as conn:
        row = conn.execute('SELECT id,lang,source_id,original_url,title FROM articles WHERE id=?', (article_id,)).fetchone()
        if row is None or news_policy.excluded_item(row):
            raise HTTPException(404, 'Article not found')
        result = reading.content_with_assets(conn, dict(row), reading.editions(conn, [article_id]).get(article_id))
    response.headers['Cache-Control'] = 'no-store'
    return result


@app.get('/api/news/{article_id}/assets/{asset_id}')
def article_asset(article_id: int, asset_id: str):
    from . import news_assets, news_image_store
    with news.connect() as conn:
        item = conn.execute('SELECT id,source_id,original_url,lang,title FROM articles WHERE id=?', (article_id,)).fetchone()
        edition = reading.editions(conn, [article_id]).get(article_id)
        if not item or news_policy.excluded_item(item) or not edition or reading.public_content(dict(item), edition)['reading_mode'] != 'full_text':
            raise HTTPException(404, 'Image unavailable')
        available = news_assets.available(conn, article_id, edition['version'])
        if not any(asset['id'] == asset_id for asset in available):
            raise HTTPException(404, 'Image unavailable')
        row = conn.execute('SELECT object_key,mime FROM article_assets WHERE id=? AND article_id=?', (asset_id, article_id)).fetchone()
    try:
        path = news_image_store.path(row['object_key'])
        if not path.is_file():
            raise ValueError('Image file missing')
    except Exception:
        raise HTTPException(503, 'Image storage temporarily unavailable') from None
    return FileResponse(path, media_type=row['mime'], headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


@app.get('/api/news/{article_id}/thumbnail')
def article_thumbnail(article_id: int, v: str = Query('',max_length=24)):
    from . import news_thumbnails, news_image_store
    with news.connect() as db:
        db.execute('BEGIN')
        item=db.execute('SELECT * FROM articles WHERE id=?',(article_id,)).fetchone()
        thumbnail=news_thumbnails.public_thumbnail(db,dict(item)) if item else None
        if not thumbnail or v and v!=thumbnail['version']:
            raise HTTPException(404,'Thumbnail unavailable')
        row=db.execute('SELECT object_key,mime FROM news_thumbnails WHERE article_id=?',(article_id,)).fetchone()
    try:
        picture=news_image_store.path(row['object_key'])
        if not picture.is_file(): raise ValueError('Missing thumbnail')
    except (ValueError,OSError): raise HTTPException(404,'Thumbnail unavailable') from None
    return FileResponse(picture,media_type=row['mime'],headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})


@app.get("/")
def homepage():
    return FileResponse(STATIC / "index.html")


app.mount("/assets", StaticFiles(directory=STATIC), name="assets")
