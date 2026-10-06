"""Small compatibility UI patch; backups first, no database or backend changes.

Run on host to persist the source, and via stdin in the existing app as root.
"""
import argparse
import os
import re
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def clean_script(text):
    if '来源未提供摘要，请查看原文。' in text and (
            "bottom.append(element('span', '', summaryKind(item)), action);" not in text or
            'row.append(meta, heading, summary, bottom); return row;' not in text):
        raise ValueError('Unrecognized legacy renderer; no changes written')
    text = text.replace("item.summary || '来源未提供摘要，请查看原文。'", "item.summary || ''")
    text = text.replace("bottom.append(element('span', '', summaryKind(item)), action);",
                        "if (item.summary?.trim()) bottom.append(element('span', '', summaryKind(item))); bottom.append(action);")
    text = text.replace('row.append(meta, heading, summary, bottom); return row;',
                        'row.append(meta, heading); if (item.summary?.trim()) row.append(summary); row.append(bottom); return row;')
    text = text.replace("if (canRead && item.summary) row.append", "if (canRead && item.summary?.trim()) row.append")
    # Remove dead legacy labels; an older renderer still needs the helper for real excerpts.
    if text.count('summaryKind') == 1:
        text = re.sub(r'^  const summaryKind = .*\n', '', text, flags=re.MULTILINE)
    if '来源未提供摘要，请查看原文。' in text:
        raise ValueError('Unrecognized legacy renderer; no changes written')
    return text


def replace_atomic(path, text, backup_dir):
    original = path.read_text(encoding='utf-8')
    if original == text:
        return False
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    (backup_dir/(path.name+'.'+stamp)).write_bytes(path.read_bytes())
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix='.'+path.name)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as file:
            file.write(text)
        os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--web', type=Path, default=Path('web'))
    parser.add_argument('--backups', type=Path, default=Path('data/ui-backups'))
    args = parser.parse_args()
    script, html = args.web/'news-ui.js', args.web/'index.html'
    cleaned = clean_script(script.read_text(encoding='utf-8'))
    index = re.sub(r'/assets/news-ui\.js(?:\?[^"\s]*)?', '/assets/news-ui.js?v=20261006-clean-summary', html.read_text(encoding='utf-8'))
    for path, value in ((script, cleaned), (html, index)):
        print(path.name, 'updated' if replace_atomic(path, value, args.backups) else 'already clean')
