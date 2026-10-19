"""Temporary-file lifecycle, independent of the website and model budgets."""
import time


def discard(store, owner=None, paper=None):
    with store.connect() as db:
        if paper:
            ids=[r['id'] for r in db.execute('SELECT id FROM papers WHERE id=? AND owner=?',(paper,owner))]
        else:
            ids=[r['id'] for r in db.execute('SELECT id FROM papers WHERE owner=?',(owner,))]
        for identity in ids:
            db.execute('DELETE FROM papers WHERE id=?',(identity,))
    for identity in ids:
        try:(store.root/'files'/(identity+'.pdf')).unlink(missing_ok=True)
        except PermissionError:pass  # The parser notices cancellation; sweep retries.
    return ids


def remove_files(store,ids):
    pending=False
    for identity in ids:
        try:(store.root/'files'/(identity+'.pdf')).unlink(missing_ok=True)
        except PermissionError:pending=True
    return pending


def sweep(store, now=None):
    now=time.time() if now is None else now
    with store.connect() as db:
        expired=[r['owner'] for r in db.execute('SELECT owner FROM visitors WHERE expires<=?',(now,))]
    for owner in expired:discard(store,owner=owner)
    with store.connect() as db:
        db.execute('DELETE FROM visitors WHERE expires<=?',(now,))
        cutoff=now-8*86400
        db.execute("DELETE FROM usage WHERE created<? AND state!='running'",(cutoff,))
        db.execute('DELETE FROM network_usage WHERE created<?',(cutoff,))
        db.execute('DELETE FROM upload_events WHERE created<?',(cutoff,))
        live={r['id'] for r in db.execute('SELECT id FROM papers')}
    for path in (store.root/'files').glob('*.pdf'):
        if path.stem not in live:
            try:path.unlink(missing_ok=True)
            except PermissionError:pass
