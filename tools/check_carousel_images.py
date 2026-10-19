"""Check the live carousel's exact image URLs and decode every response."""
import concurrent.futures,io,json,urllib.request
from pathlib import Path
from bs4 import BeautifulSoup
from PIL import Image
BASE='https://8.137.164.100:8080'
def check(slide):
 result={'id':slide['id'],'url':slide['image']}
 try:
  with urllib.request.urlopen(BASE+slide['image'],timeout=20) as r:
   blob=r.read();result.update(status=r.status,bytes=len(blob),content_type=r.headers.get('Content-Type'))
  with Image.open(io.BytesIO(blob)) as im:
   result.update(format=im.format,size=im.size);im.load()
  result['ok']=True
 except Exception as error:result.update(ok=False,error=str(error))
 return result
with urllib.request.urlopen(BASE+'/',timeout=20) as r:soup=BeautifulSoup(r.read(),'html.parser')
slides=json.loads(soup.find(id='history-slides').string)
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(check,slides))
out=Path('artifacts/carousel-repair-20261019');out.mkdir(exist_ok=True);(out/'live-image-check.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(results,ensure_ascii=True,indent=2))
assert all(r['ok'] for r in results),'Live carousel has unreadable or missing image responses'
