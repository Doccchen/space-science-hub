"""Private resource CRUD with optimistic revisions and bounded OSS checks."""
import json
import re
import uuid
from urllib.parse import unquote, urlsplit

import httpx
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from . import admin_auth, management_store as store, news, resources

router = APIRouter(prefix='/api/resources', dependencies=[Depends(admin_auth.require)])
EDITABLE = {'title', 'authors', 'category', 'tags', 'size_bytes', 'pdf_address', 'cover_asset', 'display_order', 'published'}
COVERS = resources.ROOT / 'web/resource-covers'


def pdf_key(address):
    if not isinstance(address, str) or not address or address != address.strip() or len(address) > 4096:
        raise store.ManagementError('PDF 地址格式无效。', 400)
    if any(ord(char) < 32 or ord(char) == 127 for char in address):
        raise store.ManagementError('PDF 地址不能包含控制字符。', 400)
    key = address
    if address.startswith('https://'):
        parsed = urlsplit(address)
        if (parsed.netloc != urlsplit(resources.OSS_ORIGIN).netloc or parsed.query or parsed.fragment
                or '?' in address or '#' in address):
            raise store.ManagementError('仅允许固定 OSS 来源的无参数 HTTPS 地址。', 400)
        if re.search(r'%(?![0-9a-fA-F]{2})', parsed.path):
            raise store.ManagementError('地址编码无效。', 400)
        try:
            key = unquote(parsed.path.removeprefix('/'), encoding='utf-8', errors='strict')
        except UnicodeError:
            raise store.ManagementError('地址编码无效。', 400) from None
    elif '?' in address or '#' in address:
        raise store.ManagementError('对象路径不能包含地址参数或片段。', 400)
    try:
        resources.object_url(key)
    except ValueError:
        raise store.ManagementError('文件必须是 public/ 下合法的 PDF 路径。', 400) from None
    return key


def validated(value, changes):
    if not isinstance(changes, dict) or set(changes) - EDITABLE:
        raise store.ManagementError('资料字段无效。', 400)
    value = dict(value)
    for field, data in changes.items():
        if field == 'pdf_address':
            value['object_key'] = pdf_key(data)
        else:
            value[field] = data
    if 'cover_asset' in changes:
        cover = changes['cover_asset']
        if cover is not None and (not isinstance(cover, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]*\.jpg', cover)
                                  or not (COVERS / cover).is_file()):
            raise store.ManagementError('请选择已有的本地封面。', 400)
        value['cover_key'] = None
    value['updated_at'] = news.now()
    try:
        item = resources.Resource.model_validate(value)
        resources.object_url(item.object_key)
        if not item.title.strip():
            raise ValueError()
        if len(item.authors) > 30 or len(item.tags) > 50 or any(len(s) > 200 for s in item.authors + item.tags):
            raise ValueError()
        if item.category is not None and len(item.category) > 80:
            raise ValueError()
        if item.size_bytes > 9007199254740991 or item.display_order > 2147483647:
            raise ValueError()
        return item
    except (ValueError, TypeError):
        raise store.ManagementError('资料字段或范围无效，请检查标题、文件大小、排序及上架状态。', 400) from None


def revision(body, current):
    expected = body.get('revision')
    if type(expected) is not int or expected != current:
        raise store.ManagementError('资料已被修改，请重新加载后核对；未覆盖原记录。')


@router.get('')
def listing(q: str = Query('', max_length=120), state: str = Query('all', pattern='^(all|published|hidden)$')):
    store.require_active()
    with store.connection() as db:
        items = [store.record(row) for row in db.execute('SELECT * FROM resource_items')]
    query = resources.normalized(q)
    items = [item for item in items if (state == 'all' or item['published'] == (state == 'published'))
             and (not query or query in resources.normalized(' '.join([item['title'], *item['authors'], *item['tags']])))]
    items.sort(key=lambda item: (item['display_order'], item['id']))
    return {'items': items, 'covers': sorted(p.name for p in COVERS.glob('*.jpg'))}


