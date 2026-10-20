"""Read public service state and perform one paper search, without model calls."""
import json
from pathlib import Path
from urllib.request import Request, urlopen

BASE = 'https://8.137.164.100:8080'


def get(path):
    with urlopen(BASE+path, timeout=80) as reply:
        return json.load(reply)


def main():
    status=get('/api/ai/status')
    health=get('/api/reader/health')
    config=get('/api/reader/config')
    query='grid fin aerodynamics'
    request=Request(BASE+'/api/reader/search',data=json.dumps({'query':query}).encode(),
                    headers={'Content-Type':'application/json','Origin':BASE})
    with urlopen(request,timeout=80) as reply:
        data=json.load(reply)
    assert data['query']==query and isinstance(data['papers'],list)
    assert {'Crossref','Semantic Scholar','NASA NTRS','arXiv'} <= {s['source'] for s in data['sources']}
    assert any(s['state']=='ok' for s in data['sources']), 'No search provider available'
    result={'reader_health':health,'knowledge_enabled':status['enabled'],
            'knowledge_message':status['message'],'topic_model_enabled':config['model_enabled'],
            'search_query':query,'papers':len(data['papers']),'sources':data['sources'],
            'model_calls':0}
    target=Path(__file__).resolve().parent/'verification.json'
    target.write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True))


if __name__=='__main__':
    main()
