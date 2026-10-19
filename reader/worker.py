import asyncio
import json
import sys
import time


async def parse_one(store, task):
    target = store.root / 'jobs' / (task['id'] + '.json')
    started = time.monotonic()
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable, '-m', 'reader.parser',
            str(store.root / 'files' / (task['paper'] + '.pdf')), str(target), str(store.settings.max_pages),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        while process.returncode is None:
            with store.connect() as db:
                active = db.execute("SELECT id FROM tasks WHERE id=? AND state='running'", (task['id'],)).fetchone()
            if not active:
                return
            if time.monotonic() - started > store.settings.parse_timeout:
                raise TimeoutError()
            try:
                await asyncio.wait_for(process.wait(), .25)
            except asyncio.TimeoutError:
                continue
        # A child can finish between polls (or during process creation). The
        # deadline still applies to its total elapsed time, not just live polls.
        if time.monotonic() - started > store.settings.parse_timeout:
            raise TimeoutError()
        if process.returncode or not target.exists():
            raise RuntimeError()
        result = json.loads(target.read_text(encoding='utf-8'))
        if 'error' in result:
            error = result['error']
        else:
            error = ''
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        error, result = '解析超时，请拆分文件或稍后手动重试。', {}
    except Exception:
        error, result = '解析进程失败，请检查文件后手动重试。', {}
    finally:
        if process and process.returncode is None:
            process.kill()
            await process.wait()
        target.unlink(missing_ok=True)
    with store.connect() as db:
        row = db.execute("SELECT * FROM papers WHERE id=? AND version=? AND status='parsing'", (task['paper'], task['version'])).fetchone()
        if not row:
            return
        now = time.time()
        if error:
            db.execute("UPDATE papers SET status='failed',error=?,updated=? WHERE id=?", (error, now, row['id']))
        else:
            from .store import uid
            for b in result['blocks']:
                db.execute('INSERT INTO blocks VALUES(?,?,?,?,?,?,?,?)', (uid(), row['id'], row['version'], b['page'], b['section'], b['ordinal'], b['text'], json.dumps(b['bbox'])))
            status = 'partial' if result['coverage']['missing_pages'] else 'ready'
            db.execute('UPDATE papers SET status=?,coverage=?,error=?,updated=? WHERE id=?',
                       (status, json.dumps(result['coverage']), '', now, row['id']))
            if not row['metadata_edited']:
                meta = result['metadata']
                db.execute('UPDATE papers SET title=?,authors=?,doi=? WHERE id=?',
                           (meta['title'] or row['title'], meta['authors'], meta['doi'], row['id']))
        db.execute('UPDATE tasks SET state=?,error=?,updated=?,duration=? WHERE id=?',
                   ('failed' if error else 'done', error, now, time.monotonic()-started, task['id']))


async def loop(store):
    while True:
        task = None
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM tasks WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
            if row:
                task = dict(row)
                db.execute("UPDATE tasks SET state='running',updated=? WHERE id=?", (time.time(), row['id']))
                db.execute("UPDATE papers SET status='parsing',updated=? WHERE id=?", (time.time(), row['paper']))
        if task:
            await parse_one(store, task)
        else:
            await asyncio.sleep(.25)
