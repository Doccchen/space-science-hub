"""Wanfang AI HUB metadata adapter. No full-text downloads or credential logging."""
import json
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


LIBRARIES = {
    'periodical':['OpenPeriodical'], 'thesis':['OpenThesis'], 'conference':['OpenConference'],
    'patent':['OpenPatent'], 'papers':['OpenPeriodical','OpenThesis','OpenConference'],
    'all':['OpenPeriodical','OpenThesis','OpenConference','OpenPatent'],
}
TYPES = {'Periodical':('期刊论文','periodical'), 'Thesis':('学位论文','thesis'),
         'Conference':('会议论文','conference'), 'Patent':('专利','patent')}


def request_options(query, options=None):
    """Compile explicit, escaped fields rather than claiming the website's private subject algorithm."""
    if options is None:
        return {'collections':['OpenPeriodical'],'query':query,'start':0,'rows':12}
    field=options.get('field','topic');library=options.get('library','papers')
    order=options.get('sort','relevance');page=options.get('page',1);size=options.get('page_size',20)
    if field not in {'topic','title','all'} or library not in LIBRARIES or order not in {'relevance','date'}:
        raise WanfangError('万方检索条件无效。')
    if type(page) is not int or not 1<=page<=1000 or type(size) is not int or size not in (10,20,50):
        raise WanfangError('万方分页参数无效。')
    term=json.dumps(query,ensure_ascii=False)
    expression={'topic':f'(Title:{term} OR KeywordForSearch:{term} OR Abstract:{term})',
                'title':f'Title:{term}', 'all':term}[field]
    low,high=options.get('year_from'),options.get('year_to')
    if any(v is not None and (type(v) is not int or not 1900<=v<=2100) for v in (low,high)) or (low and high and low>high):
        raise WanfangError('万方年份范围无效。')
    if low or high:expression=f'({expression}) AND PublishYear:[{low or "*"} TO {high or "*"}]'
    sorts=[{'by':'score','order':'DESC'}] if order=='relevance' else [{'by':'PublishYear','order':'DESC'},{'by':'score','order':'DESC'}]
    return {'collections':LIBRARIES[library],'query':expression,'start':(page-1)*size,'rows':size,'sort':{'sorts':sorts}}


def parse_page(body, options=None):
    from .discovery import paper
    if not isinstance(body,dict) or not isinstance(body.get('documents'),list):
        raise WanfangError('万方未返回有效文献列表，请核对接口权限与响应格式。')
    page=(options or {}).get('page',1);size=(options or {}).get('page_size',12)
    rows=[]
    for doc in body['documents'][:size]:
        if not isinstance(doc,dict):raise WanfangError('万方文献字段格式与接口说明不一致。')
        fields=doc.get('fields');resource=doc.get('resourceType') or doc.get('resource_type') or 'Periodical'
        typed=doc.get(resource)
        if isinstance(typed,dict):fields={**typed,**(fields if isinstance(fields,dict) else {})}
        if not isinstance(fields,dict) or resource not in TYPES:
            raise WanfangError('万方文献类型或字段格式暂不支持。')
        identity=first(fields.get('Id')) or first(doc.get('id'));title=first(fields.get('Title'))
        if not identity or not title:continue
        kind,path=TYPES[resource]
        venue=first(fields.get('PeriodicalTitle')) or first(fields.get('MeetingTitle')) or first(fields.get('OriginalOrganization')) or first(fields.get('Applicant'))
        row=paper('万方',title,values(fields.get('Creator') or fields.get('Inventor')),
                  first(fields.get('PublishYear')),venue,first(fields.get('DOI')),first(fields.get('Abstract')),
                  'https://d.wanfangdata.com.cn/'+path+'/'+quote(identity,safe=''),kind=kind)
        row['provider_id']=identity;row['source_rank']=(page-1)*size+len(rows)+1;rows.append(row)
    if body['documents'] and not rows:raise WanfangError('万方返回了文献，但题录字段无法解析，请检查接口返回格式。')
    total=body.get('numFound',body.get('num_found'))
    if isinstance(total,str) and total.isdigit():total=int(total)
    if type(total) is not int or total<0:total=None
    if total and not body['documents'] and (page-1)*size<total:
        raise WanfangError('万方报告命中但未返回题录，请核对接口权限或返回格式。')
    return {'papers':rows,'total':total,'page':page,'page_size':size,
            'has_more':page*size<total if total is not None else len(rows)==size,
            'pagination_supported':options is not None,'order':'provider','options':options}


async def fetch_page(query, client, key, timeout=18, options=None):
    payload=request_options(query,options)
    if options is None:payload['returned_fields']=['Id','Title','Creator','PublishYear','PeriodicalTitle','Abstract','DOI','Type']
    # The AI HUB docs list an HTTP base; HTTPS was independently checked before
    # implementation. Never follow redirects with a credential-bearing request.
    response = await client.post('https://api.wfdata.com/openwanfang/getQuery',
        headers={'X-App-Key': key}, follow_redirects=False,timeout=timeout,
        json=payload)
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
    return {**parse_page(body,options),'provider_query':payload['query'],'collections':payload['collections']}


async def fetch(query, client, key, timeout=18):
    return (await fetch_page(query,client,key,timeout))['papers']
