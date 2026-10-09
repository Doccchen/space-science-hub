"""Fixed-file news release; never packages unrelated frontend changes or credentials."""
import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = 'ef80d98c1c573aa8da85a2ec5c25a5c8d4745636'
BASELINE_OVERRIDES = {'backend/review_capture.py':'565d2a6','backend/reading.py':'565d2a6','backend/app.py':'742f131','backend/ai.py':'742f131'}
FILES = ['backend/app.py','backend/ai.py','backend/publisher_fetch.py',
         'backend/review_capture.py','backend/reading.py',
         'backend/news_agent.py','backend/news_agent_client.py','backend/news_context.py',
         'backend/news_context_store.py','backend/news_mcp.py','requirements.txt',
         'backend/news_limits.py','backend/news_limits_admin.py',
         'web/news-reader.js','web/news-ui.js','web/news-agent.js','web/news-agent.css',
         'tools/news_agent_operator.py','tools/news_agent_server_info.py','tools/probe_news_agent.py',
         'tools/probe_news_agent_mcp.py','tools/probe_news_agent_inline.py',
         'tools/probe_news_mcp.py','tools/news_mcp_scope_status.py','tools/accept_news_sources.py',
         'tools/migrate_news_usage.py','tools/news_limits_admin_overlay.py']


def main():
    files = {name:(ROOT / name).read_bytes().replace(b'\r\n',b'\n') for name in FILES}
    for path in (ROOT / 'tests').rglob('*'):
        if path.is_file() and '__pycache__' not in path.parts:
            name = path.relative_to(ROOT).as_posix()
            files[name] = path.read_bytes()
    baselines = {}
    for name in FILES:
        reference = BASELINE_OVERRIDES.get(name,BASELINE)
        result = subprocess.run(['git','show',reference + ':' + name],cwd=ROOT,capture_output=True)
        if result.returncode == 0:
            baselines[name] = hashlib.sha256(result.stdout.replace(b'\r\n',b'\n')).hexdigest()
    manifest = {'baseline':BASELINE,'baseline_overrides':BASELINE_OVERRIDES,
                'files':[{'path':name,'sha256':hashlib.sha256(data).hexdigest(),
                                             'bytes':len(data)} for name,data in sorted(files.items())],
                'existing_baselines':baselines, 'public_generation_enabled':False}
    files['news-agent-manifest.json'] = (json.dumps(manifest,indent=2)+'\n').encode()
    output = ROOT / 'artifacts/packages/news-agent-release.tar.gz'
    output.parent.mkdir(parents=True,exist_ok=True)
    with tarfile.open(output,'w:gz') as archive:
        for name,data in sorted(files.items()):
            info = tarfile.TarInfo(name); info.size=len(data); info.mode=0o644
            archive.addfile(info,io.BytesIO(data))
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.sha256').write_text(digest+'\n')
    print(json.dumps({'archive':str(output),'sha256':digest,'files':len(manifest['files'])}))


if __name__ == '__main__':
    main()
