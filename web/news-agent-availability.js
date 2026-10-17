'use strict';
(() => {
  let state = {enabled:false, message:'正在读取新闻科普状态…'}, pending = null;
  function decorate(button) {
    button.disabled = !state.enabled;
    button.textContent = state.enabled ? '科普解读与提问' : state.message;
    button.title = state.enabled ? '围绕这篇新闻生成解读或提问' : state.message;
    button.setAttribute('aria-disabled', String(!state.enabled));
  }
  async function refresh() {
    if (pending) return pending;
    pending = (async () => {
      try {
        const response = await fetch('/api/news-agent/status', {
          credentials:'same-origin', cache:'no-store', signal:AbortSignal.timeout(10000)
        });
        const data = await response.json();
        if (!response.ok || typeof data.enabled !== 'boolean') throw new Error('availability');
        state = {enabled:data.enabled, message:typeof data.message === 'string' ? data.message : '新闻科普暂未开放。'};
      } catch {
        state = {enabled:false, message:'新闻科普状态暂不可用'};
      }
      document.querySelectorAll('.news-agent-entry').forEach(decorate);
    })();
    try { await pending; } finally { pending = null; }
  }
  const visible = () => !document.hidden && !document.getElementById('news')?.classList.contains('hidden');
  window.newsAgentAvailability = {decorate, refresh};
  document.addEventListener('pagechange', event => { if (event.detail === 'news') refresh(); });
  document.addEventListener('visibilitychange', () => { if (visible()) refresh(); });
  setInterval(() => { if (visible()) refresh(); }, 15000);
  refresh();
})();
