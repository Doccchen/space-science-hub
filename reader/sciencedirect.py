"""ScienceDirect Search V2 metadata adapter; no full text or unrestricted caching."""
class ScienceDirectError(ValueError):
    pass


async def fetch(query,client,key,insttoken='',count=10,timeout=18):
    from .discovery import paper
    headers={'X-ELS-APIKey':key,'Accept':'application/json'}
    if insttoken:headers['X-ELS-Insttoken']=insttoken
    response=await client.put('https://api.elsevier.com/content/search/sciencedirect',
                              headers=headers,json={'qs':query,'display':{'show':count,'offset':0}},
                              follow_redirects=False,timeout=timeout)
    if response.status_code in (401,403):
        raise ScienceDirectError('ScienceDirect Key 或机构访问权限不可用。')
    if 300<=response.status_code<400:
        raise ScienceDirectError('ScienceDirect 接口重定向已阻止。')
    response.raise_for_status()
    body=response.json()
    if not isinstance(body,dict) or not isinstance(body.get('results'),list):
        raise ScienceDirectError('ScienceDirect 返回格式无效，请核对接口权限。')
    rows=[]
    for item in body['results'][:count]:
        authors=item.get('authors') or []
        if not isinstance(authors,list):authors=[]
        rows.append(paper('ScienceDirect',item.get('title'),
            [a.get('name','') for a in authors if isinstance(a,dict)],
            item.get('publicationDate'),item.get('sourceTitle'),item.get('doi',''),
            url=item.get('uri',''),kind='期刊论文' if item.get('publicationType')=='Journal' else '其他文献'))
    return rows
