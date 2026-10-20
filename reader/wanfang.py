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
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and body.get('code') == 'AUTH_PAYMENT_FAILED':
        raise WanfangError('万方账户扣费失败，授权已暂停；请检查账户余额、账单或支付账户。')
    if response.status_code in (401, 403):
        raise WanfangError('万方 Key 无效或未开通文献检索权限。')
    if 300 <= response.status_code < 400:
        raise WanfangError('万方接口发生重定向，本次未发送到其他地址。')
    response.raise_for_status()
    if not isinstance(body, dict) or not isinstance(body.get('documents'), list):
        raise WanfangError('万方未返回有效文献列表，请核对接口权限与响应格式。')
    rows = []
    for doc in body['documents'][:12]:
        fields = doc.get('fields') if isinstance(doc, dict) else None
        # Current AI HUB replies can carry metadata in a typed Periodical
        # object while leaving the documented generic fields map empty.
        typed = doc.get('Periodical') if isinstance(doc, dict) else None
        if isinstance(typed, dict):
            fields = {**typed, **(fields if isinstance(fields, dict) else {})}
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
    if body['documents'] and not rows:
        raise WanfangError('万方返回了文献，但题录字段无法解析，请检查接口返回格式。')
    total = body.get('numFound', body.get('num_found', 0))
    if isinstance(total, int) and total > 0 and not body['documents']:
        raise WanfangError('万方报告命中但未返回题录，请核对接口权限或返回格式。')
    return rows
