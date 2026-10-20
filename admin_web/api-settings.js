'use strict';
(() => {
  const $=id=>document.getElementById(id),make=(tag,text)=>{const n=document.createElement(tag);n.textContent=text;return n;};
  let csrf='',provider='wanfang',data=null,current=null,dirty=false,busy=false,switching=false,generation=0;
  const feedback=text=>{$('lit-feedback').textContent=text;};
  const leave=()=>!dirty||window.confirm('API 表单有未保存修改，确定放弃？');
  function clear(){for(const id of ['lit-key','lit-token'])$(id).value='';for(const id of ['lit-clear-key','lit-clear-token','lit-fee'])$(id).checked=false;}
  async function api(path,body){
    const response=await fetch('/api/literature-config'+path,{method:body===undefined?'GET':'POST',credentials:'same-origin',cache:'no-store',headers:body===undefined?{}:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(path.endsWith('/test')?65000:15000)});
    const value=await response.json();if(!response.ok){if(response.status===401)document.dispatchEvent(new Event('admin-expired'));throw new Error(typeof value.detail==='string'?value.detail:'请求未完成，请重新读取配置。');}return value;
  }
  function status(row){
    $('lit-state').textContent=({applied:'已生效',pending:'等待论文检索服务加载',offline:'尚未收到检索服务心跳',failed:'加载失败'})[row.status]||'状态未知';
    $('lit-versions').textContent='草稿版本 '+row.draft.version+' · 应用版本 '+row.applied.version+' · 加载版本 '+(row.loaded_version||'无');
    $('lit-usage').textContent='今日已请求 '+row.used_today+' 次 · 生效上限 '+row.applied.config.daily_limit+' 次';
    $('lit-runtime').textContent='已应用配置：'+(row.applied.config.enabled?'启用':'停用')+(row.heartbeat?' · 最近心跳 '+new Date(row.heartbeat*1000).toLocaleString():'');
    $('lit-error').textContent=row.error||'';$('lit-restore').disabled=!row.can_restore;
    $('lit-tests').replaceChildren();
    for(const test of row.tests){$('lit-tests').append(make('p','版本 '+test.version+' · '+new Date(test.created*1000).toLocaleString()+' · '+(test.result?.message||(test.state==='started'?'尚未收到结果，请勿重复点击':'未完成'))+(test.result?.ok?' · 返回 '+test.result.count+' 条':'')));}
    if(!row.tests.length)$('lit-tests').append(make('p','尚无连接测试记录。'));
  }
  function populate(){
    const row=data.providers.find(r=>r.provider===provider);current=row;
    $('lit-init').hidden=data.initialized;$('lit-controls').hidden=!data.initialized;
    if(!row)return;
    const c=row.draft.config;$('lit-enabled').checked=c.enabled;$('lit-authorized').checked=c.authorized;$('lit-timeout').value=c.timeout;$('lit-limit').value=c.daily_limit;
    clear();dirty=false;status(row);
    $('lit-key-state').textContent=row.draft.key_configured?'已配置 Key；留空保留，不回显原值。':'尚未配置 Key。';
    $('lit-token-state').textContent=row.draft.token_configured?'已配置机构令牌；留空保留。':'尚未配置机构令牌。';
    $('lit-history').replaceChildren();
    for(const v of row.versions)$('lit-history').append(make('p','版本 '+v.version+' · '+(v.config.enabled?'启用':'停用')+' · '+v.actor+' · '+new Date(v.created_at).toLocaleString()+' · '+(v.key_configured?'已配置密钥':'无密钥')));
  }
  async function load(){const run=++generation;const value=await api('');if(run!==generation||!csrf)return;data=value;populate();}
  async function act(button,fn){if(busy)return;busy=true;button.disabled=true;$('lit-form').inert=true;try{await fn();}catch(error){feedback(error.name==='TimeoutError'?'等待超时，请重新读取测试记录；不会自动重复请求。':error.message);}finally{busy=false;button.disabled=false;$('lit-form').inert=false;}}
  async function select(name){
    if(busy||!leave())return;
    const event=new CustomEvent('admin-tab-request',{cancelable:true,detail:name==='bailian'?'ai':'literature'});switching=true;const accepted=document.dispatchEvent(event);switching=false;if(!accepted)return;
    generation++;dirty=false;clear();current=null;feedback('');$('message').textContent='';
    document.querySelectorAll('[data-api-tab]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.apiTab===name)));
    $('bailian-panel').hidden=name!=='bailian';$('literature-panel').hidden=name==='bailian';
    if(name==='bailian'){document.dispatchEvent(new Event('bailian-open'));return;}
    provider=name;const wf=provider==='wanfang';$('lit-title').textContent=wf?'万方 AI HUB':'ScienceDirect';
    $('lit-description').textContent=wf?'中文期刊文献检索 · APP_KEY 认证':'Elsevier 文献检索 · API Key 与可选机构令牌';
    $('lit-endpoint').textContent=wf?'官方接口：https://api.wfdata.com/openwanfang/getQuery':'官方接口：https://api.elsevier.com/content/search/sciencedirect';
    $('lit-token-fields').hidden=wf;
    $('lit-permission-note').textContent=wf?'请确认账号已开通文献检索服务及相应展示权限。':'API Key 本身不授予数据访问权；须确认已获适用于本站访客的展示授权。此版本不保存 ScienceDirect 检索结果到浏览器。';
    $('lit-controls').hidden=true;feedback('正在读取配置…');
    try{await load();feedback('');}catch(error){feedback(error.message);}
  }
  document.querySelectorAll('[data-api-tab]').forEach(b=>b.onclick=()=>select(b.dataset.apiTab));
  document.addEventListener('admin-session',e=>{csrf=e.detail.csrf;});
  document.addEventListener('admin-logout',()=>{csrf='';generation++;current=null;data=null;dirty=false;clear();$('lit-controls').hidden=true;});
  document.addEventListener('admin-tab-request',e=>{if(!switching&&['resources','ai'].includes(e.detail)&&!$('literature-panel').hidden){if(busy||!leave())e.preventDefault();else{dirty=false;generation++;clear();}}});
  $('nav-ai').addEventListener('click',()=>{if(!$('literature-panel').hidden&&csrf&&!$('ai-workspace').hidden)load().catch(e=>feedback(e.message));});
  $('lit-form').addEventListener('input',()=>{dirty=true;});
  $('lit-form').onsubmit=e=>{e.preventDefault();act(e.submitter,async()=>{if(!current)throw new Error('请先读取配置。');const body={revision:current.revision,config:{enabled:$('lit-enabled').checked,authorized:$('lit-authorized').checked,timeout:Number($('lit-timeout').value),daily_limit:Number($('lit-limit').value)},new_key:$('lit-key').value.trim(),new_insttoken:$('lit-token').value.trim(),clear_key:$('lit-clear-key').checked,clear_insttoken:$('lit-clear-token').checked};clear();await api('/'+provider+'/drafts',body);await load();feedback('草稿已加密保存，前台配置未改变。');});};
  $('lit-reload').onclick=()=>act($('lit-reload'),async()=>{if(leave())await load();});
  $('lit-initialize').onclick=()=>act($('lit-initialize'),async()=>{await api('/initialize',{});await load();feedback('文献 API 管理已初始化，两项服务均默认停用。');});
  $('lit-apply').onclick=()=>act($('lit-apply'),async()=>{if(!current||dirty)throw new Error('请先保存草稿。');await api('/'+provider+'/apply',{revision:current.revision,version:current.draft.version});await load();feedback('已提交应用，请核对论文检索服务加载状态。');});
  $('lit-restore').onclick=()=>act($('lit-restore'),async()=>{if(!current||!leave()||!window.confirm('恢复上一应用版本？'))return;await api('/'+provider+'/restore',{revision:current.revision});await load();feedback('已提交恢复，请核对运行状态。');});
  $('lit-test').onclick=()=>act($('lit-test'),async()=>{if(!current||dirty)throw new Error('请先保存草稿。');if(!$('lit-fee').checked)throw new Error('请勾选确认本次测试会请求供应商。');$('lit-fee').checked=false;feedback('正在测试已保存草稿，请等待…');const result=await api('/'+provider+'/test',{version:current.draft.version,fee_confirmed:true});await load();feedback(result.message);});
  setInterval(async()=>{if(!csrf||busy||!current||dirty||$('ai-workspace').hidden||$('literature-panel').hidden)return;const run=generation,name=provider;try{const value=await api('');if(run!==generation||!csrf)return;const row=value.providers.find(r=>r.provider===name);if(row)status(row);}catch(error){if(run===generation)feedback(error.message);}},5000);
  window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
})();
