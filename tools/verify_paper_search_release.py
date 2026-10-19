"""Post-deployment HTTPS smoke checks: one model extraction and one paper search."""
import json,urllib.request
from pathlib import Path
BASE='https://8.137.164.100:8080'
def get(path):
    with urllib.request.urlopen(BASE+path,timeout=20) as response:return json.load(response)
def post(path,data):
    request=urllib.request.Request(BASE+path,data=json.dumps(data).encode(),headers={'Content-Type':'application/json','Origin':BASE})
    with urllib.request.urlopen(request,timeout=80) as response:return json.load(response)
health=get('/api/reader/health');assert health['service']=='paper-search'
config=get('/api/reader/config');assert config['model_enabled']
analysis=post('/api/reader/analyze',{'text':'新闻提到绳网回收技术，想了解捕获过程与动力学。'})
assert analysis['topics']
result=post('/api/reader/search',{'query':analysis['topics'][0]['query']})
assert any(s['state']=='ok' for s in result['sources'])
assert result['papers'],'No live records returned'
request=urllib.request.Request(BASE+'/api/reader/search',data=b'{"query":"net capture"}',headers={'Content-Type':'application/json','Origin':'https://untrusted.example'})
try:
    urllib.request.urlopen(request,timeout=20)
    raise AssertionError('Cross-site request accepted')
except urllib.error.HTTPError as error:assert error.code==403
summary={'public':BASE+'/reader/','health':health,'model_enabled':config['model_enabled'],'analysis_method':analysis['method'],
         'topics':analysis['topics'],'sources':result['sources'],'papers':len(result['papers']),
         'examples':[{'title':p['title'],'doi':p['doi']} for p in result['papers'][:3]],'cross_origin_blocked':True}
Path(__file__).with_name('verification.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
print(json.dumps(summary,ensure_ascii=True))
