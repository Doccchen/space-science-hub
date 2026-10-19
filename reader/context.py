"""Task-aware evidence selection. No model, network or cross-paper lookups."""
import re
import unicodedata


def normalize(text):
    return re.sub(r'(?<=[A-Za-z])-\s*\n\s*(?=[A-Za-z])', '', unicodedata.normalize('NFKC', text))


def comparison_requested(question):
    return bool(re.search(r'基准|验证|对照|benchmark|validation', question, re.I)
                and re.search(r'分别|各|每[个种]|逐[项一]|三个|每一|each|which.*cases', question, re.I))


def subsection_groups(blocks):
    groups, current = [], None
    for block in sorted(blocks, key=lambda b:b['ordinal']):
        first = normalize(block['text']).splitlines()[0].strip()
        heading = re.match(r'^(\d+(?:\.\d+)+)\.?\s+(.+)', first)
        if heading and len(first) <= 180 and len(first.split()) <= 24:
            current = {'title':first,'section':block['section'],'blocks':[]}
            groups.append(current)
        elif current and block['section'] != current['section']:
            current = None
        if current:
            current['blocks'].append(block)
    return groups


def comparison_context(blocks, fallback, max_blocks=14, max_chars=10000):
    groups = [g for g in subsection_groups(blocks) if g['section']=='结果与证据'][:4]
    if not groups:
        return fallback, []
    selected, used, size = [], set(), 0
    def add(block):
        nonlocal size
        length = min(len(block['text']),1800)
        if block['ordinal'] in used or len(selected)>=max_blocks or size+length>max_chars:
            return
        selected.append(block);used.add(block['ordinal']);size+=length
    # Keep the author's own overview, which distinguishes validation cases
    # from subsequent applications, before distributing subsection slots.
    overview=[b for b in blocks if b['section']=='结果与证据' and re.search(r'^\d+\.?\s+(?:Numerical results|Results|Validation)',normalize(b['text']).splitlines()[0],re.I)]
    if overview:
        heading=overview[0];add(heading)
        following=next((b for b in blocks if b['ordinal']>heading['ordinal'] and b['section']==heading['section'] and len(b['text'])>=150),None)
        if following:add(following)
    # Reserve space for every candidate subsection before adding detail. A
    # benchmark summary must not spend its entire budget on the first example.
    candidates=[]
    for group in groups:
        prose=[b for b in group['blocks'] if len(b['text'])>=100
               and len(re.findall(r'[A-Za-z]{3,}',normalize(b['text'])))>=15
               and not re.match(r'^(Fig(?:ure)?\.?|Table)\s*\d',b['text'],re.I)]
        scored=sorted(prose,key=lambda b:(-len(re.findall(
            r'theoretical|analytical|compar\w*|literature|predict\w*|Teigen|基准|理论|比较',normalize(b['text']),re.I)),b['ordinal']))
        add(group['blocks'][0])
        if scored:
            add(scored[0])
        candidates.append((group,prose,scored))
    for group,prose,scored in candidates:
        if prose:
            add(prose[0])
    for group,prose,scored in candidates:
        if len(scored)>1:
            add(scored[1])
    for block in fallback:
        add(block)
    return selected, [g['title'] for g,_,_ in candidates]


def prose_requested(question):
    return bool(re.search(r'不(?:要|必)?(?:照抄|列出|输出|写出|给出|展开)?[^。！？;]{0,18}公式|(?:只|仅)[^。！？;]{0,8}自然语言',question))


MATH = re.compile(r'[=≈≠≤≥∇∑∂\u0370-\u03ff\U0001d400-\U0001d7ff]|\\(?:frac|begin)|\$\$|\\\[')


def prose_only(text):
    """Omit entire mathematical clauses, never rewrite a scientific equation."""
    if not MATH.search(text):
        return text, False
    clauses = re.split(r'[。；;\n]|，|(?<!\d),(?!\d)',text)
    kept=[]
    omitted_expression=False
    for part in clauses:
        part=part.strip()
        if not part:continue
        if MATH.search(part):
            omitted_expression=True
            continue
        # Do not leave behind an ungrounded scalar/variable interpretation
        # after removing the equation it purported to explain.
        if omitted_expression and re.match(r'其中|其值|它的值|该变量|该参数|这意味着|从而|使得',part):
            continue
        kept.append(part)
        omitted_expression=False
    return '；'.join(kept), True
