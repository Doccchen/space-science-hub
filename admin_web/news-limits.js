'use strict';
(() => {
  const host = document.getElementById('ai-workspace');
  if (!host) return;
  const make = (tag,text='') => { const node=document.createElement(tag);node.textContent=text;return node; };
  const section=make('section');section.className='admin-panel';section.id='news-agent-limits';section.hidden=true;
  const nav=make('button','新闻 Agent');nav.id='nav-news-agent';nav.type='button';nav.setAttribute('aria-pressed','false');document.getElementById('nav-ai').after(nav);
  section.append(make('h2','新闻 Agent · 独立额度'),make('p','仅用于新闻科普，不与普通知识库问答共用次数、Token 记账或并发。此处修改额度不会开启新闻问答；云端实际费用按该服务账单核对。'));
  const status=make('p','正在读取新闻配置…'),usage=make('p'),connection=make('p'),form=make('form'),fields=make('div');
  status.setAttribute('role','status');fields.className='resource-fields';
  const labels={timeout:'新闻超时（秒）',concurrency:'新闻并发上限',visitor_daily:'新闻访客每日次数',ip_daily:'新闻 IP 每日次数',site_daily:'新闻全站每日次数',token_daily:'新闻每日 Token 用量约束',token_reservation:'新闻每次 Token 预留量'};
  const inputs={};
  for(const [name,title] of Object.entries(labels)){
    const label=make('label',title),input=make('input');input.type='number';input.min='1';input.max=String(name==='timeout'?120:name==='concurrency'?4:10000000);input.step='1';input.required=true;input.id='news-limit-'+name;label.htmlFor=input.id;label.append(input);fields.append(label);inputs[name]=input;
  }
  const save=make('button','保存新闻额度草稿');save.type='submit';save.className='primary';form.append(fields,save);
  const apply=make('button','应用新闻额度草稿'),reload=make('button','重新读取新闻额度');apply.type=reload.type='button';
  const history=make('div');section.append(status,connection,usage,form,apply,reload,make('h3','新闻额度版本历史'),history);host.after(section);
  let csrf='',current=null,dirty=false,busy=false,epoch=0;
  async function api(path,body){
    const reply=await fetch('/api/news-agent-limits'+path,{method:body?'POST':'GET',credentials:'same-origin',cache:'no-store',headers:body?{'Content-Type':'application/json','X-CSRF-Token':csrf}:{},body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(15000)});
    const data=await reply.json();if(!reply.ok){if(reply.status===401)document.dispatchEvent(new Event('admin-expired'));throw new Error(typeof data.detail==='string'?data.detail:'新闻额度请求失败。');}return data;
  }
  function render(data,populate=false){
    status.textContent='新闻额度：'+({applied:'已生效',pending:'等待服务加载',failed:'加载失败',offline:'心跳暂不可用'}[data.status]||data.status)+' · 草稿 '+data.draft.version+' · 目标 '+data.desired.version+' · 已加载 '+(data.loaded?.version||'无');
    const value=data.usage;
    connection.textContent=value?('新闻应用 '+value.application_id+' · '+value.region+' · '+(value.enabled?'问答已开放':'问答未开放')):'新闻连接和运行状态等待服务上报。';
    usage.textContent=value?('新闻今日（北京时间）：'+value.requests+' 次请求 · Token 记账 '+value.tokens_accounted.toLocaleString()+' · 在途预留 '+value.pending_reservation+' · 新闻并发 '+value.active):'新闻独立用量暂无数据。';
    if(data.error)status.textContent+=' · '+data.error;
    if(populate){current=data;dirty=false;for(const name of Object.keys(inputs))inputs[name].value=data.draft.config[name];history.replaceChildren();for(const version of data.versions)history.append(make('p','新闻版本 '+version.version+' · '+version.actor+' · '+new Date(version.created_at).toLocaleString()));}
  }
  async function load(){const ticket=++epoch;const data=await api('');if(ticket===epoch&&csrf)render(data,true);}
  async function action(fn){if(busy)return;busy=true;save.disabled=apply.disabled=reload.disabled=true;form.inert=true;try{await fn();}catch(error){status.textContent=error.message;}finally{busy=false;save.disabled=apply.disabled=reload.disabled=false;form.inert=false;}}
  document.addEventListener('admin-session',event=>{csrf=event.detail.csrf;});
  document.addEventListener('admin-logout',()=>{csrf='';current=null;dirty=false;epoch++;form.reset();history.replaceChildren();section.hidden=true;nav.setAttribute('aria-pressed','false');});
  nav.addEventListener('click',()=>action(async()=>{if(dirty&&!window.confirm('放弃未保存的新闻额度修改？'))return;if(!document.dispatchEvent(new CustomEvent('admin-tab-request',{cancelable:true,detail:'news'})))return;document.getElementById('message').textContent='';host.hidden=true;document.getElementById('resource-workspace').hidden=true;section.hidden=false;nav.setAttribute('aria-pressed','true');for(const id of ['nav-ai','nav-resources'])document.getElementById(id).setAttribute('aria-pressed','false');queueMicrotask(()=>{const label=document.getElementById('admin-page-label');if(label&&nav.getAttribute('aria-pressed')==='true')label.textContent='新闻 Agent';});await load();}));
  document.addEventListener('admin-tab-request',event=>{if(event.defaultPrevented||event.detail==='news')return;if(busy||(dirty&&!window.confirm('新闻额度有未保存修改，确定放弃？')))event.preventDefault();else{dirty=false;epoch++;section.hidden=true;nav.setAttribute('aria-pressed','false');}});
  form.addEventListener('input',()=>{dirty=true;});
  form.addEventListener('submit',event=>{event.preventDefault();action(async()=>{if(!current)throw new Error('请先读取新闻额度。');const config={};for(const name of Object.keys(inputs))config[name]=Number(inputs[name].value);await api('/drafts',{revision:current.revision,config});await load();status.textContent+=' · 已保存；需单独应用新闻草稿。';});});
  apply.addEventListener('click',()=>action(async()=>{if(!current||dirty)throw new Error('请先保存新闻额度草稿。');if(!window.confirm('仅应用新闻额度版本 '+current.draft.version+'？不会改变普通知识库问答或启动模型调用。'))return;await api('/apply',{revision:current.revision,version:current.draft.version});await load();}));
  reload.addEventListener('click',()=>action(async()=>{if(!dirty||window.confirm('放弃未保存的新闻额度修改？'))await load();}));
  setInterval(async()=>{if(!csrf||section.hidden||busy||!current)return;const ticket=epoch;try{const data=await api('');if(ticket===epoch&&csrf)render(data);}catch(error){if(csrf)status.textContent=error.message;}},2000);
  window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
})();
