"""Wanfang AI HUB metadata adapter. No full-text downloads or credential logging."""
from urllib.parse import quote


class WanfangError(ValueError):
    pass


def values(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if isinstance(v, (str, int, float))]
    return [str(value)] if isinstance(value, (str, int, float)) else []


def first(value):
    return next(iter(values(value)), '')


async def fetch(query, client, key, timeout=18):
    from .discovery import paper
    # The AI HUB docs list an HTTP base; HTTPS was independently checked before
    # implementation. Never follow redirects with a credential-bearing request.
    response = await client.post('https://api.wfdata.com/openwanfang/getQuery',
        headers={'X-App-Key': key}, follow_redirects=False,timeout=timeout,
        json={'collections': ['OpenPeriodical'], 'query': query,
              'returned_fields': ['Id','Title','Creator','PublishYear','PeriodicalTitle',
                                  'Abstract','DOI','Type'], 'start': 0, 'rows': 12})
    if response.status_code in (401, 403):
        raise WanfangError('万方 Key 无效或未开通文献检索权限。')
    if 300 <= response.status_code < 400:
        raise WanfangError('万方接口发生重定向，本次未发送到其他地址。')
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict) or not isinstance(body.get('documents'), list):
        raise WanfangError('万方未返回有效文献列表，请核对接口权限与响应格式。')
    rows = []
    for doc in body['documents'][:12]:
        fields = doc.get('fields') if isinstance(doc, dict) else None
        if not isinstance(fields, dict):
            raise WanfangError('万方文献字段格式与接口说明不一致。')
        identity = first(fields.get('Id')) or first(doc.get('id'))
        title = first(fields.get('Title'))
        if not identity or not title:
            continue
        # We only request OpenPeriodical in this initial integration. HasFulltext
        # would describe availability in Wanfang, not public/open-access status.
        rows.append(paper('万方', title, values(fields.get('Creator')),
                          first(fields.get('PublishYear')), first(fields.get('PeriodicalTitle')),
                          first(fields.get('DOI')), first(fields.get('Abstract')),
                          'https://d.wanfangdata.com.cn/periodical/' + quote(identity, safe=''),
                          kind='期刊论文'))
    return rows
