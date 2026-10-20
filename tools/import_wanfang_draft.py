"""Transfer a locally configured APP_KEY through SSH stdin into encrypted admin storage."""
import json
import shlex
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    from tools.run_integrated_site import envfile
    key=envfile(ROOT/'.env.reader').get('READER_WANFANG_API_KEY','')
    if not key:raise SystemExit('Local Wanfang key is not configured; no transfer performed.')
    inner='''import json,sys
from backend import literature_config as c,management_store as s
try:
 incoming=json.load(sys.stdin)['key']
 c.required('wanfang')
 with s.connection() as d:
  state=c.state(d,'wanfang');row=c.version(d,'wanfang',state['draft']);old=c.decrypt(row);values=c.public(row)['config']
 if old['key'] and old['key']!=incoming:
  print(json.dumps({'ok':False,'message':'A different key is already configured; no overwrite performed.'}));sys.exit(2)
 if old['key']==incoming:
  print(json.dumps({'ok':True,'state':'already_configured','version':row['id']}));sys.exit(0)
 config={name:values[name] for name in c.DEFAULT}
 result=c.save('wanfang',{'revision':state['revision'],'config':config,'new_key':incoming,'new_insttoken':'','clear_key':False,'clear_insttoken':False},'authorized-server-deployment')
 print(json.dumps({'ok':True,'state':'encrypted_draft_saved','version':result['version'],'enabled':config['enabled']}))
except Exception:
 print(json.dumps({'ok':False,'message':'Credential import failed; key was not printed.'}));sys.exit(1)
'''
    # Neither the SSH command line nor the remote process arguments contain the key.
    outer="import subprocess,sys; r=subprocess.run(['docker','exec','-i','space-news-admin-1','python','-c',"+repr(inner)+"],input=sys.stdin.buffer.read(),stdout=subprocess.PIPE,stderr=subprocess.PIPE);sys.stdout.buffer.write(r.stdout);sys.exit(r.returncode)"
    command=['ssh','-i',str(ROOT.parent/'GPT.pem'),'-o','BatchMode=yes','-o','ConnectTimeout=12',
             'root@8.137.164.100','python3 -c '+shlex.quote(outer)]
    result=subprocess.run(command,input=json.dumps({'key':key}).encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if result.stdout:
        try:
            value=json.loads(result.stdout)
            assert key not in result.stdout.decode()
            print(json.dumps(value))
            OUT=ROOT/'artifacts/api-management-release-20261020'
            (OUT/'key-import.json').write_text(json.dumps(value,indent=2))
        except (ValueError,AssertionError):raise SystemExit('Unexpected import response; no credential output emitted.') from None
    if result.returncode:raise SystemExit('Import did not complete. No key was printed.')


if __name__=='__main__':main()
