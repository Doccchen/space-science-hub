'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const make = (tag, text) => { const element = document.createElement(tag); if (text) element.textContent = text; return element; };
  const message = text => { $('message').textContent = text; };
  const numeric = ['timeout','concurrency','visitor_daily','ip_daily','site_daily','token_daily','token_reservation'];
  let csrf = '', current = null, dirty = false, busy = false, generation = 0;
  async function api(path, body) {
    const response = await fetch(path, {method:body === undefined ? 'GET':'POST', credentials:'same-origin', cache:'no-store',
      headers:body === undefined ? {} : {'Content-Type':'application/json','X-CSRF-Token':csrf},
      body:body === undefined ? undefined : JSON.stringify(body), signal:AbortSignal.timeout(15000)});
    const result = await response.json();
    if (!response.ok) {
      if (response.status === 401) document.dispatchEvent(new Event('admin-expired'));
      throw new Error(typeof result.detail === 'string' ? result.detail : '请求未完成。');
    }
    return result;
  }
  async function act(button, fn) {
    if (busy) return;
    busy = true; button.disabled = true; $('ai-settings-form').inert = true;
    try { await fn(); } catch(error) { message(error.message); }
    finally { busy = false; button.disabled = false; $('ai-settings-form').inert = false; }
  }
  const leave = () => !dirty || window.confirm('AI 表单有未保存修改，确定放弃？');
  function renderStatus(data) {
    const names = {applied:'已生效', pending:'等待公开服务加载', failed:'生效失败', offline:'公开服务离线或心跳过期'};
    $('config-status').textContent = names[data.status];
    $('config-versions').textContent = '最新保存版本 ' + data.draft.version + ' · 期望版本 ' + data.desired.version + ' · 公开服务加载版本 ' + (data.loaded?.version || '无');
    $('config-heartbeat').textContent = data.heartbeat ? '最近心跳：' + new Date(data.heartbeat*1000).toLocaleString() : '尚未收到公开服务心跳。';
    $('config-error').textContent = data.error || (data.upstream_error ? '最近问答失败：' + data.upstream_error + '。配置加载成功不代表云端认证或回答已验证。' : '');
    $('config-runtime').textContent = data.loaded ? (data.loaded.config.enabled ? '当前启用 AI。' : '当前停用 AI。') : '尚无公开进程确认配置。';
    const usage = data.usage;
    $('config-usage').textContent = usage ? '今日（北京时间）已记录 ' + usage.requests + ' 次请求 · 用量记账 ' + usage.tokens_accounted.toLocaleString() + ' Token · 在途预留 ' + usage.pending_reservation.toLocaleString() + ' · 正在调用 ' + usage.active : '用量信息暂不可用。';
    $('config-tests').replaceChildren();
    for (const job of data.tests) {
      const text = '版本 ' + job.version + ' · ' + ({queued:'等待执行',running:'执行中',done:'完成',failed:'失败'}[job.state] || job.state);
      const row = make('p', text);
      if (job.result?.error) row.append(make('span', ' · ' + job.result.error));
      if (job.state === 'done') row.append(make('span', ' · 取得来源 ' + job.result.source_count + ' 项 · 用量 ' + (job.result.tokens ?? '未返回，保留预留量')));
      $('config-tests').append(row);
    }
    if (!data.tests.length) $('config-tests').append(make('p', '尚无实际问答测试记录。'));
    $('config-restore').disabled = !data.can_restore;
    $('config-verified').textContent = data.tests.some(job => job.version === data.draft.version && job.state === 'done') ? '此保存版本已有问答测试记录；请核对是否取得来源。' : '此保存版本尚未实际验证。可直接应用，远端错误需人工检查或回退。';
  }
  function populate(data) {
    current = data; dirty = false;
    const config = data.draft.config;
    $('config-enabled').checked = config.enabled; $('config-workspace').value = config.workspace; $('config-agent').value = config.agent;
    for (const name of numeric) $('config-' + name).value = config[name];
    $('config-new-key').value = ''; $('config-key-state').textContent = data.draft.key_configured ? '已配置 API Key；留空保持当前草稿的密钥。' : '尚未配置 API Key。';
    $('config-fee').checked = false; $('config-invalidate').checked = false; renderStatus(data);
    $('config-history').replaceChildren();
    for (const item of data.versions) {
      const row = make('div'); row.className = 'resource-history-row';
      row.append(make('p', '版本 ' + item.version + ' · ' + item.actor + ' · ' + new Date(item.created_at).toLocaleString()),
        make('p', (item.config.enabled ? '启用' : '停用') + ' · ' + item.config.workspace + ' · ' + item.config.agent + ' · ' + (item.key_configured ? '密钥已配置' : '无密钥')));
      $('config-history').append(row);
    }
  }
  async function load() {
    const run = ++generation;
    let data;
    try { data = await api('/api/ai-config'); }
    catch(error) { if(run===generation){current=null;$('config-status').textContent='配置暂不可用';$('config-error').textContent=error.message;}throw error; }
    if (run !== generation || !csrf) return;
    populate(data);
  }
  function fields() {
    const values = {enabled:$('config-enabled').checked, workspace:$('config-workspace').value.trim(), agent:$('config-agent').value.trim()};
    for (const name of numeric) values[name] = Number($('config-' + name).value);
    return values;
  }
  document.addEventListener('admin-session', event => { csrf = event.detail.csrf; });
  document.addEventListener('admin-logout', () => { csrf = ''; current = null; dirty = false; generation++; $('config-new-key').value = ''; $('config-tests').replaceChildren(); $('config-history').replaceChildren(); });
  document.addEventListener('admin-tab-request', event => { if (['resources','news'].includes(event.detail)){if(busy||!leave())event.preventDefault();else{dirty=false;generation++;$('config-new-key').value='';}} });
  $('nav-ai').addEventListener('click', () => act($('nav-ai'), async () => {
    if (!leave() || !document.dispatchEvent(new CustomEvent('admin-tab-request',{cancelable:true,detail:'ai'}))) return;
    $('resource-workspace').hidden = true; $('ai-workspace').hidden = false;
    $('nav-ai').setAttribute('aria-pressed','true'); $('nav-resources').setAttribute('aria-pressed','false');
    await load();
  }));
  $('ai-settings-form').addEventListener('input', () => { dirty = true; });
  $('ai-settings-form').addEventListener('submit', event => { event.preventDefault(); act(event.submitter, async () => {
    if (!current) throw new Error('请先读取 AI 配置。');
    const config = fields(), newKey = $('config-new-key').value, run = generation;
    $('config-new-key').value = '';
    await api('/api/ai-config/drafts', {revision:current.revision, config, new_key:newKey});
    if (!csrf || run !== generation) return;
    await load(); message('草稿已加密保存，访客仍使用当前生效版本。');
  }); });
  $('config-reload').addEventListener('click', () => act($('config-reload'), async () => { if (leave()) await load(); }));
  $('config-apply').addEventListener('click', () => act($('config-apply'), async () => {
    if (!current || dirty) throw new Error('请先保存草稿，再应用已保存版本。');
    const invalidate = $('config-invalidate').checked;
    if (!window.confirm('应用保存版本 ' + current.draft.version + '？新请求将采用该配置；不会自动调用百炼验证。')) return;
    await api('/api/ai-config/apply', {revision:current.revision, version:current.draft.version, invalidate_sessions:invalidate});
    await load(); message('已提交应用，请查看公开服务加载状态。');
  }));
  $('config-restore').addEventListener('click', () => act($('config-restore'), async () => {
    if (!current || !leave() || !window.confirm('恢复上一生效版本参数并生成新修订？旧会话将需要重新开始。')) return;
    await api('/api/ai-config/restore', {revision:current.revision}); await load(); message('已提交回退，新请求采用回退配置后生效。');
  }));
  $('config-test').addEventListener('click', () => act($('config-test'), async () => {
    if (!current || dirty) throw new Error('请先保存草稿，再测试已保存版本。');
    if (!$('config-fee').checked) throw new Error('请确认实际测试会调用百炼并可能产生费用。');
    await api('/api/ai-config/test', {version:current.draft.version, fee_confirmed:true});
    $('config-fee').checked = false; message('测试已排队，与访客共用额度和并发；结果将在下方显示。');
  }));
  setInterval(async () => {
    if (!csrf || $('ai-workspace').hidden || busy || !current) return;
    const run = generation;
    try {
      const data = await api('/api/ai-config');
      if (run !== generation || !csrf) return;
      renderStatus(data);
      // Only runtime/test state is refreshed; preserve unsaved form values and revision conflicts.
    } catch(error) { if (csrf) $('config-error').textContent = error.message; }
  }, 2000);
  window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue=''; } });
})();
