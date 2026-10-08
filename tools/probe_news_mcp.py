"""Server operator probes public MCP TLS using protected keys; logs metadata only."""
import json
import time
from pathlib import Path

import httpx

from backend import ai_config, news_agent


def main():
    settings = news_agent.Settings.environment()
    cipher = ai_config.cipher()
    scope = json.loads(Path('/data/news-mcp-preflight.json').read_text())
    if scope['expires'] <= time.time():
        raise SystemExit('Preflight expired; create a new bounded scope')
    headers = {'Authorization':'Bearer ' + settings.mcp_key,
               'X-News-Context':cipher.decrypt(scope['context'].encode()).decode(),
               'Accept':'application/json, text/event-stream'}
    endpoint = 'https://8.137.164.100/api/news-mcp/mcp'
    report = {'model_calls':0, 'article_id':scope['article_id']}
    with httpx.Client(timeout=30, trust_env=False) as client:
        def call(identity, method, params, request_headers=None):
            reply = client.post(endpoint, headers=request_headers or headers,
                                json={'jsonrpc':'2.0','id':identity,'method':method,'params':params})
            reply.raise_for_status()
            return reply.json()['result']
        initialized = call(1,'initialize',{'protocolVersion':'2025-06-18','capabilities':{},
                                         'clientInfo':{'name':'news-preflight','version':'1'}})
        report['protocol_version'] = initialized['protocolVersion']
        tools = call(2,'tools/list',{})['tools']
        report['tools'] = [tool['name'] for tool in tools]
        result = call(3,'tools/call',{'name':'read_news','arguments':{'article_id':scope['article_id']}})['structuredContent']
        if result['read_status'] != 'full':
            raise SystemExit('Scoped body unavailable: ' + result['read_status'])
        report['read_status'] = result['read_status']
        report['blocks'] = len(result['blocks'])
        wrong = call(4,'tools/call',{'name':'read_news','arguments':{'article_id':scope['article_id']+1}})['structuredContent']
        assert wrong['read_status'] == 'blocked'
        report['cross_article_blocked'] = True
        absent = call(5,'tools/call',{'name':'read_news','arguments':{'article_id':scope['article_id']}},
                      {'Authorization':headers['Authorization'],'Accept':headers['Accept']})['structuredContent']
        assert absent['read_status'] == 'blocked'
        report['missing_scope_blocked'] = True
    print(json.dumps(report))


if __name__ == '__main__':
    main()
