"use strict";
(() => {
  const $ = id => document.getElementById(id);
  let csrf = '';
  const updatePageLabel = () => {
    $('admin-page-label').textContent = $('workspace').hidden ? '私有管理后台' :
      ($('nav-ai').getAttribute('aria-pressed') === 'true' ? 'AI 设置' : '资料管理');
  };
  const navigationObserver = new MutationObserver(updatePageLabel);
  navigationObserver.observe($('workspace'), {attributes:true,attributeFilter:['hidden']});
  for (const id of ['nav-ai','nav-resources']) {
    navigationObserver.observe($(id), {attributes:true,attributeFilter:['aria-pressed']});
  }
  const message = text => { $('message').textContent = text; };
  function loggedOut() {
    csrf = ''; document.dispatchEvent(new Event('admin-logout'));
    $('workspace').hidden = true; $('login').hidden = false;
    $('logout').hidden = true; $('account').textContent = ''; $('password').value = '';
  }
  async function api(path, body) {
    const response = await fetch(path, {method:body === undefined ? 'GET':'POST', credentials:'same-origin', cache:'no-store',
      headers:body === undefined ? {} : {'Content-Type':'application/json','X-CSRF-Token':csrf},
      body:body === undefined ? undefined : JSON.stringify(body), signal:AbortSignal.timeout(15000)});
    const result = await response.json();
    if (!response.ok) { if(response.status === 401) loggedOut(); throw new Error(typeof result.detail === 'string' ? result.detail : '请求格式无效。'); }
    return result;
  }
  async function loggedIn() {
    const session = await api('/api/session'); csrf = session.csrf;
    $('account').textContent = session.username; $('logout').hidden = false;
    $('login').hidden = true; $('workspace').hidden = false;
    document.dispatchEvent(new CustomEvent('admin-session',{detail:{csrf}}));
    $('nav-resources').click();
  }
  async function act(button, fn) { button.disabled = true; try { await fn(); } catch(error) { message(error.message); } finally { button.disabled = false; } }
  $('login-form').addEventListener('submit', event => { event.preventDefault(); act(event.submitter, async () => {
    const password = $('password').value; $('password').value = '';
    await api('/api/login',{username:$('username').value,password}); await loggedIn(); message('登录成功。');
  }); });
  $('logout').addEventListener('click', () => act($('logout'), async () => { await api('/api/logout',{}); loggedOut(); }));
  document.addEventListener('admin-expired',loggedOut);
  loggedIn().catch(loggedOut);
})();
