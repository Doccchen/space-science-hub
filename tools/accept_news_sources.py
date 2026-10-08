"""Read-only source inventory and bounded real-body acceptance, without model calls."""
import argparse
import asyncio
import json
import os
import re
import ssl
import time
from pathlib import Path

from backend import news, news_context
from backend.bailian import AIError
from backend.news_context_store import Store
from backend.publisher_fetch import Publisher


async def run(args):
    with news.connect() as db:
        sources = db.execute('SELECT id,enabled FROM sources ORDER BY id').fetchall()
        inventory = []
        for source in sources:
            rows = db.execute('SELECT id,title,lang,published_at,original_url FROM articles WHERE source_id=? '
                              'ORDER BY id DESC LIMIT 3', (source['id'],)).fetchall()
            inventory.append({'source_id':source['id'],'enabled':bool(source['enabled']),
                'support':news_context.SOURCE_REGISTRY[source['id']]['status'],
                'samples':[dict(row) for row in rows]})
    if args.diagnose:
        ids = [int(value) for value in args.ids.split(',') if value]
        if not 1 <= len(ids) <= 3:
            raise ValueError('Diagnose at most 3 articles')
        results = []
        for article_id in ids:
            item,_,_,_ = news_context.snapshot(article_id)
            client = Publisher(item['source_id']); client.deadline = time.monotonic()+20
            cause = 'fetch_ok'
            try:
                _,mime = await asyncio.to_thread(client.get,item['original_url'])
            except ssl.SSLCertVerificationError:
                cause = 'certificate_verification_failed'
            except TimeoutError:
                cause = 'network_timeout'
            except ValueError as error:
                message = str(error)
                cause = message if re.fullmatch(r'Publisher HTTP \d{3}; no bypass attempted',message) or message in {
                    'Unreviewed NASA path','robots.txt disallows this material',
                    'robots.txt returned HTML; review required','Unexpected compression',
                    'Publisher resolved to non-public address','Publisher request budget reached'} else 'fetch_policy_rejected'
            except Exception as error:
                cause = type(error).__name__
            results.append({'article_id':article_id,'cause':cause,'requests':client.requests})
        print(json.dumps({'model_calls':0,'diagnostics':results})); return
    if not args.read:
        print(json.dumps({'model_calls':0,'sources':inventory},ensure_ascii=False)); return
    ids = [int(value) for value in args.ids.split(',') if value]
    if not 1 <= len(ids) <= 15 or len(set(ids)) != len(ids):
        raise ValueError('Select 1-15 distinct articles')
    service = news_context.ContextService(Store(Path('/data/news-source-acceptance.sqlite3')),enabled=True)
    report = {'model_calls':0,'samples':[]}
    try:
        for article_id in ids:
            try:
                result = await service.read(article_id)
                # Await already-running bounded reads; never start a duplicate on timeout.
                if result['read_status'] == 'pending' and service.tasks:
                    await asyncio.gather(*tuple(service.tasks.values()),return_exceptions=True)
                    result = await service.read(article_id)
                report['samples'].append(result)
            except AIError as error:
                report['samples'].append({'article_id':article_id,'read_status':error.code})
        path = Path(args.output); path.parent.mkdir(parents=True,exist_ok=True)
        with os.fdopen(os.open(path,os.O_WRONLY | os.O_CREAT | os.O_TRUNC,0o600),'w',encoding='utf-8') as handle:
            json.dump(report,handle,ensure_ascii=False,indent=2)
        print(json.dumps({'model_calls':0,'output':str(path),'samples':[
            {key:sample.get(key) for key in ('article_id','source_id','read_status','total_blocks','warnings')}
            for sample in report['samples']]},ensure_ascii=False))
    finally:
        await service.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--read',action='store_true')
    parser.add_argument('--diagnose',action='store_true')
    parser.add_argument('--ids',default='')
    parser.add_argument('--output',default='/data/news-source-acceptance-20261008.json')
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception:
        raise SystemExit('Source acceptance failed; inspect protected server state without printing credentials.') from None


if __name__ == '__main__': main()
