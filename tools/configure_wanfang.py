"""Save the AI HUB APP_KEY through hidden input; optional one-query HTTPS verification."""
import argparse
import asyncio
import getpass
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def save_key(path, key):
    if not key or len(key)>4096 or any(c.isspace() or c in '\"\'`#' for c in key):
        raise ValueError('Key 格式无效，配置未修改。')
    text=path.read_text(encoding='utf-8-sig') if path.exists() else ''
    lines=[line for line in text.splitlines() if line.split('=',1)[0].strip()!='READER_WANFANG_API_KEY']
    staged=path.with_name('.env.reader.wanfang-staging')
    fd=os.open(staged,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as handle:
            handle.write('\n'.join(lines)+'\nREADER_WANFANG_API_KEY='+key+'\n')
        staged.replace(path)
        path.chmod(0o600)
    finally:
        staged.unlink(missing_ok=True)


async def check(key):
    import httpx
    from reader.wanfang import fetch
    async with httpx.AsyncClient(timeout=20,follow_redirects=False) as client:
        try:
            papers=await fetch('栅格舵',client,key)
        except Exception as error:
            from reader.wanfang import WanfangError
            print(str(error) if isinstance(error,WanfangError) else '万方连接检查未成功，Key 未输出；请核对网络、额度和平台权限。')
            return False
        print('万方连接成功，返回 '+str(len(papers))+' 条记录。Key 未输出。')
        return True


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true',help='Save and perform one authenticated metadata query')
    args=parser.parse_args()
    path=ROOT/'.env.reader'
    key=getpass.getpass('万方 AI HUB APP_KEY（隐藏输入）：').strip()
    try:save_key(path,key)
    except ValueError as error:raise SystemExit(str(error)) from None
    print('已保存到 .env.reader，不会写入前端或 Git。未初始化后台管理时，重启本地检索服务后生效；已初始化时请在后台管理 Key。')
    if args.check and not asyncio.run(check(key)):
        raise SystemExit(1)


if __name__=='__main__':
    main()
