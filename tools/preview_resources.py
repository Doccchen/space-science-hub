"""Private local preview of drafts and thumbnails; never publishes the catalog.

Run: python -m tools.preview_resources
Open: http://127.0.0.1:8091/#library
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    import uvicorn
    from fastapi import HTTPException
    from fastapi.responses import FileResponse

    preview_dir = ROOT / "artifacts/resource-preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    os.environ['COLLECT_ENABLED'] = '0'
    os.environ['NEWS_DB_PATH'] = str(preview_dir / 'news.sqlite3')
    os.environ['RESOURCES_PATH'] = str(ROOT / 'content/resources.json')
    from backend.app import app
    from backend import resources

    candidates = json.loads((ROOT / 'docs/research/resources-preparation/resources.candidates.json').read_text(encoding='utf-8'))
    previews = [resources.Resource.model_validate({key: value for key, value in item.items() if key in resources.Resource.model_fields})
                for item in candidates if item['object_key']]
    cover_ids = {item['id'] for item in candidates if item['review']['cover_status'] == 'visually_checked_candidate'}
    original_load = resources.catalog.load
    original_record = resources.public_record

    def load_preview():
        original_load()
        resources.catalog.items = sorted([item.model_copy(update={'published': True}) for item in previews],
                                        key=lambda item: (item.display_order, item.id))

    def preview_record(item, detail=False):
        result = original_record(item, detail)
        result['cover_url'] = f'/preview-covers/{item.id}.jpg' if item.id in cover_ids else None
        return result

    resources.catalog.load = load_preview
    resources.public_record = preview_record

    @app.get('/preview-covers/{filename}')
    def preview_cover(filename: str):
        if filename.removesuffix('.jpg') not in cover_ids or not filename.endswith('.jpg'):
            raise HTTPException(404)
        return FileResponse(ROOT / 'artifacts/resources-preparation' / filename, media_type='image/jpeg')

    print('Draft preview only: loopback binding, isolated news DB, no collection or publication.', flush=True)
    uvicorn.run(app, host='127.0.0.1', port=8091)


if __name__ == '__main__':
    main()
