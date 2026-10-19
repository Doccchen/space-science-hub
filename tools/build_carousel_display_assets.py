"""Build smaller carousel derivatives and keep original images as fallbacks."""
from pathlib import Path
import json,re
from PIL import Image,ImageOps
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'web/index.html';text=p.read_text(encoding='utf-8')
match=re.search(r'(<script[^>]*id="history-slides"[^>]*>)([\s\S]*?)(</script>)',text);slides=json.loads(match[2])
report=[]
for slide in slides:
 old=slide['image']
 if not slide.get('variants'):
  original=slide.get('fallback_image') or old
  file=ROOT/'web'/original.split('?')[0].removeprefix('/assets/')
  with Image.open(file) as source:
   for size in [1800,960]:
    image=ImageOps.exif_transpose(source).convert('RGB');image.thumbnail((size,size),Image.Resampling.LANCZOS)
    target=ROOT/'web/carousel'/f'{slide["id"]}-{size}.webp';target.parent.mkdir(exist_ok=True);image.save(target,'WEBP',quality=86,method=6)
  slide['image']=f'/assets/carousel/{slide["id"]}-1800.webp'
  slide['mobile_image']=f'/assets/carousel/{slide["id"]}-960.webp'
  slide['fallback_image']=original
  if '等比例缩放并转为 WebP' not in slide.get('changes',''):slide['changes']=slide.get('changes','')+'；展示版本等比例缩放并转为 WebP，未裁切或补绘。'
 else:
  jpeg=slide.get('fallback_image') or old
  webp=next(v['path'] for v in slide['variants'] if v['path'].endswith('-2400.webp'))
  slide['image']=webp;slide['fallback_image']=jpeg
 report.append({'id':slide['id'],'before':(ROOT/'web'/old.split('?')[0].removeprefix('/assets/')).stat().st_size,'after':(ROOT/'web'/slide['image'].removeprefix('/assets/')).stat().st_size})
text=text[:match.start(2)]+json.dumps(slides,ensure_ascii=False,separators=(',',':'))+text[match.end(2):]
text=re.sub(r'(<link[^>]*rel="preload"[^>]*as="image"[^>]*href=")[^"]+',lambda m:m[1]+slides[0]['image'],text)
text=re.sub(r'(<img[^>]*class="space-cover-image"[^>]*src=")[^"]+',lambda m:m[1]+slides[0]['image'],text)
text=re.sub(r'history-carousel.js\?v=[^"\s]+','history-carousel.js?v=20261019-image-recovery',text)
text=text.replace('site-navigation.css?v=20261019-entry-cards','site-navigation.css?v=20261019-no-entries')
p.write_text(text,encoding='utf-8');(ROOT/'web/history-slides.json').write_text(json.dumps(slides,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'primary_before_bytes':sum(x['before'] for x in report),'primary_after_bytes':sum(x['after'] for x in report),'slides':report},ensure_ascii=True))
