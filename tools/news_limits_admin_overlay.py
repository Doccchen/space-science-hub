"""Minimal owned admin changes over the actual deployed layout, preserving parallel edits."""
import argparse
from pathlib import Path


def backend_source(source):
    if 'app.include_router(news_limits_admin.router)' not in source:
        anchor='from . import resource_admin, management_store, ai_admin'
        if source.count(anchor)!=1: raise ValueError('Unreviewed admin import layout')
        source=source.replace(anchor,anchor+', news_limits_admin',1)
        anchor='app.include_router(ai_admin.router)'
        if source.count(anchor)!=1: raise ValueError('Unreviewed admin router layout')
        source=source.replace(anchor,anchor+'\napp.include_router(news_limits_admin.router)',1)
    if "@app.get('/news-limits.js')" not in source:
        anchor="    return FileResponse(STATIC/'ai-settings.js', media_type='application/javascript')"
        if source.count(anchor)!=1:raise ValueError('Unreviewed admin JavaScript route')
        source=source.replace(anchor,anchor+"\n\n\n@app.get('/news-limits.js')\ndef news_limits_script():\n    return FileResponse(STATIC/'news-limits.js',media_type='application/javascript')",1)
    return source


def admin_html(source):
    if '<script src="/news-limits.js"></script>' in source:return source
    anchor='<script src="/ai-settings.js"></script>'
    if source.count(anchor)!=1:raise ValueError('Unreviewed admin script layout')
    return source.replace(anchor,anchor+'<script src="/news-limits.js"></script>',1)


def navigation_guard(source,module):
    if module=='ai':
        anchor="event.detail === 'resources'";replacement="['resources','news'].includes(event.detail)"
    else:
        anchor="event.detail==='ai'";replacement="['ai','news'].includes(event.detail)"
    if replacement in source:return source
    if source.count(anchor)!=1:raise ValueError('Unreviewed admin navigation guard')
    return source.replace(anchor,replacement,1)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--backend-only',action='store_true');args=parser.parse_args()
    root=Path(args.root);path=root/'backend/admin_app.py';path.write_text(backend_source(path.read_text()),encoding='utf-8')
    if not args.backend_only:
        path=root/'admin_web/index.html';path.write_text(admin_html(path.read_text()),encoding='utf-8')
        for filename,module in (('ai-settings.js','ai'),('resources.js','resources')):
            path=root/'admin_web'/filename;path.write_text(navigation_guard(path.read_text(),module),encoding='utf-8')


if __name__=='__main__':main()
