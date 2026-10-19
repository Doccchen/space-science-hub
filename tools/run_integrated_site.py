"""Supervise three isolated local processes. No deployment or live collection."""
import argparse
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parent.parent


def envfile(path):
    result={}
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if line.startswith(('READER_', 'SEMANTIC_SCHOLAR_')) and '=' in line:
                name,value=line.split('=',1);result[name]=value.strip().strip('"')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--port',type=int,default=8878)
    parser.add_argument('--main-port',type=int,default=18820);parser.add_argument('--reader-port',type=int,default=18821)
    parser.add_argument('--reader-python',default=sys.executable,help='Optional Python environment for the paper search service')
    args=parser.parse_args();os.chdir(ROOT)
    data=ROOT/'data/integrated-preview';data.mkdir(parents=True,exist_ok=True)
    snapshot=data/'news.sqlite3';source=ROOT/'data/news.sqlite3'
    if source.exists() and not snapshot.exists():
        with sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True) as original,sqlite3.connect(snapshot) as target:original.backup(target)
    site_env={**os.environ,'NEWS_DB_PATH':str(snapshot),'MANAGEMENT_DB_PATH':str(data/'management.sqlite3'),
              'COLLECT_ENABLED':'0','GOVERNMENT_FULLTEXT_AUTO':'0','NEWS_THUMBNAILS_ENABLED':'0','AI_ENABLED':'0'}
    reader_env={**os.environ,**envfile(ROOT/'.env.reader'),'READER_DATA_DIR':str(ROOT/'data/temporary-reader'),
                'READER_PUBLIC_ORIGIN':f'http://127.0.0.1:{args.port}','READER_COOKIE_SECURE':'0'}
    gateway_env={**os.environ,'SITE_MAIN_UPSTREAM':f'http://127.0.0.1:{args.main_port}',
                 'SITE_READER_UPSTREAM':f'http://127.0.0.1:{args.reader_port}'}
    processes=[]
    def stop(*unused):
        for child in reversed(processes):
            if child.poll() is None:child.terminate()
        for child in processes:
            try:child.wait(timeout=8)
            except subprocess.TimeoutExpired:child.kill();child.wait()
    signal.signal(signal.SIGINT,lambda *_:sys.exit(0))
    try:
        for module,port,environment in [('backend.app:app',args.main_port,site_env),('reader.app:app',args.reader_port,reader_env),('backend.site_gateway:app',args.port,gateway_env)]:
            executable=args.reader_python if module=='reader.app:app' else sys.executable
            processes.append(subprocess.Popen([executable,'-m','uvicorn',module,'--host','127.0.0.1','--port',str(port),'--workers','1','--no-proxy-headers'],
                env=environment,cwd=ROOT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0))
        for _ in range(60):
            if any(child.poll() is not None for child in processes):raise RuntimeError('A local service failed; see output above')
            try:
                urllib.request.urlopen(f'http://127.0.0.1:{args.port}/api/reader/health',timeout=1)
                urllib.request.urlopen(f'http://127.0.0.1:{args.port}/api/health',timeout=1)
                break
            except Exception:time.sleep(.5)
        else:raise RuntimeError('Local services did not become ready')
        print(f'INTEGRATED READY http://127.0.0.1:{args.port} (local preview; collection disabled)',flush=True)
        while all(child.poll() is None for child in processes):time.sleep(.5)
    finally:stop()


if __name__=='__main__':main()
