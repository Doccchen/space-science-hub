"""Approved pictures only. Private storage failures cannot break historical text."""
import hashlib
import json
from io import BytesIO
from . import news, reading, news_image_store
from .publisher_fetch import Publisher
from .reading_policy import source_policy


def inspect_image(data, declared):
    from PIL import Image
    if not 0 < len(data) <= 8*1024*1024:
        raise ValueError('Image byte budget exceeded')
    with Image.open(BytesIO(data)) as image:
        fmt = image.format
        if fmt not in {'JPEG', 'PNG', 'WEBP'} or image.width*image.height > 24_000_000 or getattr(image, 'n_frames', 1) != 1:
            raise ValueError('Unsupported or oversized image')
        mime, extension = {'JPEG': ('image/jpeg', 'jpg'), 'PNG': ('image/png', 'png'), 'WEBP': ('image/webp', 'webp')}[fmt]
        if declared != mime:
            raise ValueError('Image type does not match response')
        width, height = image.size
        image.load()
    return mime, extension, width, height


def store_approved(item, payload, asset_id):
    with news.connect() as conn:
        edition = reading.editions(conn, [item['id']]).get(item['id'])
        visible = reading.public_content(item, edition)
    if visible['reading_mode'] != 'full_text' or edition['version'] != payload['version']:
        raise ValueError('Article edition changed or is no longer allowed')
    permission = payload['permission']
    if not reading.permitted(permission) or source_policy(item['source_id']) != 'government_candidate':
        raise ValueError('Image permission unavailable')
    data, declared = Publisher(item['source_id']).get(payload['source_url'], image=True, limit=8*1024*1024)
    mime, extension, width, height = inspect_image(data, declared)
    key = f"{item['id']}/{asset_id}/{hashlib.sha256(data).hexdigest()}.{extension}"
    news_image_store.write(key, data)
    # A withdrawn/new edition cannot expose this file even if storage completed.
    with news.connect() as conn:
        current = reading.editions(conn, [item['id']]).get(item['id'])
        visible = reading.public_content(item, current)
        if not current or current['version'] != payload['version'] or visible['reading_mode'] != 'full_text':
            raise ValueError('Edition changed during image storage; file retained unpublished')
        conn.execute('INSERT INTO article_assets VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                     (asset_id, item['id'], payload['version'], payload['source_url'], key, mime, width, height,
                      payload['caption'], payload['credit'], json.dumps({**permission, 'block_index': payload['block_index']}), 'ready', news.now()))


def available(conn, article_id, version):
    if not version:
        return []
    output = []
    for row in conn.execute('SELECT * FROM article_assets WHERE article_id=? AND content_version=? AND status=? ORDER BY created_at,id', (article_id, version, 'ready')):
        permission = json.loads(row['permission'])
        if reading.permitted(permission):
            output.append({'id': row['id'], 'url': f"/api/news/{article_id}/assets/{row['id']}", 'width': row['width'], 'height': row['height'],
                           'caption': row['caption'], 'credit': row['credit'], 'block_index': permission.get('block_index', 0)})
    return output
