"""Convert the inspected official SatWiki batch to provenance-bearing UTF-8 MD.

No network, cloud upload or model calls. Known navigation/display templates are
removed; source quality notices remain. Unknown templates stop the conversion.
"""
import argparse
import collections
import hashlib
import html
import json
import re
import zipfile
from pathlib import Path

import wikitextparser as wtp
from bs4 import BeautifulSoup

NAVIGATION = {'知名航天人', '火箭发动机', '轨道', '姿态', '天文学'}
DISPLAY = {'Top icon', 'KaTeX'}
MATH = re.compile(r'\\\[(.*?)\\\]|\\\((.*?)\\\)|(?<!\\)\$\$(.*?)\$\$|(?<!\\)\$([^\n$]+?)\$', re.S)
LIMIT = 10 * 1024 * 1024  # Conservative target, official recommendation not a hard platform limit.


class Converter:
    def __init__(self):
        self.math = []
        self.refs = []
        self.ref_names = {}
        self.notices = []
        self.removed = collections.Counter()
        self.tables = []
        self.media_count = 0

    def protect_math(self, text):
        def replace(match):
            index = len(self.math)
            parts = match.groups()
            display = parts[0] is not None or parts[2] is not None
            value = next(p for p in parts if p is not None)
            self.math.append({'source': match.group(), 'value': value, 'display': display})
            return f'SATWIKIMATH{index:04d}TOKEN'
        return MATH.sub(replace, text)

    def templates(self, text):
        parsed = wtp.parse(text)
        for item in reversed(parsed.parser_functions):
            if not re.fullmatch(r'\{\{#html:(MathJax|KaTeX)\}\}', item.string, re.I):
                raise ValueError('Unsupported parser function: ' + item.string)
            item.string = ''
            self.removed['math_renderer'] += 1
        for item in reversed(parsed.templates):
            name = item.name.strip().removeprefix('模板:').removeprefix('Template:')
            if name in NAVIGATION or name in DISPLAY:
                self.removed[name] += 1
                item.string = ''
            elif name in {'需要更新', '正在施工'}:
                notice = '原站标记：' + name + '；本资料采用导出时的历史版本，内容尚未独立核实。'
                self.notices.append(notice)
                item.string = '\n\n> ' + notice + '\n\n'
            elif name == '消歧义':
                target = str(item.get_arg('1').value).strip() if item.has_arg('1') else ''
                item.string = '\n\n> 原站消歧义提示：可能存在同名或近似词条，请参阅 ' + target + '。\n\n'
            else:
                raise ValueError('Unsupported content template: ' + name)
        return parsed.string

    def references(self, text):
        parsed = wtp.parse(text)
        # Assign numbers in source order, resolve named references defined later.
        tags = parsed.get_tags('ref')
        assigned = []
        for tag in tags:
            name = tag.attrs.get('name')
            if name and name in self.ref_names:
                index = self.ref_names[name]
            else:
                index = len(self.refs)
                self.refs.append('')
                if name:
                    self.ref_names[name] = index
            if tag.contents.strip():
                if self.refs[index] and self.refs[index] != tag.contents.strip():
                    raise ValueError('Conflicting named reference: ' + str(name))
                self.refs[index] = tag.contents.strip()
            assigned.append((tag, index))
        for tag, index in reversed(assigned):
            tag.string = f'〔参考{index+1}〕'
        if any(not ref for ref in self.refs):
            raise ValueError('Source contains unresolved reference')
        for tag in reversed(parsed.get_tags('references')):
            tag.string = ''
        return parsed.string

    def inline(self, text):
        text = re.sub(r'<nowiki>(.*?)</nowiki>', lambda m: m.group(1), text, flags=re.S|re.I)
        parsed = wtp.parse(text)
        # Inner links first, so caption links cannot be silently truncated.
        while parsed.wikilinks:
            link = parsed.wikilinks[-1]
            target = link.target.strip()
            prefix = target.partition(':')[0].casefold()
            if prefix in {'分类', 'category'}:
                value = ''
            elif prefix in {'file', '文件', 'image', '图像'}:
                self.media_count += 1
                options = (link.text or '').split('|')
                captions = [x for x in options if x.strip() and not re.fullmatch(r'(?:\d+px|thumb|thumbnail|frame|frameless|center|left|right|none|缩略图|居中|缩略|居右|居左|无框|class=.*|alt=.*|link=.*)', x.strip(), re.I)]
                value = '\n\n插图说明（未包含图片）：' + '；'.join(captions) + '\n\n' if captions else '\n\n本处原有插图，文字资料未包含其图像内容。\n\n'
            else:
                value = link.text if link.text is not None else target
            link.string = value
            parsed = wtp.parse(parsed.string)
        for link in reversed(parsed.external_links):
            url = link.url
            value = f'{link.text}（{url}）' if link.text else url
            link.string = value
        text = parsed.string.replace("'''''", '').replace("'''", '**').replace("''", '')
        text = re.sub(r'<sub>(.*?)</sub>', lambda m: '_' + m.group(1), text, flags=re.S|re.I)
        text = re.sub(r'<sup>(.*?)</sup>', lambda m: '^(' + m.group(1) + ')', text, flags=re.S|re.I)
        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.I)
        text = re.sub(r'<nowiki>(.*?)</nowiki>', lambda m: m.group(1), text, flags=re.S|re.I)
        if re.search(r'</?[A-Za-z][^>]*>', text):
            text = BeautifulSoup(text, 'html.parser').get_text()
        return html.unescape(text).strip()

    def convert(self, raw):
        # Protect TeX before parsing: nested TeX braces resemble wiki templates.
        text = self.protect_math(raw)
        text = re.sub(r'<!--.*?-->', '', text, flags=re.S)
        text = self.templates(text)
        text = self.references(text)
        text = re.sub(r'(?m)^([*#]+)\s*(.+)$', lambda m: '  '*(len(m.group(1))-1) + '- ' + m.group(2), text)
        parsed = wtp.parse(text)
        for table in reversed(parsed.tables):
            data = [[self.inline(cell or '').replace('\n', ' ').replace('|', '\\|') for cell in row] for row in table.data()]
            if len(data) < 2 or len({len(row) for row in data}) != 1:
                raise ValueError('Table not rectangular or missing data rows')
            caption = self.inline(table.caption or '')
            self.tables.append({'caption': caption, 'rows': data})
            lines = ['\n\n' + caption if caption else '\n\n',
                     '| ' + ' | '.join(data[0]) + ' |',
                     '| ' + ' | '.join(['---'] * len(data[0])) + ' |']
            lines.extend('| ' + ' | '.join(row) + ' |' for row in data[1:])
            # Field-name sentences ensure values retain context if table chunks split.
            lines.append('\n参数逐行记录：')
            for row in data[1:]:
                lines.append('- ' + '；'.join(f'{header}：{value}' for header, value in zip(data[0], row)) + '。')
            table.string = '\n'.join(lines) + '\n\n'
        text = self.inline(parsed.string)
        text = re.sub(r'(?m)^(={2,6})\s*(.*?)\s*\1\s*$', lambda m: '#' * len(m.group(1)) + ' ' + m.group(2), text)
        text = re.sub(r'(?m)^:\s*', '', text)
        if self.refs:
            text += '\n\n## 原词条参考资料\n\n' + '\n'.join(f'{i+1}. {self.inline(ref)}' for i, ref in enumerate(self.refs))
        for i, formula in enumerate(self.math):
            token = f'SATWIKIMATH{i:04d}TOKEN'
            value = '\n\n$$\n' + formula['value'] + '\n$$\n\n' if formula['display'] else '$' + formula['value'] + '$'
            if token not in text:
                raise ValueError('Formula lost during conversion')
            text = text.replace(token, value)
        text = re.sub(r'\n[ \t]+\n', '\n\n', text)
        return re.sub(r'\n{3,}', '\n\n', text).strip()


