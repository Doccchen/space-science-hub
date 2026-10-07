"""Explicit historical NASA full-text image backfill; existing rights checks stay in effect."""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from backend import news, reading, news_thumbnails


def inventory():
    with news.connect() as db:
        rows=db.execute("""SELECT a.* FROM articles a
            WHERE a.source_id='nasa' AND news_is_excluded(a.source_id,a.title,a.original_url)=0
            ORDER BY a.published_at ASC,a.id ASC""").fetchall()
        public=reading.public_rows(db,rows)
        states={row['article_id']:dict(row) for row in db.execute('SELECT article_id,state,attempts FROM news_thumbnails')}
    pending=[]
    counts=Counter()
    for item,record in zip(rows,public):
        if record['reading_mode']!='full_text':continue
        counts['full_text']+=1
        prior=states.get(item['id'],{})
        if prior.get('state')=='withdrawn':
            counts['withdrawn']+=1
        elif record.get('thumbnail'):
            counts['with_image']+=1
        else:
            pending.append({**dict(item),'previous_state':prior.get('state','not_attempted')})
    return counts,pending


def run(max_articles=100,apply=False,progress=None):
    if type(max_articles) is not int or not 1<=max_articles<=500:
        raise ValueError('max-articles must be 1-500')
    counts,pending=inventory()
    selected=pending[:max_articles]
    report={'mode':'backfill' if apply else 'inventory','nasa_full_text':counts['full_text'],
            'already_with_image':counts['with_image'],'withdrawn_skipped':counts['withdrawn'],
            'missing_images':len(pending),'selected_ids':[item['id'] for item in selected],
            'deferred':max(0,len(pending)-len(selected))}
    if not apply:return report
    results=[]
    # Snapshot once: an unconfirmed/failed article is attempted once per invocation,
    # rather than repeatedly selecting it and starving older articles.
    for item in selected:
        with news.connect() as db:
            current=db.execute('SELECT * FROM articles WHERE id=?',(item['id'],)).fetchone()
            prior=db.execute('SELECT state FROM news_thumbnails WHERE article_id=?',(item['id'],)).fetchone()
            record=reading.public_rows(db,[current])[0] if current else None
        if not record or record['reading_mode']!='full_text' or not news_thumbnails.eligible(dict(current)):
            result={'article_id':item['id'],'state':'skipped','reason':'no_longer_public_full_text'}
        elif prior and prior['state']=='withdrawn':
            result={'article_id':item['id'],'state':'skipped','reason':'withdrawn'}
        elif record.get('thumbnail'):
            result={'article_id':item['id'],'state':'skipped','reason':'already_with_image'}
        else:
            # This explicit operation retries historical failures regardless of the
            # scheduler cooldown, while capture still verifies the source/credit/rights.
            result=news_thumbnails.capture(dict(current))
        results.append(result)
        if progress:progress(result)
    report['results']=results
    report['outcomes']=dict(Counter(item['state'] for item in results))
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true',help='Download and save confirmed images; otherwise report only')
    parser.add_argument('--max-articles',type=int,default=100)
    args=parser.parse_args()
    progress=lambda result:print(json.dumps(result,ensure_ascii=False),flush=True)
    try:
        report=run(args.max_articles,args.apply,progress if args.apply else None)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
