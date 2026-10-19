import json
from pathlib import Path
from bs4 import BeautifulSoup
from PIL import Image


def test_runtime_slides_match_asset_catalog_and_all_image_sources_exist():
    root=Path('web')
    soup=BeautifulSoup((root/'index.html').read_text(encoding='utf-8'),'html.parser')
    slides=json.loads(soup.find(id='history-slides').string)
    assert slides==json.loads((root/'history-slides.json').read_text(encoding='utf-8'))
    assert len(slides)==12
    for slide in slides:
        assert slide['image'].endswith('.webp')
        assert slide['fallback_image']!=slide['image']
        for field in ['image','mobile_image','fallback_image']:
            url=slide[field].split('?')[0]
            assert url.startswith('/assets/')
            path=root/url.removeprefix('/assets/')
            assert path.is_file(),(slide['id'],field)
            with Image.open(path) as image:image.verify()
        assert (root/slide['image'].removeprefix('/assets/')).stat().st_size<500_000
    assert not soup.select('.section-entries')
