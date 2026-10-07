"""Server-side bounded thumbnail discovery, status, withdrawal and confirmed image registration."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from backend import news, news_thumbnails as thumbnails


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('collect','status','register','withdraw','inspect','retry'))
    parser.add_argument('--limit',type=int,default=3)
    parser.add_argument('--article-id',type=int)
    parser.add_argument('--image-url')
    parser.add_argument('--credit')
    parser.add_argument('--rights-kind',choices=tuple(thumbnails.RIGHTS))
    parser.add_argument('--rights-reviewed',action='store_true')
    args=parser.parse_args()
    news.initialize()
    if args.mode=='collect':
        result=thumbnails.run_batch(args.limit)
    elif args.mode=='status':
        with news.connect() as db:
            result=[dict(row) for row in db.execute('SELECT article_id,state,credit,rights_kind,error FROM news_thumbnails ORDER BY attempted_at DESC LIMIT 30')]
    else:
        if not args.article_id:
            parser.error('--article-id required')
        with news.connect() as db:
            row=db.execute('SELECT * FROM articles WHERE id=?',(args.article_id,)).fetchone()
        if row is None:
            parser.error('Article not found')
        if args.mode=='inspect':
            result=thumbnails.diagnose(dict(row))
        elif args.mode=='retry':
            with news.connect() as db:
                prior=db.execute('SELECT state FROM news_thumbnails WHERE article_id=?',(args.article_id,)).fetchone()
            if prior and prior['state']=='withdrawn':parser.error('Withdrawn pictures require explicit reviewed registration')
            result=thumbnails.capture(dict(row))
        elif args.mode=='withdraw':
            with news.connect() as db:
                db.execute("UPDATE news_thumbnails SET state='withdrawn',attempts=3 WHERE article_id=?",(args.article_id,))
            result={'article_id':args.article_id,'state':'withdrawn'}
        else:
            if not args.rights_reviewed or not args.image_url or not args.credit or not args.rights_kind:
                parser.error('Register requires image URL, full credit, rights kind and explicit --rights-reviewed')
            result=thumbnails.store_picture(dict(row),{'source_url':args.image_url,'credit':args.credit,'rights_kind':args.rights_kind})
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
