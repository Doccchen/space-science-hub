"""Bounded child process: no network, no OCR, no model, page-based provenance."""
import collections
import json
import re
import sys
import unicodedata
from pathlib import Path

import pymupdf


SECTIONS = {
    '研究问题': r'\b(abstract|introduction|background|objective)\b|摘要|引言|研究目的',
    '方法与条件': r'\b(method|methods|methodology|experiment\w*|numerical|simulation|setup|procedure|hardware|instrumentation)\b|方法|实验|数值|工况',
    '结果与证据': r'\b(results?|discussion|validation)\b|结果|讨论|验证',
    '局限与结论': r'\b(conclusions?|limitations?|future work)\b|结论|局限|展望',
    '参考文献': r'\b(references|bibliography)\b|参考文献',
}


def section_for(text):
    heading = unicodedata.normalize('NFKC', next((line.strip() for line in text.splitlines() if line.strip()), ''))
    if len(heading) > 180:
        return None
    # MuPDF may combine a heading and its following paragraph into one block.
    # Only recognize heading-shaped first lines, never keyword hits in prose.
    candidate = re.sub(r'^(?:[IVX]+\.|[A-Z]\.|\d+(?:\.\d+)*\.?)\s+', '', heading)
    numbered = candidate != heading
    if not numbered and len(text) > 180 and not re.fullmatch(r'abstract|introduction|background|methods?|experimental design|results?(?: and discussion)?|discussion(?: of results)?|summary(?: and conclusions)?|conclusions?|limitations?|future work|references|bibliography|data availability|acknowledg(?:e)?ments|摘要|引言|方法|结果|讨论|结论|参考文献|致谢', candidate, re.I):
        return None
    if len(candidate.split()) > 14 or re.search(r'[.!?。！？]$', candidate):
        return None
    if not re.match(r'abstract|introduction|background|objective|method|experiment|numerical|simulation|setup|procedure|chamber|instrumentation|results?|discussion|validation|summary|conclusion|limitation|future work|references|bibliography|appendix|acknowledg|data availability|摘要|引言|研究目的|方法|实验|数值|工况|结果|讨论|验证|结论|局限|展望|参考文献|附录|致谢', candidate, re.I):
        return None
    if re.match(r'appendix|acknowledg|data availability|附录|致谢', candidate, re.I):
        return '附录与其他声明'
    # "Numerical results" must not match the more general "numerical" method rule.
    if re.search(SECTIONS['结果与证据'], candidate, re.I):
        return '结果与证据'
    return next((name for name, pattern in SECTIONS.items() if re.search(pattern, heading, re.I)), None)


def ordered_blocks(page):
    """Detect two columns with full-width separators; keep page provenance intact."""
    middle = page.rect.width / 2
    raw = []
    for block in page.get_text('dict')['blocks']:
        if block['type'] != 0:
            continue
        lines = [(line['bbox'], ''.join(span['text'] for span in line['spans'])) for line in block['lines']]
        lines = [(box, text) for box, text in lines if text.strip()]
        if not lines:
            continue
        left_lines = [line for line in lines if line[0][2] < middle+12]
        right_lines = [line for line in lines if line[0][0] > middle-12]
        # MuPDF can merge two adjacent columns into the same block. Split it
        # using the individual line positions before ordering whole columns.
        groups = [left_lines, right_lines] if left_lines and right_lines and len(left_lines)+len(right_lines) == len(lines) else [lines]
        for group in groups:
            box = (min(l[0][0] for l in group), min(l[0][1] for l in group), max(l[0][2] for l in group), max(l[0][3] for l in group))
            raw.append((*box, '\n'.join(l[1] for l in group), 0, 0))
    left = [b for b in raw if b[2] < middle + 12]
    right = [b for b in raw if b[0] > middle - 12]
    if len(left) < 2 or len(right) < 2:
        return sorted(raw, key=lambda b: (round(b[1] / 4), b[0]))
    # A full-width heading divides the page into independent column bands.
    separators = sorted([b for b in raw if b not in left and b not in right], key=lambda b: b[1])
    remaining = [b for b in raw if b in left or b in right]
    result = []
    for sep in separators + [None]:
        band = [b for b in remaining if sep is None or b[1] < sep[1]]
        result.extend(sorted([b for b in band if b in left], key=lambda b: b[1]))
        result.extend(sorted([b for b in band if b not in left], key=lambda b: b[1]))
        remaining = [b for b in remaining if b not in band]
        if sep:
            result.append(sep)
    return result


def parse(path, maximum):
    with pymupdf.open(path) as doc:
        if not doc.is_pdf or doc.needs_pass:
            raise ValueError('仅支持未加密、可读取的 PDF。')
        if not 1 <= len(doc) <= maximum:
            raise ValueError(f'页数应在 1–{maximum} 页之间。')
        pages = [ordered_blocks(page) for page in doc]
        margin_counts = collections.Counter()
        for page, blocks in zip(doc, pages):
            seen = set()
            for b in blocks:
                if b[1] < page.rect.height * .08 or b[3] > page.rect.height * .94:
                    seen.add(re.sub(r'\d+', '#', b[4].strip()))
            margin_counts.update(seen)
        blocks, missing, section = [], [], '未识别章节'
        chars = 0
        for number, (page, page_blocks) in enumerate(zip(doc, pages), 1):
            page_chars = 0
            for block in page_blocks:
                text = block[4].strip().replace('\x00', '')
                margin = block[1] < page.rect.height * .08 or block[3] > page.rect.height * .94
                repeated = margin_counts[re.sub(r'\d+', '#', text)] >= max(3, len(doc) * .5)
                if margin and repeated:
                    continue
                heading = section_for(text)
                if heading:
                    section = heading
                page_chars += len(text)
                chars += len(text)
                if chars > 1_500_000:
                    raise ValueError('解析文本超过 150 万字符上限，请拆分文献。')
                # Limit fragment size while retaining coordinates and exact PDF page.
                start = 0
                while start < len(text):
                    end = min(start+1800, len(text))
                    if end < len(text):
                        boundary = max(text.rfind('\n', start+900, end), text.rfind(' ', start+900, end))
                        if boundary > start:
                            end = boundary+1
                    blocks.append({'page': number, 'section': section, 'text': text[start:end],
                                   'bbox': list(block[:4]), 'ordinal': len(blocks)})
                    start = end
            if page_chars < 40:
                missing.append(number)
        if not blocks or len(missing) == len(doc):
            raise ValueError('未提取到足够文本，可能是扫描件；首版不支持 OCR，请使用文字型 PDF。')
        full = '\n'.join(b['text'] for b in blocks[:30])
        doi = re.search(r'10\.\d{4,9}/[^\s<>]+', full)
        metadata = doc.metadata or {}
        return {'blocks': blocks, 'metadata': {'title': metadata.get('title', '').strip(),
                'authors': metadata.get('author', '').strip(), 'year': '',
                'doi': doi.group().rstrip('.,;)') if doi else ''},
                'coverage': {'pages': len(doc), 'text_pages': len(doc)-len(missing), 'missing_pages': missing,
                'characters': chars, 'warnings': ['公式、单位、上下标与图表数值需对照原页核对。',
                '双栏与页眉页脚采用启发式排序；跨页段落保留独立页片段，阅读顺序需人工核对。']}}


if __name__ == '__main__':
    try:
        result = parse(sys.argv[1], int(sys.argv[3]))
    except Exception as error:
        result = {'error': str(error) if isinstance(error, ValueError) else 'PDF 损坏或解析失败，请检查原文件。'}
    Path(sys.argv[2]).write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
