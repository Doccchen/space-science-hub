"""One durable queue worker in the private admin process; bounded fixed-source jobs."""
import asyncio
import json
import secrets
from . import news, review_store, review_capture, news_assets


def enqueue(conn, article_id, kind, payload):
    active = conn.execute("SELECT COUNT(*) FROM review_jobs WHERE state IN ('queued','running')").fetchone()[0]
    if active >= 20:
        raise ValueError('Review queue is full')
    if kind == 'auto_text':
        auto_active = conn.execute("SELECT COUNT(*) FROM review_jobs WHERE kind='auto_text' AND state IN ('queued','running')").fetchone()[0]
        if auto_active >= 15:
            raise ValueError('Automatic queue budget reached; manual slots reserved')
    job_id = secrets.token_hex(16)
    conn.execute('INSERT INTO review_jobs(id,article_id,kind,payload,created_at) VALUES(?,?,?,?,?)', (job_id, article_id, kind, json.dumps(payload), news.now()))
    return job_id


def run_one(kinds=('capture', 'image')):
    if not kinds:
        return False
    placeholders = ','.join('?' for _ in kinds)
    with news.connect() as conn:
        job = conn.execute(f"SELECT * FROM review_jobs WHERE state='queued' AND kind IN ({placeholders}) ORDER BY created_at,rowid LIMIT 1", kinds).fetchone()
        if job is None:
            return False
        changed = conn.execute("UPDATE review_jobs SET state='running' WHERE id=? AND state='queued'", (job['id'],)).rowcount
        if not changed:
            return False
        item = review_store.article(conn, job['article_id'])
    payload = json.loads(job['payload'])
    try:
        if job['kind'] == 'capture':
            document, candidates = review_capture.capture(item, payload['actor'])
            revision = review_store.save_draft(item['id'], document, payload['revision'], payload['actor'], candidates)
            result = {'revision': revision, 'images_found': len(candidates)}
        elif job['kind'] == 'image':
            news_assets.store_approved(item, payload, job['id'])
            result = {'asset_id': job['id']}
        elif job['kind'] == 'auto_text':
            from . import auto_fulltext
            result = auto_fulltext.process(item, payload)
        else:
            raise ValueError('Unknown job')
        state = 'done'
    except Exception as error:
        state = 'failed'
        # Never store SDK messages that may contain credentials, signed URLs or headers.
        result = {'error': str(error)[:250] if isinstance(error, ValueError) else type(error).__name__, 'retry': 'Review state, then queue a new task'}
    with news.connect() as conn:
        conn.execute('UPDATE review_jobs SET state=?,result=? WHERE id=?', (state, json.dumps(result), job['id']))
        review_store.audit(conn, payload.get('actor', 'worker'), item['id'], job['kind']+'_'+state, job['id'])
    return True


async def loop():
    # Interrupted work remains failed for explicit retry; never silently republish.
    with news.connect() as conn:
        conn.execute("UPDATE review_jobs SET state='failed',result=? WHERE state='running' AND kind IN ('capture','image')", (json.dumps({'error': 'Interrupted by container restart; queue a retry'}),))
    while True:
        await asyncio.to_thread(run_one)
        await asyncio.sleep(1)
