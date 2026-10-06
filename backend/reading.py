"""Reviewed reading editions. Public requests never fetch publisher content.

Imported editions are immutable; a separate head records publication/withdrawal.
Legacy collector excerpts stay private until explicitly reviewed.
"""
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from . import news
from .locking import operation_lock
from .reading_policy import source_policy, policy_version, direct_enabled

PERMISSIONS = {'pending', 'policy_reviewed', 'explicit_grant', 'denied', 'withdrawn'}
ALLOWED = {'policy_reviewed', 'explicit_grant'}
MAX_DOCUMENT_BYTES = 300_000


def migrate(conn):
    existing = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if {'reading_heads', 'article_contents', 'reading_audit'} <= existing:
        return
    if conn.execute('SELECT COUNT(*) FROM articles').fetchone()[0]:
        backup = news.DB_PATH.with_name(news.DB_PATH.name + '.before-v4.sqlite3')
        if not backup.exists():
            with closing(sqlite3.connect(news.DB_PATH)) as origin, closing(sqlite3.connect(backup)) as target:
                origin.backup(target)
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS article_contents (
      article_id INTEGER NOT NULL REFERENCES articles(id), version TEXT NOT NULL,
      document TEXT NOT NULL, created_at TEXT NOT NULL,
      PRIMARY KEY(article_id,version));
    CREATE TABLE IF NOT EXISTS reading_heads (
      article_id INTEGER PRIMARY KEY REFERENCES articles(id), version TEXT NOT NULL,
      revision INTEGER NOT NULL DEFAULT 1, withdrawn INTEGER NOT NULL DEFAULT 0,
      updated_at TEXT NOT NULL,
      FOREIGN KEY(article_id,version) REFERENCES article_contents(article_id,version));
    CREATE TABLE IF NOT EXISTS reading_audit (
      id INTEGER PRIMARY KEY, article_id INTEGER NOT NULL REFERENCES articles(id),
      version TEXT NOT NULL, action TEXT NOT NULL, reviewer TEXT NOT NULL,
      reason TEXT NOT NULL, created_at TEXT NOT NULL);
    ''')


def plain(value, maximum=12000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError('Missing or oversized plain text')
    if any(ord(char) < 32 and char not in '\n\t' for char in value):
        raise ValueError('Control characters are not allowed')
    return value


def exact_keys(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        raise ValueError('Unexpected or missing fields')


def validate(document):
    exact_keys(document, {'original_url', 'mode', 'language', 'blocks', 'permissions',
                          'credit', 'reviewed_at', 'reviewer', 'completeness', 'notes'}, {'source_sha256', 'publication_mode', 'source_record_hash'})
    if 'source_record_hash' in document:
        value = document['source_record_hash']
        if not isinstance(value, str) or len(value) != 64 or any(char not in '0123456789abcdef' for char in value):
            raise ValueError('Invalid source record hash')
    if document.get('publication_mode') not in {None, 'government_direct'}:
        raise ValueError('Unknown publication mode')
    if 'source_sha256' in document:
        value = document['source_sha256']
        if not isinstance(value, str) or len(value) != 64 or any(char not in '0123456789abcdef' for char in value):
            raise ValueError('Invalid source snapshot digest')
    if document['mode'] not in {'full', 'guide'}:
        raise ValueError('Only full or guide editions can be imported')
    for key in ('original_url', 'language', 'credit', 'reviewed_at', 'reviewer', 'notes'):
        plain(document[key], 4000)
    checked = datetime.fromisoformat(document['reviewed_at'])
    if checked.tzinfo is None:
        raise ValueError('Review time needs a timezone')
    exact_keys(document['permissions'], {'text', 'image', 'translation', 'ai_context'})
    for permission in document['permissions'].values():
        exact_keys(permission, {'status'}, {'basis', 'rightsholder', 'purpose', 'expires_at', 'third_party_check'})
        if permission['status'] not in PERMISSIONS:
            raise ValueError('Unknown permission')
        if permission['status'] in ALLOWED:
            for key in ('basis', 'rightsholder', 'purpose', 'third_party_check'):
                plain(permission.get(key), 4000)
            if permission['purpose'] != 'public_web_text':
                raise ValueError('Permission must cover public web text')
        if permission.get('expires_at'):
            expiry = datetime.fromisoformat(permission['expires_at'])
            if expiry.tzinfo is None:
                raise ValueError('Expiry needs a timezone')
    # Image/translation/model permissions are deliberately not activated this round.
    if any(document['permissions'][key]['status'] in ALLOWED for key in ('image', 'translation', 'ai_context')):
        raise ValueError('Images, translation and AI are outside this release')
    if document['completeness'] not in {'complete_checked', 'own_guide_checked', 'structure_checked'}:
        raise ValueError('Content must be checked before publication')
    automatic = document.get('publication_mode') == 'government_direct'
    expected = 'structure_checked' if automatic else 'complete_checked' if document['mode'] == 'full' else 'own_guide_checked'
    if document['completeness'] != expected or automatic and document['mode'] != 'full':
        raise ValueError('Completeness does not match edition mode')
    blocks = document['blocks']
    if not isinstance(blocks, list) or not 1 <= len(blocks) <= 250:
        raise ValueError('Expected 1–250 blocks')
    for block in blocks:
        if not isinstance(block, dict):
            raise ValueError('Invalid block')
        kind = block.get('type')
        if kind in {'heading', 'paragraph'}:
            exact_keys(block, {'type', 'text'}, {'level'} if kind == 'heading' else ())
            plain(block['text'])
            if kind == 'heading' and block.get('level', 2) not in {2, 3, 4}:
                raise ValueError('Invalid heading level')
        elif kind == 'list':
            exact_keys(block, {'type', 'items'}, {'ordered'})
            if not isinstance(block['items'], list) or not 1 <= len(block['items']) <= 50:
                raise ValueError('Invalid list')
            for item in block['items']:
                plain(item)
            if 'ordered' in block and type(block['ordered']) is not bool:
                raise ValueError('Invalid list ordering')
        elif kind == 'table':
            exact_keys(block, {'type', 'rows'}, {'caption'})
            rows = block['rows']
            if not isinstance(rows, list) or not 1 <= len(rows) <= 50:
                raise ValueError('Invalid table')
            width = len(rows[0]) if isinstance(rows[0], list) else 0
            if not 1 <= width <= 10:
                raise ValueError('Invalid table width')
            for row in rows:
                if not isinstance(row, list) or len(row) != width:
                    raise ValueError('Ragged table')
                for cell in row:
                    plain(cell, 2000)
            if 'caption' in block:
                plain(block['caption'], 2000)
        else:
            raise ValueError('Unsupported block; no HTML or media embeds')
    serialized = json.dumps(document, ensure_ascii=False, sort_keys=True)
    if len(serialized.encode()) > MAX_DOCUMENT_BYTES:
        raise ValueError('Edition exceeds byte budget')
    return serialized


def publish(document, *, republish=False, only_if_missing=False, conn=None):
    serialized = validate(document)
    version = hashlib.sha256(serialized.encode()).hexdigest()[:24]
    if conn is None:
        with operation_lock(news.DB_PATH, timeout=10), news.connect() as db:
            return publish(document, republish=republish, only_if_missing=only_if_missing, conn=db)
    if conn is not None:
        row = conn.execute('SELECT id,source_id FROM articles WHERE canonical_url=?',
                           (news.canonical_url(document['original_url']),)).fetchone()
        if not row:
            raise ValueError('Article must already exist; import never creates news')
        article_id = row['id']
        if document.get('publication_mode') == 'government_direct' and source_policy(row['source_id']) != 'government_candidate':
            raise ValueError('Automatic full text is limited to configured government sources')
        current = conn.execute('SELECT * FROM reading_heads WHERE article_id=?', (article_id,)).fetchone()
        if current and only_if_missing:
            return {'article_id': article_id, 'version': current['version'], 'changed': False,
                    'status': 'existing_edition_preserved'}
        if current and current['withdrawn'] and not republish:
            raise ValueError('Withdrawn edition requires explicit republish authorization')
        if current and current['version'] == version and not current['withdrawn']:
            return {'article_id': article_id, 'version': version, 'changed': False}
        stamp = news.now()
        conn.execute('INSERT OR IGNORE INTO article_contents VALUES(?,?,?,?)', (article_id, version, serialized, stamp))
        conn.execute('''INSERT INTO reading_heads(article_id,version,updated_at) VALUES(?,?,?)
          ON CONFLICT(article_id) DO UPDATE SET version=excluded.version, revision=revision+1,
          withdrawn=0,updated_at=excluded.updated_at''', (article_id, version, stamp))
        conn.execute('INSERT INTO reading_audit(article_id,version,action,reviewer,reason,created_at) VALUES(?,?,?,?,?,?)',
                     (article_id, version, 'publish', document['reviewer'], document['notes'], stamp))
    return {'article_id': article_id, 'version': version, 'changed': True}


def withdraw(article_id, reviewer, reason):
    plain(reviewer, 200); plain(reason, 4000)
    with operation_lock(news.DB_PATH, timeout=10), news.connect() as conn:
        row = conn.execute('SELECT * FROM reading_heads WHERE article_id=?', (article_id,)).fetchone()
        if not row:
            raise ValueError('No published edition')
        if not row['withdrawn']:
            stamp = news.now()
            conn.execute('UPDATE reading_heads SET withdrawn=1,revision=revision+1,updated_at=? WHERE article_id=?', (stamp, article_id))
            conn.execute('INSERT INTO reading_audit(article_id,version,action,reviewer,reason,created_at) VALUES(?,?,?,?,?,?)',
                         (article_id, row['version'], 'withdraw', reviewer, reason, stamp))


def editions(conn, ids):
    if not ids:
        return {}
    placeholders = ','.join('?' for _ in ids)
    return {row['article_id']: dict(row) for row in conn.execute(f'''SELECT h.*,c.document
      FROM reading_heads h JOIN article_contents c ON c.article_id=h.article_id AND c.version=h.version
      WHERE h.article_id IN ({placeholders})''', ids)}


def permitted(permission):
    if permission['status'] not in ALLOWED:
        return False
    expiry = permission.get('expires_at')
    return not expiry or datetime.fromisoformat(expiry) > datetime.now(timezone.utc)


def public_content(item, edition):
    policy = source_policy(item.get('source_id'))
    display_version = policy_version()
    result = {'article_id': item['id'], 'read_scope': 'link_only', 'reading_mode': 'link_only',
              'source_reading_policy': policy, 'original_url': item['original_url'],
              'content_version': display_version + ':link', 'blocks': [], 'assets': [],
              'credit': '', 'notes': '正文和来源节选尚未核对展示许可，请查看发布方原文。',
              'language': item['lang'], 'images_status': 'not_included'}
    if policy != 'government_candidate':
        result['notes'] = '本来源提供原文阅读，请访问发布方网站。'
        return result
    if direct_enabled():
        result['notes'] = '政府原文正文尚未取回或尚无法完整解析，请访问发布方原文。'
    if not edition:
        return result
    document = json.loads(edition['document'])
    result['content_version'] = display_version + ':' + edition['version'] + ':' + str(edition['revision'])
    permission = document['permissions']['text']
    automatic = (direct_enabled() and document.get('publication_mode') == 'government_direct'
                 and permission['status'] == 'pending' and not permission.get('expires_at'))
    if edition['withdrawn'] or not (permitted(permission) or automatic):
        status = 'withdrawn' if edition['withdrawn'] or permission['status'] == 'withdrawn' else permission['status']
        if status in ALLOWED:
            status = 'expired'
        result['content_version'] += ':' + status
        scope = 'link_only' if status == 'pending' else 'unavailable'
        notes = {'pending': '正文展示许可尚待核对，请查看发布方原文。', 'denied': '正文未获展示许可，请查看发布方原文。',
                 'withdrawn': '本站内容已撤下，请查看发布方原文。', 'expired': '正文展示许可已失效，请查看发布方原文。'}[status]
        if status == 'pending' and direct_enabled():
            notes = '正文暂未形成可展示的自动转载版本，请访问发布方原文。'
        result.update(read_scope=scope, reading_mode=scope, availability=status, notes=notes)
        return result
    if document['mode'] != 'full':
        result['content_version'] += ':link'
        result['notes'] = '本轮不展示本站导读，请访问发布方原文。'
        return result
    result.update(read_scope='full_text', reading_mode='full_text',
                  credit=document['credit'], language=document['language'], notes=document['notes'])
    result['blocks'] = [{**block, 'block_id': f"b{index:03d}"} for index, block in enumerate(document['blocks'], 1)]
    # Public notice only; private review evidence and reviewer identities stay off APIs.
    result['usage'] = {'status': 'operator_direct' if automatic else permission['status'], 'images': '图片请到原文查看。'}
    return result


def public_rows(conn, rows):
    snapshots = editions(conn, [row['id'] for row in rows if source_policy(row['source_id']) == 'government_candidate'])
    safe = []
    for row in rows:
        item = dict(row)
        content = content_with_assets(conn, item, snapshots.get(item['id']))
        item.update(summary='', summary_kind='none', reading_mode=content['reading_mode'],
                    read_scope=content['read_scope'], content_version=content['content_version'],
                    source_reading_policy=content['source_reading_policy'])
        # Preview comes only from the currently permitted government full text.
        if content['read_scope'] == 'full_text':
            item['summary'] = next((block['text'][:600] for block in content['blocks'] if block['type'] == 'paragraph'), '')
            item['summary_kind'] = 'body_excerpt' if content.get('usage', {}).get('status') == 'operator_direct' else 'reviewed_excerpt'
        safe.append(item)
    return safe


def content_with_assets(conn, item, edition):
    result = public_content(item, edition)
    if result['reading_mode'] == 'full_text':
        from . import news_assets
        result['assets'] = news_assets.available(conn, item['id'], edition['version'])
        result['content_version'] += ':media-' + hashlib.sha256(json.dumps(result['assets'], sort_keys=True).encode()).hexdigest()[:12]
        if result['assets']:
            result['images_status'] = 'reviewed_images'
    return result
