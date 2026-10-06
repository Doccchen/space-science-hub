"""Run on the server to add AI settings without printing or committing a key."""
import getpass
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path


def main():
    path=Path('/opt/space-news/.env')
    if not path.is_file():
        raise SystemExit('Missing /opt/space-news/.env; existing deployment required.')
    text=path.read_text()
    current={}
    for line in text.splitlines():
        if line.strip() and not line.lstrip().startswith('#') and '=' in line:
            name,value=line.split('=',1);current[name.strip()]=value.strip().strip('"\'')
    key=getpass.getpass('百炼 API Key（隐藏输入；留空保留已有值）：').strip() or current.get('DASHSCOPE_API_KEY','')
    if not re.fullmatch(r'[A-Za-z0-9._-]{8,256}',key):
        raise SystemExit('Key format invalid; no changes were made.')
    fields={'AI_ENABLED':'1','DASHSCOPE_API_KEY':key,
            'BAILIAN_WORKSPACE_ID':current.get('BAILIAN_WORKSPACE_ID','llm-ep9bqc9mnw50k8e0'),
            'BAILIAN_AGENT_ID':current.get('BAILIAN_AGENT_ID','aid-066ddd0b6e1e44d6bf7d620e0ac7c060'),
            'AI_CONFIG_VERSION':current.get('AI_CONFIG_VERSION','1'),'AI_COOKIE_SECURE':current.get('AI_COOKIE_SECURE','0'),
            'AI_TIMEOUT_SECONDS':current.get('AI_TIMEOUT_SECONDS','60'),'AI_CONCURRENCY':current.get('AI_CONCURRENCY','2'),
            'AI_VISITOR_DAILY_LIMIT':current.get('AI_VISITOR_DAILY_LIMIT','20'),'AI_IP_DAILY_LIMIT':current.get('AI_IP_DAILY_LIMIT','30'),
            'AI_SITE_DAILY_LIMIT':current.get('AI_SITE_DAILY_LIMIT','100'),'AI_DAILY_TOKEN_LIMIT':current.get('AI_DAILY_TOKEN_LIMIT','200000'),
            'AI_TOKEN_RESERVATION':current.get('AI_TOKEN_RESERVATION','20000')}
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup=path.with_name('.env.before-ai-'+stamp)
    shutil.copy2(path,backup);backup.chmod(0o600)
    lines=[line for line in text.splitlines() if line.split('=',1)[0].strip() not in fields]
    lines+=['']+[name+'='+value for name,value in fields.items()]
    staged=path.with_name('.env.ai-staging')
    fd=os.open(staged,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as handle:handle.write('\n'.join(lines)+'\n')
    staged.replace(path);path.chmod(0o600)
    print('AI settings saved; key hidden. Other environment settings preserved. Backup:',backup.name)


if __name__=='__main__':main()
