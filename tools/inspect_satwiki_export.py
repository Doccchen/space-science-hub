"""Archive and inspect an official SatWiki XML export, without network calls.

Outputs original XML, per-page Wikitext and a provenance/coverage manifest.
Wikitext is staging material, not template-expanded AI knowledge documents.
"""
import argparse
import collections
import hashlib
import json
import shutil
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


def inspect(source, output, titles_file):
    raw = source.read_bytes()
    if len(raw) > 25 * 1024 * 1024:
        raise ValueError('Export exceeds 25 MiB inspection limit')
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('DTD/entity declarations are not accepted')
    root = ET.fromstring(raw)
    if not root.tag.startswith('{http://www.mediawiki.org/xml/export-') or not root.tag.endswith('}mediawiki'):
        raise ValueError('Not a MediaWiki XML export')
    ns = {'m': root.tag.split('}')[0][1:]}
    base = root.findtext('m:siteinfo/m:base', default='', namespaces=ns)
    if urllib.parse.urlsplit(base).hostname != 'sat.huijiwiki.com':
        raise ValueError('Export siteinfo does not identify SatWiki')
    expected = [line.strip() for line in titles_file.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    if len(expected) != len(set(expected)):
        raise ValueError('Duplicate requested titles')
    if output.exists() and any(output.iterdir()):
        raise ValueError('Output directory must be empty')
    output.mkdir(parents=True, exist_ok=True)
    (output/'wikitext').mkdir()
    shutil.copyfile(source, output/'official-export.xml')
    rows = []
    for page in root.findall('m:page', ns):
        title = page.findtext('m:title', default='', namespaces=ns)
        page_id = page.findtext('m:id', default='', namespaces=ns)
        if not page_id.isdigit():
            raise ValueError('Export page missing numeric ID')
        revisions = page.findall('m:revision', ns)
        revision = max(revisions, key=lambda item: item.findtext('m:timestamp', default='', namespaces=ns)) if revisions else None
        if revision is None:
            raise ValueError('Export page has no revision')
        text = revision.findtext('m:text', default='', namespaces=ns)
        text_node = revision.find('m:text', ns)
        if text_node is None:
            text_node = revision.find('m:slots/m:slot/m:text', ns)
            text = text_node.text or '' if text_node is not None else ''
        redirect = page.find('m:redirect', ns)
        contributor = revision.find('m:contributor', ns)
        quoted = urllib.parse.quote(title, safe='')
        revid = revision.findtext('m:id', default='', namespaces=ns)
        file = output/'wikitext'/f'{page_id}.wiki'
        file.write_bytes(text.encode('utf-8'))
        rows.append({
            'title': title, 'page_id': int(page_id),
            'namespace': int(page.findtext('m:ns', default='0', namespaces=ns)),
            'revision_id': revid,
            'revision_timestamp': revision.findtext('m:timestamp', default='', namespaces=ns),
            'exported_revision_count': len(revisions),
            'last_contributor': contributor.findtext('m:username', namespaces=ns) if contributor is not None else None,
            'source_url': f'https://sat.huijiwiki.com/wiki/{quoted}',
            'revision_url': f'https://sat.huijiwiki.com/index.php?title={quoted}&oldid={revid}',
            'history_url': f'https://sat.huijiwiki.com/index.php?title={quoted}&action=history',
            'redirect_target': redirect.get('title') if redirect is not None else None,
            'text_present': text_node is not None and 'deleted' not in text_node.attrib,
            'text_characters': len(text),
            'text_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
            'wikitext_file': f'wikitext/{page_id}.wiki',
        })
    present = {row['title'] for row in rows}
    articles = [row for row in rows if row['namespace'] == 0]
    manifest = {
        'inspected_utc': datetime.now(timezone.utc).isoformat(),
        'acquisition': 'official browser Special:Export download; XML itself is not cryptographically authenticated',
        'source_export_url': 'https://sat.huijiwiki.com/wiki/Special:Export',
        'xml_sha256': hashlib.sha256(raw).hexdigest(), 'xml_bytes': len(raw),
        'site_name': root.findtext('m:siteinfo/m:sitename', namespaces=ns),
        'generator': root.findtext('m:siteinfo/m:generator', namespaces=ns),
        'requested_title_count': len(expected), 'exported_page_count': len(rows),
        'namespace_counts': dict(collections.Counter(str(row['namespace']) for row in rows)),
        'article_count': len(articles), 'requested_missing': sorted(set(expected)-present),
        'redirects': [row['title'] for row in articles if row['redirect_target']],
        'empty_or_hidden': [row['title'] for row in rows if not row['text_present'] or not row['text_characters']],
        'license_policy_url': 'https://sat.huijiwiki.com/wiki/Project:%E7%89%88%E6%9D%83',
        'default_text_license': 'CC BY-SA 4.0; page-specific exceptions require review',
        'readiness': 'raw_archive_only; templates not expanded; citations and factual accuracy not audited',
        'attribution_note': 'Last contributor is not the complete author list; retain history links and obtain fuller attribution if needed',
        'pages': rows,
    }
    (output/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: manifest[key] for key in ('xml_bytes', 'exported_page_count', 'namespace_counts', 'article_count', 'requested_missing', 'redirects', 'empty_or_hidden')}, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--titles', type=Path, default=Path('docs/research/卫星百科首批候选标题-20261006.txt'))
    args = parser.parse_args()
    inspect(args.source, args.output, args.titles)