def build(archive, output):
    manifest = json.loads((archive/'manifest.json').read_text(encoding='utf-8'))
    if hashlib.sha256((archive/'official-export.xml').read_bytes()).hexdigest() != manifest['xml_sha256']:
        raise ValueError('Original XML checksum mismatch')
    if output.exists() and any(output.iterdir()):
        raise ValueError('Output directory must be empty')
    upload = output/'上传文件'
    upload.mkdir(parents=True, exist_ok=True)
    audit = []
    for page in manifest['pages']:
        if page['namespace'] != 0:
            continue
        raw = (archive/page['wikitext_file']).read_text(encoding='utf-8')
        if hashlib.sha256(raw.encode('utf-8')).hexdigest() != page['text_sha256']:
            raise ValueError('Raw Wikitext checksum mismatch')
        converter = Converter()
        body = converter.convert(raw)
        categories = [link.target.partition(':')[2] for link in wtp.parse(raw).wikilinks if link.target.partition(':')[0].casefold() in {'分类', 'category'}]
        provenance = '\n'.join([
            '资料来源：卫星百科（SatWiki）及该词条的贡献者。',
            f"词条原文：{page['source_url']}",
            f"本次采用版本：{page['revision_url']}",
            f"版本时间（UTC）：{page['revision_timestamp']}",
            f"作者归属与完整编辑历史：{page['history_url']}",
            '导出日期：2026-10-06。',
            '主题分类：' + '、'.join(dict.fromkeys(categories)) + '。' if categories else '',
            '许可：CC BY-SA 4.0（https://creativecommons.org/licenses/by-sa/4.0/）；另有声明的材料以原声明为准。',
            '整理说明：调整标题、列表、引用和表格格式，移除站内导航及显示脚本；保留原文事实、数值和公式，不新增推导或核实结论。',
            '图片、视频未纳入；插图说明仅保留原有文字。时间敏感信息以以上版本为准，不代表当前状态。',
        ])
        header = f"# {page['title']}\n\n来源：卫星百科；版本：{page['revision_id']}（{page['revision_timestamp']}）。\n\n"
        document = header + body + '\n\n## 来源、版本与许可\n\n' + provenance + '\n'
        filename = f"卫星百科_{page['title']}.md"
        if re.search(r'[<>:"/\\|?*]', filename):
            raise ValueError('Unsafe document filename')
        encoded = document.encode('utf-8')
        if len(encoded) >= LIMIT or '\ufffd' in document or 'SATWIKIMATH' in document:
            raise ValueError('Invalid document encoding, size or unresolved formula')
        # Residual braces can legitimately occur only inside exact preserved TeX.
        outside_math = MATH.sub('', document)
        if any(marker in outside_math for marker in ['{{', '}}', '[[', ']]', '{|', '|}', '<ref', '<script']):
            raise ValueError('Unconverted Wikitext/HTML remains: ' + page['title'])
        (upload/filename).write_bytes(encoded)
        audit.append({'title':page['title'], 'file':filename, 'bytes':len(encoded),
                      'sha256':hashlib.sha256(encoded).hexdigest(), 'revision_id':page['revision_id'],
                      'source_url':page['source_url'], 'source_notices':converter.notices,
                      'formula_count':len(converter.math), 'formulas':converter.math,
                      'table_count':len(converter.tables), 'tables':converter.tables,
                      'reference_count':len(converter.refs), 'media_count':converter.media_count,
                      'removed_templates':dict(converter.removed)})
    if len(audit) != 30:
        raise ValueError('Expected exactly 30 articles in this batch')
    report = {'format':'UTF-8 Markdown, LF, one article per file', 'upload_file_count':len(audit),
              'cloud_import_verified':False, 'xml_sha256':manifest['xml_sha256'],
              'max_file_bytes':max(item['bytes'] for item in audit),
              'documents':audit}
    (output/'转换与校验清单.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    with zipfile.ZipFile(output/'卫星百科_百炼导入文件_30篇.zip', 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for file in sorted(upload.glob('*.md')):
            bundle.write(file, arcname=file.name)
    print(json.dumps({'documents':len(audit), 'max_bytes':report['max_file_bytes'],
                      'formulas':sum(row['formula_count'] for row in audit),
                      'tables':sum(row['table_count'] for row in audit),
                      'references':sum(row['reference_count'] for row in audit)}, ensure_ascii=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, default=Path('artifacts/satwiki-export/20261006-batch01'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build(args.archive, args.output)
