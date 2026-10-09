"""Server-only reversible MCP pause; preserve public generation and provider settings."""
import json
import shutil
import subprocess
import time
import urllib.request
from datetime import datetime,timezone
from pathlib import Path

PROJECT = Path('/opt/space-news')


def get(path):
    with urllib.request.urlopen('http://127.0.0.1:18081'+path,timeout=5) as response:
        return json.load(response)


def restart():
    subprocess.run(['docker','compose','up','-d','--no-deps','--no-build','--pull','never','app'],cwd=PROJECT,check=True)
    for _ in range(45):
        try:
            return get('/api/health')
        except Exception:
            time.sleep(1)
    raise RuntimeError('App startup failed')


def main():
    container = json.loads(subprocess.check_output(['docker','inspect','space-news-app-1'],text=True))[0]
    labels = container['Config'].get('Labels') or {}
    project = labels.get('com.docker.compose.project')
    if not project or labels.get('com.docker.compose.service') != 'app':
        raise RuntimeError('Unreviewed app identity')
    matching = subprocess.check_output(['docker','ps','-aq','--filter','label=com.docker.compose.project='+project,
                                        '--filter','label=com.docker.compose.service=app'],text=True).splitlines()
    if len(matching) != 1 or not container['Id'].startswith(matching[0]):
        raise RuntimeError('Ambiguous Compose app identity')
    before = get('/api/news/88/agent-status')
    ai_before = get('/api/ai/status')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    evidence = Path('/root/news-agent-deployment-20261008') / ('inline-mode-'+stamp)
    evidence.mkdir(mode=0o700)
    target = PROJECT / '.env'
    saved = evidence / 'environment-before'
    shutil.copy2(target,saved)
    values = {'NEWS_MCP_ENABLED':'0','NEWS_MCP_CONTEXT_VERIFIED':'0','NEWS_MCP_PLUGIN_CODE':''}
    lines = [line for line in target.read_text().splitlines() if line.partition('=')[0].strip() not in values]
    try:
        target.write_text('\n'.join(lines+[name+'='+value for name,value in values.items()])+'\n')
        target.chmod(0o600)
        health = restart()
        after = get('/api/news/88/agent-status')
        if after['enabled'] != before['enabled'] or after['mcp_enabled'] or after['mcp_service_enabled'] or get('/api/ai/status') != ai_before:
            raise RuntimeError('Unexpected service state')
        report = {'mode':'backend_inline_context','mcp_enabled':False,'public_generation_enabled':after['enabled'],
                  'health':health,'evidence':str(evidence),'model_calls':0}
        (evidence/'result.json').write_text(json.dumps(report,indent=2))
        print(json.dumps(report))
    except BaseException:
        shutil.copy2(saved,target)
        restart()
        raise


if __name__ == '__main__': main()
