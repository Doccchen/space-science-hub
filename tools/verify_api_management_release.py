"""Production read-only management verification and a base-source search; no model calls."""
import json
import subprocess
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request,urlopen


def get(url):
    with urlopen(url,timeout=80) as response:return json.load(response)


def status(url):
    try:
        with urlopen(url,timeout=20) as response:return response.status
    except HTTPError as error:return error.code


def main():
    code='from backend import literature_config as c;import json;print(json.dumps(c.overview()))'
    view=json.loads(subprocess.check_output(['docker','exec','space-news-admin-1','python','-c',code]))
    assert view['initialized']
    rows=[{'provider':p['provider'],'status':p['status'],'enabled':p['applied']['config']['enabled'],
           'key_configured':p['draft']['key_configured'],'used_today':p['used_today']} for p in view['providers']]
    assert all(row['status']=='applied' for row in rows)
    public='https://8.137.164.100:8080'
    assert status(public+'/api/literature-config')==404
    assert status('http://127.0.0.1:8090/api/literature-config')==401
    request=Request(public+'/api/reader/search',data=json.dumps({'query':'grid fin aerodynamics','query_zh':'栅格舵'}).encode(),
                    headers={'Content-Type':'application/json','Origin':public})
    with urlopen(request,timeout=80) as response:search=json.load(response)
    assert search['papers'] and any(s['state']=='ok' for s in search['sources'])
    result={'providers':rows,'reader_config':get(public+'/api/reader/config'),
            'public_management_route':404,'private_unauthenticated_route':401,
            'search_records':len(search['papers']),'sources':search['sources'],'model_calls':0}
    print(json.dumps(result,ensure_ascii=True))


if __name__=='__main__':main()
