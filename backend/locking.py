"""One OS lock shared by scheduled collection, migration and admin commands."""
import os
import time
from contextlib import contextmanager


@contextmanager
def operation_lock(db_path, timeout=0):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(str(db_path) + '.lock', 'a+b')
    handle.seek(0, 2)
    if not handle.tell():
        handle.write(b'0')
        handle.flush()
    deadline = time.monotonic() + timeout
    acquired = False
    try:
        while True:
            try:
                if os.name == 'nt':
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except (BlockingIOError, OSError):
                if time.monotonic() >= deadline:
                    raise RuntimeError('Another collector/migration/backfill holds the database operation lock')
                time.sleep(0.05)
        yield
    finally:
        if acquired:
            if os.name == 'nt':
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
