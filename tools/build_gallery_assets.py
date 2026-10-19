"""Create reproducible local display derivatives; preserve original evidence."""
import hashlib
import json
import argparse
import urllib.request
from pathlib import Path
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'artifacts/landspace-gallery-20261012'
SELECTION = [
    (8, 'sunset', ['把遥远的想象，', '立在大地之上。'], '火箭静立在晚霞与发射工位之间。', '一枚火箭竖立在发射工位，后方是粉橙色晚霞和远处山脉', '56% 50%'),
    (15, 'liftoff', ['点燃此刻，', '向更远处出发。'], '火焰照亮箭体，远行从此刻开始。', '火箭从发射工位升起，底部喷出明亮火焰', '50% 50%'),
    (4, 'desert', ['在辽阔天地间，', '寻找新的高度。'], '荒漠与远山之间，试验箭向上探索。', '试验箭在荒漠上空离地升起，底部有细长喷流，后方是连绵山脉', '50% 50%'),
    (6, 'horizon', ['出发之前，', '天地已经铺开。'], '宽阔天空下，发射工位等待下一次出发。', '横向延展的天空与大地之间是火箭和发射工位', '53% 50%'),
    (17, 'engine', ['远行的力量，', '藏在每一处细节。'], '走近喷焰与箭底结构，看见工程的力量。', '火箭底部结构与喷出的明亮火焰近景', '50% 50%'),
]
EXPANSION = [
    (9, 'dusk', ['天色渐深，', '远行仍在准备。'], '暮色中的火箭与发射工位。', '火箭竖立在粉紫色暮色下的发射工位', '50% 50%'),
    (11, 'nose', ['抬头看见，', '梦想的轮廓。'], '走近箭体上部，观察整流罩与外部结构。', '火箭上部整流罩和箭体外部结构的近景', '50% 50%'),
    (12, 'distance', ['从一束火光，', '走向辽阔天空。'], '远处的发射工位被火焰与烟云照亮。', '火箭从远处工位升空，喷流与烟云向地面扩散', '50% 50%'),
    (18, 'assembly', ['每一次出发，', '从这里开始。'], '厂房内，箭体与发动机结构依次展开。', '宽阔厂房中排列着箭体部件与发动机结构', '50% 50%'),
    (20, 'workshop', ['沿着工程的长廊，', '走近远行的起点。'], '沿厂房通道，观看两侧的箭体部件。', '明亮厂房里的绿色通道，两旁是箭体部件', '50% 50%'),
    (21, 'hardware', ['向上的力量，', '有清晰的形状。'], '厂房中的金属结构与发动机喷管。', '厂房里安放着带金属框架和喷管的发动机组件', '50% 50%'),
    (26, 'testbed', ['把想象落到实处，', '把细节做到深处。'], '试验设施内的发动机结构与工作平台。', '发动机置于室内试验设施中，周围有平台管线与工作人员', '50% 50%'),
]
ORDER = [8, 6, 9, 11, 4, 12, 15, 17, 18, 20, 21, 26]
LABELS = {9:'暮色工位', 11:'箭体上部', 12:'升空远景', 18:'总装厂房', 20:'工程长廊', 21:'发动机组件', 26:'试验设施'}
MOBILE_POSITION = {8:'27% 50%', 6:'59% 50%', 17:'75% 50%'}

def expand_originals():
    evidence = json.loads((EVIDENCE/'candidates.json').read_text(encoding='utf-8'))
    selected_path = EVIDENCE/'selected-originals.json'
    records = json.loads(selected_path.read_text(encoding='utf-8'))
    existing = {r['preview_number'] for r in records}
    official = {r['url'] for r in evidence['candidates']}
    for number, _, _, description, _, _ in EXPANSION:
        if number in existing:
            continue
        url = evidence['previews'][number-1]['url'].split('?')[0]
        assert url in official and url.startswith('https://offical-static.landspace.com/')
        filename = EVIDENCE/('original-'+url.rsplit('/',1)[1])
        if not filename.exists():
            with urllib.request.urlopen(url, timeout=45) as response:
                filename.write_bytes(response.read())
        photo = Image.open(filename)
        blob = filename.read_bytes()
        records.append({'url':url, 'local_path':filename.as_posix(), 'source':evidence['source'],
                        'preview_number':number, 'title':description, 'credit':'蓝箭航天 / LANDSPACE',
                        'rights_status':'官网公开下载；未见开放许可声明，网站公开展示授权待核',
                        'event_identification':'仅描述可见画面，不推断型号、任务或拍摄日期',
                        'width':photo.width, 'height':photo.height, 'bytes':len(blob),
                        'sha256':hashlib.sha256(blob).hexdigest()})
        selected_path.write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Retrieved official original:', number, photo.size, flush=True)

def main():
    originals = {x['preview_number']: x for x in json.loads((EVIDENCE/'selected-originals.json').read_text(encoding='utf-8'))}
    destination = ROOT/'web/gallery'
    destination.mkdir(exist_ok=True)
    slides = []
    selection = {entry[0]: entry for entry in SELECTION+EXPANSION}
    for number in ORDER:
        number, slug, title, description, alt, position = selection[number]
        record = originals[number]
        original = EVIDENCE / Path(record['local_path']).name
        assert hashlib.sha256(original.read_bytes()).hexdigest() == record['sha256'], original
        photo = ImageOps.exif_transpose(Image.open(original)).convert('RGB')
        assert photo.size == (record['width'], record['height'])
        variants = []
        for width, quality in [(2400, 86), (1200, 84), (320, 78)]:
            width = min(width, photo.width)  # Never enlarge smaller official originals.
            height = round(width * photo.height / photo.width)
            image = photo.resize((width, height), Image.Resampling.LANCZOS)
            for extension in ('webp', 'jpg'):
                name = f'landspace-{slug}-{width}.{extension}'
                image.save(destination/name, quality=quality, **({'optimize': True, 'progressive': True} if extension == 'jpg' else {'method': 6}))
                blob = (destination/name).read_bytes()
                variants.append({'path': '/assets/gallery/'+name, 'width': width, 'height': height,
                                 'bytes': len(blob), 'sha256': hashlib.sha256(blob).hexdigest()})
        slides.append({'id': 'landspace-'+slug, 'image': variants[0]['path'], 'fallback_image': variants[1]['path'],
                       'width': variants[0]['width'], 'height': variants[0]['height'],
                       'mobile_image': variants[2]['path'], 'mobile_fallback_image': variants[3]['path'],
                       'thumbnail': variants[4]['path'], 'label': LABELS.get(number, record['title']), 'title': title,
                       'description': description, 'alt': alt, 'credit': record['credit'],
                       'source_url': record['source'], 'original_image_url': record['url'],
                       'original_sha256': record['sha256'], 'rights_status': 'pending', 'rights_evidence': '',
                       'object_position_desktop': position, 'object_position_mobile': MOBILE_POSITION.get(number,'50% 50%'),
                       'changes': '等比例缩放与压缩；无补绘、增清或文件裁切。独立画廊默认与完整图模式均保留全图。',
                       'variants': variants})
    (ROOT/'web/gallery-slides.json').write_text(json.dumps(slides, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps([{s['id']: [(v['width'], v['bytes']) for v in s['variants'][:4]]} for s in slides]))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--download-expansion', action='store_true')
    if parser.parse_args().download_expansion:
        expand_originals()
    main()
