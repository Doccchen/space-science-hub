"""Materialize the user-authorized catalog without introductions.

Only thumbnails are copied; original PDFs and candidate drafts stay offline.
"""
import json
import shutil
from pathlib import Path

from backend.resources import Resource

ROOT = Path(__file__).resolve().parent.parent


def main():
    candidates = json.loads((ROOT / 'docs/research/resources-preparation/resources.candidates.json').read_text(encoding='utf-8'))
    covers = ROOT / 'web/resource-covers'
    covers.mkdir(parents=True, exist_ok=True)
    items = []
    for candidate in candidates:
        if not candidate['object_key']:
            continue
        item = {key: value for key, value in candidate.items() if key in Resource.model_fields}
        item.update(published=True, description_short='', description='', source_note='', cover_key=None,
                    updated_at='2026-10-05', cover_asset=None)
        if candidate['review']['cover_status'] == 'visually_checked_candidate':
            filename = candidate['id'] + '.jpg'
            shutil.copyfile(ROOT / 'artifacts/resources-preparation' / filename, covers / filename)
            item['cover_asset'] = filename
        items.append(Resource.model_validate(item).model_dump())
    assert len(items) == 28 and sum(item['cover_asset'] is not None for item in items) == 24
    (ROOT / 'content/resources.json').write_text(json.dumps(items, ensure_ascii=False, indent=2)+'\n',encoding='utf-8')
    # Preserve unrelated science/news copy while updating just the about-library sentence.
    homepage = ROOT / 'web/index.html'
    text = homepage.read_text(encoding='utf-8').replace(
        '用于展示航天与工程学习资料的封面、简介、作者、来源、格式、大小与下载入口。资料整理后逐项发布，不提供PDF在线阅读。',
        '提供航天与工程学习资料的封面、书名、分类、格式、大小与下载入口，不提供PDF在线阅读。')
    homepage.write_text(text, encoding='utf-8', newline='\n')
    print('Release catalog: 28 published, 24 local covers, 4 placeholders, no introductions')


if __name__ == '__main__':
    main()
