"""Private local images in the persistent news volume, never a static web mount."""
import os
import re
import tempfile
import shutil
from pathlib import Path
from . import news


def root():
    return news.DB_PATH.parent/'news-images'


def path(key):
    if not re.fullmatch(r'[1-9][0-9]*/[0-9a-f]{32}/[0-9a-f]{64}\.(jpg|png|webp)', key):
        raise ValueError('Invalid local image key')
    base = root().resolve()
    target = (base/key).resolve()
    if not target.is_relative_to(base):
        raise ValueError('Image path outside private store')
    return target


def write(key, data):
    target = path(key)
    if shutil.disk_usage(news.DB_PATH.parent).free < len(data)+256*1024*1024:
        raise ValueError('Insufficient free disk; preserving database space')
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix='.image-', dir=target.parent)
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return target
