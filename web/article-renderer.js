'use strict';
// Deliberately limited Markdown, built with DOM APIs only. Never interpret HTML.
(() => {
  const node = (tag, text) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; return n; };
  function safeURL(value, baseURL = location.href) {
    if (!value || /[\u0000-\u0020\u007f\\]/.test(value)) return null;
    try {
      const url = new URL(value, baseURL);
      return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : null;
    } catch { return null; }
  }
  function anchor(label, url) {
    const a = node('a', label); a.href = url;
    if (new URL(url).origin !== location.origin) { a.target = '_blank'; a.rel = 'noopener noreferrer'; }
    return a;
  }
  function plainLinks(target, value) {
    let start = 0;
    for (const match of value.matchAll(/https?:\/\/[^\s<>"'`\\\u0000-\u001f\u007f，。！？；：、…）》」』】]+/gi)) {
      let candidate = match[0];
      // Sentence punctuation is not part of a URL; retain balanced parentheses in paths.
      while (candidate) {
        const last = candidate.at(-1), pairs = {')':'(', ']':'[', '}':'{'};
        if (/[.,!?;:，。！？；：、…）》」』】]/.test(last) || (pairs[last] && candidate.split(last).length > candidate.split(pairs[last]).length)) candidate = candidate.slice(0, -1);
        else break;
      }
      const url = safeURL(candidate);
      if (!url) continue;
      target.append(document.createTextNode(value.slice(start, match.index)), anchor(candidate, url));
      start = match.index + candidate.length;
    }
    target.append(document.createTextNode(value.slice(start)));
  }
  function linkedText(target, value, links = [], options = {}) {
    const characters = Array.from(value);
    let start = 0;
    for (const entry of links) {
      const {start:from, end:to} = entry, url = safeURL(entry.url, options.baseURL);
      if (!url || !Number.isInteger(from) || !Number.isInteger(to) || from < start || to <= from || to > characters.length) continue;
      plainLinks(target, characters.slice(start, from).join(''));
      target.append(anchor(characters.slice(from, to).join(''), url)); start = to;
    }
    plainLinks(target, characters.slice(start).join(''));
  }
  function inline(target, value, options = {}, depth = 0) {
    if (depth > 8) { target.append(document.createTextNode(value)); return; }
    const tokens = /(`[^`\n]+`|!\[([^\]\n]*)\]\(([^\s)]+)\)|\[([^\]\n]+)\]\(([^\s)]+)\)|\*\*([^*\n]+)\*\*|\*([^*\n]+)\*)/g;
    let start = 0;
    for (const match of value.matchAll(tokens)) {
      plainLinks(target, value.slice(start, match.index));
      const [raw, , alt, imageURL, label, linkURL, bold, emphasis] = match;
      if (raw.startsWith('`')) target.append(node('code', raw.slice(1, -1)));
      else if (imageURL !== undefined) {
        const url = safeURL(imageURL, options.baseURL);
        // News passes no image permission: reviewed assets are inserted separately.
        if (url && options.allowImage?.(url)) {
          const image = node('img'); image.src = url; image.alt = alt; image.loading = 'lazy';
          image.addEventListener('error', () => image.replaceWith(node('span', '图片暂不可用：' + alt)));
          target.append(image);
        } else target.append(node('span', alt ? '图片：' + alt + '（请查看原文）' : '图片请查看原文。'));
      } else if (linkURL !== undefined) {
        const url = safeURL(linkURL, options.baseURL);
        if (url) {
          target.append(anchor(label, url));
        } else target.append(document.createTextNode(label));
      } else { const tag = node(bold !== undefined ? 'strong' : 'em'); inline(tag, bold ?? emphasis, options, depth + 1); target.append(tag); }
      start = match.index + raw.length;
    }
    plainLinks(target, value.slice(start));
  }
  function tableWrap(table) {
    const wrap = node('div'); wrap.className = 'article-table reader-table'; wrap.tabIndex = 0;
    wrap.setAttribute('role', 'region'); wrap.setAttribute('aria-label', '表格，可横向滚动'); wrap.append(table); return wrap;
  }
  const cells = line => line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(cell => cell.trim());
  const divider = line => line.includes('|') && cells(line).every(cell => /^:?-{3,}:?$/.test(cell));
  function markdown(text, options = {}, depth = 0) {
    const body = node('div'); body.className = 'article-content';
    if (depth > 12) { body.append(node('p', String(text))); return body; }
    const lines = String(text).replace(/\r\n?/g, '\n').split('\n');
    let i = 0;
    const special = at => /^(?:\s*$| {0,3}#{1,6}\s| {0,3}```|\s*>|\s*(?:[-+*]|\d+\.)\s+)/.test(lines[at]) || (at + 1 < lines.length && divider(lines[at + 1]));
    while (i < lines.length) {
      const line = lines[i];
      if (!line.trim()) { i++; continue; }
      const fence = /^ {0,3}```([^`]*)$/.exec(line);
      const heading = /^ {0,3}(#{1,6})\s+(.+)$/.exec(line);
      const list = /^\s*([-+*]|\d+\.)\s+(.+)$/.exec(line);
      if (fence) {
        const code = node('code'), pre = node('pre'), content = []; i++;
        while (i < lines.length && !/^ {0,3}```\s*$/.test(lines[i])) content.push(lines[i++]);
        code.textContent = content.join('\n'); pre.append(code); body.append(pre); if (i < lines.length) i++;
      } else if (heading) {
        const h = node('h' + Math.min(6, Math.max(2, heading[1].length)));
        inline(h, heading[2], options); body.append(h); i++;
      } else if (/^\s*>/.test(line)) {
        const quote = node('blockquote'), content = [];
        while (i < lines.length && /^\s*>/.test(lines[i])) content.push(lines[i++].replace(/^\s*>\s?/, ''));
        quote.append(markdown(content.join('\n'), options, depth + 1)); body.append(quote);
      } else if (i + 1 < lines.length && line.includes('|') && divider(lines[i + 1])) {
        const table = node('table'), head = node('thead'), row = node('tr'), tbody = node('tbody');
        cells(line).forEach(value => { const th = node('th'); th.scope = 'col'; inline(th, value, options); row.append(th); });
        head.append(row); table.append(head, tbody); i += 2;
        while (i < lines.length && lines[i].trim() && lines[i].includes('|')) {
          const tr = node('tr'); cells(lines[i++]).forEach(value => { const td = node('td'); inline(td, value, options); tr.append(td); }); tbody.append(tr);
        }
        body.append(tableWrap(table));
      } else if (list) {
        const ordered = /\d/.test(list[1]), ul = node(ordered ? 'ol' : 'ul');
        if (ordered) ul.start = Number.parseInt(list[1], 10);
        while (i < lines.length) {
          const entry = /^\s*([-+*]|\d+\.)\s+(.+)$/.exec(lines[i]);
          if (!entry || /\d/.test(entry[1]) !== ordered) break;
          const li = node('li'); inline(li, entry[2], options); ul.append(li); i++;
        }
        body.append(ul);
      } else {
        const content = [lines[i++]];
        while (i < lines.length && !special(i)) content.push(lines[i++]);
        const p = node('p'); inline(p, content.join('\n'), options); body.append(p);
      }
    }
    return body;
  }
  function block(value, options = {}) {
    let result;
    if (value.type === 'markdown') return markdown(value.text, options); // No inline news images.
    if (value.type === 'heading' || value.type === 'paragraph') {
      result = node(value.type === 'heading' ? 'h' + Math.max(2, Math.min(4, value.level || 2)) : 'p');
      linkedText(result, value.text, value.links, options);
    }
    else if (value.type === 'list') {
      result = node(value.ordered ? 'ol' : 'ul');
      value.items.forEach((item, index) => { const li = node('li'); linkedText(li, item, (value.links || []).filter(link => link.item === index), options); result.append(li); });
    }
    else if (value.type === 'table') {
      const table = node('table'), tbody = node('tbody');
      if (value.caption) table.append(node('caption', value.caption));
      value.rows.forEach((row, r) => { const tr = node('tr'); row.forEach((cell, c) => { const td = node('td'); linkedText(td, cell, (value.links || []).filter(link => link.row === r && link.column === c), options); tr.append(td); }); tbody.append(tr); });
      table.append(tbody); result = tableWrap(table);
    }
    return result || null;
  }
  window.ArticleRenderer = Object.freeze({markdown, block, safeURL});
})();
