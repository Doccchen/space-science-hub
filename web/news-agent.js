'use strict';
const make = (tag, text = '', cls = '') => {
  const node = document.createElement(tag); node.textContent = text; node.className = cls; return node;
};
const stages = {queued:'任务已保存', reading:'正在读取发布方原文…', generating:'正在生成解读…', complete:'已完成', error:'任务失败', interrupted:'任务已中断'};
const readStates = {unsupported:'该来源的原文解析暂未适配。', blocked:'原文读取未开放。', withdrawn:'新闻已撤下或来源已停用。', unavailable:'原文暂不可读取。'};
async function api(path, options = {}) {
  const reply = await fetch(path, {cache:'no-store', credentials:'same-origin', ...options,
    headers:{'Content-Type':'application/json', ...options.headers}, signal:AbortSignal.timeout(15000)});
  if (reply.status === 204) return null;
  const body = await reply.json();
  if (!reply.ok) { const error = new Error(body.error?.message || '暂时无法连接新闻科普服务。'); error.code = body.error?.code; throw error; }
  return body;
}
export function mount(parent, item) {
  const section = make('section', '', 'news-agent'); section.setAttribute('aria-label', '科普解读与提问');
  const heading = make('h2', '科普解读与提问'), status = make('p', '正在确认服务状态…', 'news-agent-status');
  status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
  const transcript = make('div', '', 'news-agent-thread'), controls = make('div', '', 'news-agent-actions');
  const generate = make('button', '生成科普解读', 'secondary'), clear = make('button', '清除个人会话', 'secondary');
  generate.type = clear.type = 'button'; controls.append(generate, clear);
  const form = make('form'), label = make('label', '围绕这篇新闻提问'), input = make('textarea');
  input.id = 'news-question-' + item.id; label.htmlFor = input.id; input.maxLength = 1500; input.rows = 3;
  input.placeholder = '例如：这次任务与以往相比有什么进展？';
  const send = make('button', '发送问题', 'secondary'); send.type = 'submit'; form.append(label, input, send);
  const notice = make('p', '首次打开不会调用模型。生成后离开页面不一定取消上游调用；个人解读保存为私有草稿。', 'news-agent-notice');
  section.append(heading, make('p', item.title, 'news-agent-article'), status, transcript, controls, form, notice); parent.append(section);
  const storageKey = 'space-news-conversation-' + item.id;
  let conversation = null, ready = false, busy = false, destroyed = false, pollTimer = null, pending = null;
  const alive = () => !destroyed && section.isConnected && !document.hidden;
  function saved(value) { try { if (value) sessionStorage.setItem(storageKey, value); else sessionStorage.removeItem(storageKey); } catch { /* storage unavailable */ } }
  try { conversation = sessionStorage.getItem(storageKey); } catch { /* storage unavailable */ }
  function buttons() { generate.disabled = send.disabled = !ready || busy; input.disabled = !ready || busy; clear.disabled = !conversation; }
  function addJob(job) {
    const existing = transcript.querySelector('[data-job-id="' + job.job_id + '"]');
    if (existing) existing.remove();
    if (!job.result && !job.error) return;
    const card = make('article', '', 'news-agent-message'); card.dataset.jobId = job.job_id;
    card.append(make('p', job.question, 'news-agent-question'));
    if (job.result) {
      card.append(make('div', job.result.answer, 'news-agent-answer'), make('p', job.result.notice, 'news-agent-notice'));
      const source = make('a', '已读取：' + job.result.news_source.title + ' ↗');
      try {
        const url = new URL(job.result.news_source.url);
        if (['https:', 'http:'].includes(url.protocol) && !url.username && !url.password && url.href === new URL(item.original_url).href) source.href = url.href;
      } catch { /* invalid metadata */ }
      source.target = '_blank'; source.rel = 'noopener noreferrer'; card.append(source);
      if (job.result.news_citations?.length) card.append(make('p', '正文引用：' + job.result.news_citations.join('、'), 'news-agent-notice'));
    } else card.append(make('p', job.error.message, 'news-agent-status'));
    transcript.append(card);
  }
  async function poll(jobId) {
    if (!alive()) return;
    try {
      const job = await api('/api/news-agent/jobs/' + jobId);
      if (!alive()) return;
      status.textContent = stages[job.stage] || '任务状态待确认';
      if (['complete', 'error', 'interrupted'].includes(job.stage)) { addJob(job); busy = false; pending = null; buttons(); return; }
      pollTimer = setTimeout(() => poll(jobId), 1500);
    } catch (error) {
      if (!alive()) return;
      status.textContent = error.message + ' 刷新页面可查询已保存任务。';
      if (['session_expired', 'context_changed', 'withdrawn'].includes(error.code)) { conversation = null; saved(null); busy = false; pending = null; buttons(); }
      else pollTimer = setTimeout(() => poll(jobId), 5000);
    }
  }
  async function submit(explanation) {
    if (!alive() || !ready || busy) return;
    const question = input.value.trim(); if (!explanation && !question) { input.focus(); return; }
    busy = true; buttons(); status.textContent = '正在提交任务…';
    try {
      if (!conversation) {
        await api('/api/ai/visitor', {method:'POST', body:'{}'});
        const response = await api('/api/news/' + item.id + '/conversations', {method:'POST', body:'{}'});
        conversation = response.conversation_id; saved(conversation); buttons();
      }
      // A network retry retains the exact request ID and question.
      const path = explanation ? '/api/news/' + item.id + '/explanation-jobs' : '/api/news-agent/messages';
      pending = pending || {path, body:{conversation_id:conversation, request_id:crypto.randomUUID(), ...(explanation ? {} : {question})}};
      const response = await api(pending.path, {method:'POST', body:JSON.stringify(pending.body)});
      if (!alive()) return;
      input.value = ''; poll(response.job_id);
    } catch (error) {
      if (!alive()) return;
      status.textContent = error.message; busy = false;
      if (error.code) pending = null; // A definite server rejection did not enqueue a new task.
      if (['session_expired', 'context_changed', 'withdrawn'].includes(error.code)) { conversation = null; saved(null); }
      buttons();
    }
  }
  form.addEventListener('submit', event => { event.preventDefault(); submit(false); });
  generate.addEventListener('click', () => submit(true));
  clear.addEventListener('click', async () => {
    if (!conversation) return;
    clear.disabled = true;
    try {
      await api('/api/news-agent/conversations/' + conversation, {method:'DELETE'});
      clearTimeout(pollTimer); conversation = null; pending = null; busy = false; saved(null); transcript.replaceChildren();
      status.textContent = '个人会话已清除。已开始的模型调用可能仍会完成。'; buttons();
    } catch (error) { status.textContent = error.message; buttons(); }
  });
  buttons();
  (async () => {
    try {
      const state = await api('/api/news/' + item.id + '/agent-status');
      if (!alive()) return;
      ready = state.enabled && state.read_status === 'pending';
      status.textContent = ready ? '按需读取原文，围绕当前新闻连续提问。' : state.enabled ? (readStates[state.read_status] || '原文暂不可读取。') : state.message;
      if (ready && conversation) {
        try {
          const history = await api('/api/news-agent/conversations/' + conversation);
          if (!alive()) return;
          history.jobs.forEach(addJob);
          const running = history.jobs.find(job => ['queued', 'reading', 'generating'].includes(job.stage));
          if (running) { busy = true; poll(running.job_id); }
        } catch (error) { if (error.code) { conversation = null; saved(null); } status.textContent = error.message; }
      }
      buttons();
    } catch (error) { if (alive()) status.textContent = error.message; }
  })();
  // Remove listeners/timers with the reader; replies for an old article cannot enter a new panel.
  const observer = new MutationObserver(() => { if (!section.isConnected) { destroyed = true; clearTimeout(pollTimer); observer.disconnect(); } });
  observer.observe(parent, {childList:true});
}
