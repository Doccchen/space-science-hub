"""Validate and stage a fixed-file release, then add only AI environment keys to Compose."""
import argparse
import hashlib
import json
import re
import tarfile
from pathlib import Path

FILES=['backend/app.py','backend/ai.py','backend/bailian.py','web/index.html','web/studio.js',
       'web/glass-theme.js','web/ai.css','web/ai-ui.js','tests/test_ai.py']
ENV={
 'AI_ENABLED':'0','DASHSCOPE_API_KEY':'','BAILIAN_WORKSPACE_ID':'llm-ep9bqc9mnw50k8e0',
 'BAILIAN_AGENT_ID':'aid-066ddd0b6e1e44d6bf7d620e0ac7c060','AI_CONFIG_VERSION':'1',
 'AI_DB_PATH':'/data/ai.sqlite3','AI_COOKIE_SECURE':'0','AI_TIMEOUT_SECONDS':'60','AI_CONCURRENCY':'2',
 'AI_VISITOR_DAILY_LIMIT':'20','AI_IP_DAILY_LIMIT':'30','AI_SITE_DAILY_LIMIT':'100',
 'AI_DAILY_TOKEN_LIMIT':'200000','AI_TOKEN_RESERVATION':'20000'}


def compose_patch(text):
    # Existing server configuration is retained; only app.environment AI keys are managed.
    text=text.replace('\r\n','\n')
    app=re.search(r'(?ms)^  app:\n.*?(?=^  [A-Za-z][\w-]*:|\Z)',text)
    if not app:raise ValueError('app_service_missing')
    environment=re.search(r'(?m)^    environment:\n(?:^      [^\n]*\n)+',app.group())
    if not environment:raise ValueError('app_environment_shape_unknown')
    original=environment.group()
    lines=[line for line in original.splitlines() if line.strip().split(':',1)[0] not in ENV]
    for key,value in ENV.items():
        lines.append('      '+key+': '+(value if key=='AI_DB_PATH' else '${'+key+':-'+value+'}'))
    begin=app.start()+environment.start();end=app.start()+environment.end()
    return text[:begin]+'\n'.join(lines)+'\n'+text[end:]


def stage(archive,directory):
    with tarfile.open(archive,'r:gz') as tar:
        members=tar.getmembers()
        assert len(members)==len(FILES)+1 and {m.name for m in members}==set(FILES+['manifest.json'])
        assert all(m.isfile() and m.size<500000 for m in members)
        content={m.name:tar.extractfile(m).read() for m in members}
    manifest=json.loads(content['manifest.json'])
    assert len(manifest['files'])==len(FILES) and {item['path'] for item in manifest['files']}==set(FILES)
    for item in manifest['files']:
        assert hashlib.sha256(content[item['path']]).hexdigest()==item['sha256']
    for name,data in content.items():
        path=directory/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);path.chmod(0o644)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--archive',type=Path);parser.add_argument('--stage',type=Path)
    parser.add_argument('--compose',type=Path);parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.archive and args.stage:stage(args.archive,args.stage)
    if args.compose and args.output:args.output.write_text(compose_patch(args.compose.read_text()),encoding='utf-8')
