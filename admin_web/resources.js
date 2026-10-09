'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const node = (tag, text) => { const element = document.createElement(tag); if (text) element.textContent = text; return element; };
  const message = text => { $('message').textContent = text; };
  let csrf = '', current = null, covers = [], generation = 0, dirty = false, busy = false;
  async function api(path, method = 'GET', body) {
    const response = await fetch(path, {method, credentials:'same-origin', cache:'no-store',
      headers: body === undefined ? {} : {'Content-Type':'application/json', 'X-CSRF-Token':csrf},
      body:body === undefined ? undefined : JSON.stringify(body), signal:AbortSignal.timeout(15000)});
    const result = await response.json();
    if (!response.ok) {
      if (response.status === 401) document.dispatchEvent(new Event('admin-expired'));
      throw new Error(typeof result.detail === 'string' ? result.detail : '请求格式无效。');
    }
    return result;
  }
  async function act(button, action) {
    if (busy) return;
    busy = true; button.disabled = true; $('resource-form').inert = true;
    try { await action(); } catch (error) { message(error.message); }
    finally { busy = false; button.disabled = false; $('resource-form').inert = false; }
  }
  function leave() { return !dirty || window.confirm('尚有未保存的资料修改，确定放弃这些修改？'); }
  function summary(item) {
    return [item.category || '未分类', item.published ? '已上架' : '已下架',
      '排序 ' + item.display_order, '版本 ' + item.revision, new Date(item.updated_at).toLocaleString()].join(' · ');
  }
  async function list() {
    const run = ++generation;
    $('resource-list').hidden = false; $('resource-editor').hidden = true;
    $('resource-rows').replaceChildren(node('p', '正在读取资料目录…'));
    const result = await api('/api/resources?q=' + encodeURIComponent($('resource-search').value) + '&state=' + $('resource-state').value);
    if (run !== generation || !csrf) return;
    covers = result.covers; current = null; dirty = false;
    $('resource-list').hidden = false; $('resource-editor').hidden = true;
    $('resource-count').textContent = result.items.length + ' 份资料';
    $('resource-rows').replaceChildren();
    for (const item of result.items) {
      const row = node('article'); row.className = 'resource-row';
      if (item.cover_asset) { const image = node('img'); image.src = '/covers/' + item.cover_asset; image.alt = ''; row.append(image); }
      const content = node('div'); content.append(node('h2', item.title), node('p', summary(item)), node('p', '文件大小 ' + item.size_bytes.toLocaleString() + ' 字节'));
      const edit = node('button', '编辑资料'); edit.type = 'button';
      edit.addEventListener('click', () => act(edit, () => open(item.id)));
      row.append(content, edit); $('resource-rows').append(row);
    }
    if (!result.items.length) $('resource-rows').append(node('p', '没有符合条件的资料。'));
  }
  function coverChoices(item) {
    $('resource-cover').replaceChildren();
    const keep = node('option', '保持当前封面'); keep.value = '__keep'; $('resource-cover').append(keep);
    const none = node('option', '无封面'); none.value = ''; $('resource-cover').append(none);
    for (const name of covers) { const choice = node('option', name); choice.value = name; $('resource-cover').append(choice); }
    $('resource-cover').value = item ? '__keep' : '';
  }
  function draw(item) {
    current = item; dirty = false;
    $('resource-list').hidden = true; $('resource-editor').hidden = false;
    $('resource-heading').textContent = item ? '编辑资料' : '新增资料';
    $('resource-meta').textContent = item ? 'ID：' + item.id + ' · ' + summary(item) : '首次保存为下架状态，核对后可上架。';
    $('resource-title').value = item?.title || '';
    $('resource-authors').value = (item?.authors || []).join('\n');
    $('resource-category').value = item?.category || '';
    $('resource-tags').value = (item?.tags || []).join('\n');
    $('resource-size').value = item?.size_bytes || '';
    $('resource-address').value = item?.object_key || '';
    $('resource-order').value = item?.display_order ?? 0;
    $('resource-published').checked = Boolean(item?.published); $('resource-published').disabled = !item;
    coverChoices(item); $('resource-history').replaceChildren(); $('resource-check-result').textContent = '';
    $('resource-check').disabled = !item; $('resource-use-size').hidden = true;
    $('resource-summary').textContent = ''; $('resource-commit').hidden = true;
    $('resource-reload').hidden = !item;
  }
  async function history(item, run) {
    const result = await api('/api/resources/' + item.id + '/history');
    if (generation !== run || current?.id !== item.id || current.revision !== item.revision) return;
    $('resource-history').replaceChildren();
    for (const version of result.items) {
      const row = node('div'); row.className = 'resource-history-row';
      row.append(node('p', '版本 ' + version.revision + ' · ' + version.actor + ' · ' + version.operation + ' · ' + new Date(version.created_at).toLocaleString()),
        node('p', version.record.title + ' · ' + (version.record.published ? '上架' : '下架') + ' · ' + version.record.object_key));
      if (version.revision !== current.revision) {
        const restore = node('button', '恢复为此版本'); restore.type = 'button';
        restore.addEventListener('click', () => act(restore, async () => {
          if (!leave() || !window.confirm('恢复版本 ' + version.revision + ' 的全部资料字段及上下架状态？这会生成新修订。')) return;
          const run = generation;
          const saved = await api('/api/resources/' + current.id + '/restore', 'POST', {revision:current.revision, target_revision:version.revision});
          if (!csrf || run !== generation) return;
          draw(saved); await history(saved, generation); message('已恢复并生成新修订，前台新请求采用当前上架版本。');
        })); row.append(restore);
      }
      $('resource-history').append(row);
    }
  }
  async function open(id) {
    const run = ++generation, item = await api('/api/resources/' + id);
    if (run !== generation || !csrf) return;
    draw(item); await history(item, run);
  }
  function value() {
    const split = id => $(id).value.split('\n').map(text => text.trim()).filter(Boolean);
    const changes = {title:$('resource-title').value.trim(), authors:split('resource-authors'), category:$('resource-category').value.trim() || null,
      tags:split('resource-tags'), size_bytes:Number($('resource-size').value), pdf_address:$('resource-address').value,
      display_order:Number($('resource-order').value), published:current ? $('resource-published').checked : false};
    if ($('resource-cover').value !== '__keep') changes.cover_asset = $('resource-cover').value || null;
    return changes;
  }
  document.addEventListener('admin-session', event => { csrf = event.detail.csrf; });
  document.addEventListener('admin-tab-request',event=>{if(['ai','news'].includes(event.detail)){if(busy||!leave())event.preventDefault();else{dirty=false;generation++;}}});
  document.addEventListener('admin-logout', () => { csrf = ''; current = null; dirty = false; generation++; $('resource-rows').replaceChildren(); $('resource-history').replaceChildren(); });
  $('nav-resources').addEventListener('click', () => act($('nav-resources'), async () => {
    if (!leave()) return;
    if (!document.dispatchEvent(new CustomEvent('admin-tab-request', {cancelable:true,detail:'resources'}))) return;
    $('ai-workspace').hidden = true; $('resource-workspace').hidden = false;
    $('nav-resources').setAttribute('aria-pressed', 'true'); $('nav-ai').setAttribute('aria-pressed', 'false');
    await list();
  }));
  $('resource-search-form').addEventListener('submit', event => { event.preventDefault(); act(event.submitter, list); });
  $('resource-new').addEventListener('click', () => { if (!busy && leave()) { generation++; draw(null); } });
  $('resource-back').addEventListener('click', () => act($('resource-back'), async () => { if (leave()) await list(); }));
  $('resource-reload').addEventListener('click', () => act($('resource-reload'), async () => { if (leave()) await open(current.id); }));
  $('resource-form').addEventListener('input', () => { dirty = true; $('resource-commit').hidden = true; $('resource-summary').textContent = ''; });
  $('resource-form').addEventListener('submit', event => {
    event.preventDefault(); const changes = value();
    const labels = {title:'书名', authors:'作者', category:'分类', tags:'标签', size_bytes:'文件大小', pdf_address:'PDF 地址', display_order:'排序', published:'上架状态', cover_asset:'封面'};
    const fields = Object.keys(changes).filter(key => !current || JSON.stringify(changes[key]) !== JSON.stringify(current[key === 'pdf_address' ? 'object_key' : key]));
    $('resource-summary').textContent = fields.length ? '将保存：' + fields.map(key => labels[key]).join('、') + '。保存后前台新请求即时采用已上架资料；文件能否下载需另行检查。' : '字段未修改。';
    $('resource-commit').hidden = fields.length === 0;
  });
  $('resource-commit').addEventListener('click', () => act($('resource-commit'), async () => {
    if (!$('resource-form').reportValidity()) return;
    const changes = value(), run = generation, serialized = JSON.stringify(changes), item = current;
    const result = item ? await api('/api/resources/' + item.id, 'PATCH', {revision:item.revision, changes}) : await api('/api/resources', 'POST', {changes});
    if (!csrf || run !== generation) return;
    if (serialized !== JSON.stringify(value())) {
      current = result; dirty = true; $('resource-published').disabled = false;
      $('resource-commit').hidden = true; message('保存期间表单有新修改，已保留输入。请再次查看变更并保存。'); return;
    }
    draw(result); await history(result, generation); message('资料已持久保存。刷新公开资料页核对展示和下载入口。');
  }));
  $('resource-check').addEventListener('click', () => act($('resource-check'), async () => {
    if (dirty) throw new Error('请先保存或重新加载，文件检查针对当前已保存地址。');
    const item = current, run = generation;
    const result = await api('/api/resources/' + item.id + '/check', 'POST', {revision:item.revision});
    if (run !== generation || current?.id !== item.id || current.revision !== result.revision) return;
    $('resource-check-result').textContent = ({accessible:'服务器可取得文件元信息；仍需浏览器检查下载。', missing:'服务返回 404，当前地址未找到文件。', unconfirmed:'无法自动确认，请在浏览器核对下载。'}[result.state]) + (result.size_bytes ? ' 返回大小：' + result.size_bytes.toLocaleString() + ' 字节。' : '');
    $('resource-use-size').hidden = !result.size_bytes;
    $('resource-use-size').onclick = () => { $('resource-size').value = result.size_bytes; dirty = true; $('resource-commit').hidden = true; $('resource-summary').textContent = ''; message('文件大小已填入表单，查看变更并保存后生效。'); };
  }));
  window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
})();
