import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import news
from . import resources

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
    task = asyncio.create_task(scheduled_collection()) if os.environ.get("COLLECT_ENABLED", "1") == "1" else None
    yield
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Space News", lifespan=lifespan, docs_url=None, redoc_url=None)
app.include_router(resources.router)


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
def articles(source: str | None = None, cursor: str | None = Query(None, max_length=500),
             limit: int = Query(20, ge=1, le=50), category: str | None = None,
             region: str | None = None, geographic_region: str | None = None):
    try:
        return news.list_articles(source, cursor, limit, category, region, geographic_region)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@app.get("/api/news/{article_id}")
def article(article_id: int):
    with news.connect() as conn:
        row = conn.execute("""SELECT a.*,s.name AS source_name,s.region,s.publisher_kind,s.enabled AS source_enabled,
            s.geographic_region,s.country_code FROM articles a
            JOIN sources s ON s.id=a.source_id WHERE a.id=?""", (article_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Article not found")
    return dict(row)


@app.get("/")
def homepage():
    return FileResponse(STATIC / "index.html")


app.mount("/assets", StaticFiles(directory=STATIC), name="assets")