@router.get('/{identity}')
def detail(identity: str):
    store.require_active()
    with store.connection() as db:
        return store.record(store.get(db, identity))


@router.post('')
async def create(request: Request, user=Depends(admin_auth.require)):
    store.require_active()
    body = await request.json()
    if set(body) != {'changes'} or not isinstance(body['changes'], dict):
        raise store.ManagementError('新增资料格式无效。', 400)
    if body['changes'].get('published') not in (None, False):
        raise store.ManagementError('新增资料必须先保存为下架状态。', 400)
    item = validated({'id': 'book-' + uuid.uuid4().hex, 'published': False}, body['changes'])
    with store.connection(write=True) as db:
        store.write_record(db, item, 1, user['username'], 'create', sorted(body['changes']))
    return {**item.model_dump(), 'revision': 1}


@router.patch('/{identity}')
async def update(identity: str, request: Request, user=Depends(admin_auth.require)):
    store.require_active()
    body = await request.json()
    if set(body) != {'revision', 'changes'}:
        raise store.ManagementError('修改资料格式无效。', 400)
    with store.connection(write=True) as db:
        row = store.get(db, identity)
        revision(body, row['revision'])
        item = validated(json.loads(row['record']), body['changes'])
        version = row['revision'] + 1
        store.write_record(db, item, version, user['username'], 'update', sorted(body['changes']))
    return {**item.model_dump(), 'revision': version}


@router.get('/{identity}/history')
def history(identity: str):
    store.require_active()
    with store.connection() as db:
        store.get(db, identity)
        rows = db.execute('SELECT * FROM resource_revisions WHERE resource_id=? ORDER BY revision DESC', (identity,)).fetchall()
    return {'items': [{**dict(row), 'record': json.loads(row['record'])} for row in rows]}


@router.post('/{identity}/restore')
async def restore(identity: str, request: Request, user=Depends(admin_auth.require)):
    store.require_active()
    body = await request.json()
    if set(body) != {'revision', 'target_revision'} or type(body['target_revision']) is not int:
        raise store.ManagementError('恢复版本格式无效。', 400)
    with store.connection(write=True) as db:
        row = store.get(db, identity)
        revision(body, row['revision'])
        old = db.execute('SELECT record FROM resource_revisions WHERE resource_id=? AND revision=?',
                         (identity, body['target_revision'])).fetchone()
        if old is None:
            raise store.ManagementError('历史版本不存在。', 404)
        item = validated(json.loads(old['record']), {})
        version = row['revision'] + 1
        store.write_record(db, item, version, user['username'], 'restore', {'target_revision': body['target_revision']})
    return {**item.model_dump(), 'revision': version}


@router.post('/{identity}/check')
async def check(identity: str, request: Request, user=Depends(admin_auth.require)):
    store.require_active()
    body = await request.json()
    with store.connection() as db:
        row = store.get(db, identity)
        revision(body, row['revision'])
        item = resources.Resource.model_validate(json.loads(row['record']))
    url = resources.object_url(item.object_key)
    store.reserve_check(identity)
    result = {'revision': row['revision'], 'object_key': item.object_key, 'checked_at': news.now(), 'size_bytes': None}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8, connect=4), follow_redirects=False, trust_env=False) as client:
            response = await client.head(url)
        code = response.status_code
        state = 'accessible' if code == 200 else 'missing' if code == 404 else 'unconfirmed'
        size = response.headers.get('content-length', '')
        if state == 'accessible' and len(size) <= 20 and size.isascii() and size.isdigit() and 0 < int(size) <= 2**63 - 1:
            result['size_bytes'] = int(size)
        result.update(state=state, http_status=code)
    except httpx.HTTPError:
        result.update(state='unconfirmed', http_status=None)
    with store.connection(write=True) as db:
        db.execute('INSERT INTO management_audit(resource_id,revision,actor,operation,created_at,summary) VALUES(?,?,?,?,?,?)',
                   (identity, row['revision'], user['username'], 'check', result['checked_at'], json.dumps({'state': result['state']})))
    return result


async def management_error(request, error):
    return JSONResponse({'detail': error.message}, status_code=error.status)
