'use strict';
(() => {
  const byId = id => document.getElementById(id);
  const form = byId('ai-form'), question = byId('ai-question'), send = byId('ai-send'), fresh = byId('ai-new');
  const thread = byId('ai-thread'), welcome = byId('ai-welcome'), feedback = byId('ai-feedback'), waiting = byId('ai-waiting');
  let enabled = false, busy = false, session = null, generation = 0, controller = null, initialized = false;
  let availabilityText='正在读取问答服务状态…';
  let statusRequest=0;
  const make = (tag, cls, value) => { const node = document.createElement(tag); if (cls) node.className = cls; if (value) node.textContent = value; return node; };
  function controls() {
    const hint=byId('ai-input-hint');if(hint){hint.hidden=!enabled;hint.textContent=busy?'正在处理问题，请等待回答。':'输入问题后发送，Ctrl / ⌘ + Enter 也可提交。';}
    send.textContent=busy?'正在整理回答…':'发送问题 ↑';send.setAttribute('aria-busy',String(busy));
    send.disabled = !enabled || busy || !question.value.trim(); question.disabled = !enabled || busy;
    const counter=byId('ai-counter');if(counter)counter.textContent = question.value.length + ' / 1500'; waiting.hidden = !busy;
    thread.setAttribute('aria-busy', String(busy));
    const starters=byId('ai-starters');if(starters){starters.hidden=!enabled;
    starters.querySelectorAll('button').forEach(button=>{button.disabled=!enabled||busy;});}
    byId('ai-welcome-copy').textContent=enabled?'基于本站专属知识库，把专业概念讲清楚。':availabilityText;
    question.placeholder=enabled?'例如：固体火箭发动机为什么能产生推力？':'服务恢复后即可在这里提问。';
    byId('home').dataset.aiAvailable=String(enabled);
    byId('home').dataset.aiConversation=String(thread.children.length>0);
  }
  async function json(path, options = {}) {
    const response = await fetch(path, {...options, credentials:'same-origin', cache:'no-store'});
    const data = response.status === 204 ? {} : await response.json();
    if (!response.ok) { const error = new Error(data.error?.message || '请求未完成，请稍后再试。'); error.code = data.error?.code; throw error; }
    return data;
  }
  // DOM-only Markdown subset: no raw HTML, links, images or script evaluation.
  function inline(node,text) {
    for (const part of text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)) {
      if (part.startsWith('**') && part.endsWith('**')) node.append(make('strong','',part.slice(2,-2)));
      else if (part.startsWith('`') && part.endsWith('`')) node.append(make('code','',part.slice(1,-1)));
      else node.append(document.createTextNode(part));
    }
  }
  function markdown(text) {
    const body=make('div','ai-message-content'); let list=null,code=null;
    for(const line of text.split('\n')) {
      if(line.startsWith('```')) {if(code)code=null;else{code=make('pre');body.append(code);}list=null;continue;}
      if(code){code.append(document.createTextNode(line+'\n'));continue;}
      if(!line.trim()){list=null;continue;}
      const heading=/^(#{1,4})\s+(.+)$/.exec(line),bullet=/^\s*[-*]\s+(.+)$/.exec(line);
      if(heading){const h=make('h'+Math.min(4,heading[1].length+1));inline(h,heading[2]);body.append(h);list=null;}
      else if(bullet){if(!list){list=make('ul');body.append(list);}const item=make('li');inline(item,bullet[1]);list.append(item);}
      else{list=null;const p=make('p');inline(p,line);body.append(p);}
    }
    return body;
  }
  function message(role,text,result) {
    const box=make('section','ai-message');box.dataset.role=role;
    box.append(make('p','ai-message-label',role==='user'?'你的问题':'知识库科普'));
    box.append(role==='user'?make('div','ai-message-content',text):markdown(text));
    if(result?.sources?.length){
      const details=make('details','ai-sources'),summary=make('summary','','本次检索资料 · '+result.sources.length+' 项'),sources=make('div','ai-source-list');
      for(const source of result.sources){const row=make('div','ai-source');row.append(make('strong','',source.name));if(source.positions?.length)row.append(make('small','','返回位置：'+source.positions.join('、')));sources.append(row);}
      details.append(summary,sources,make('p','ai-source-notice',result.notice));box.append(details);
    }
    if(result)box.append(make('p','ai-message-foot',result.status==='insufficient'?'本次未取得可靠依据，可补充问题后继续。':'本次对话还可追问 '+result.remaining_rounds+' 轮。'));
    thread.append(box);welcome.hidden=true;return box;
  }
  async function init() {
    if(initialized)return;initialized=true;
    const check=++statusRequest;
    controls();
    try{const status=await json('/api/ai/status',{signal:AbortSignal.timeout(10000)});if(check!==statusRequest)return;enabled=status.enabled;availabilityText=status.message;byId('ai-service-text').textContent=enabled?'专属知识库 · 可以提问':status.message;byId('ai-status-dot').dataset.ready=String(enabled);const retention=byId('ai-retention');if(retention)retention.textContent='对话历史保留约 '+Math.round(status.history_retention_seconds/60)+' 分钟，新对话会清除本站旧对话。';if(feedback.textContent==='无法读取问答服务状态，请重新打开此页面。')feedback.textContent='';}
    catch{if(check!==statusRequest)return;enabled=false;availabilityText='服务状态暂不可用，请稍后重新打开页面。';byId('ai-service-text').textContent='服务状态暂不可用';byId('ai-status-dot').dataset.ready='false';feedback.textContent='无法读取问答服务状态，请重新打开此页面。';initialized=false;}
    controls();
  }
  async function reset(){
    const old=session;session=null;generation++;controller?.abort();controller=null;busy=false;
    thread.replaceChildren();welcome.hidden=false;question.value='';feedback.textContent='';fresh.disabled=true;controls();
    try{if(old)await json('/api/ai/conversations/'+old,{method:'DELETE'});}
    catch(error){if(error.code!=='session_expired')feedback.textContent='页面已清空，旧对话暂未确认删除，将按保留期限过期。';}
    finally{fresh.disabled=false;controls();if(enabled)question.focus();}
  }
  form.addEventListener('submit',async event=>{
    event.preventDefault();const text=question.value.trim();if(!text||!enabled||busy||fresh.disabled)return;
    const run=++generation;busy=true;feedback.textContent='';controls();
    controller=new AbortController();const localController=controller,signal=controller.signal;
    const timeout=setTimeout(()=>localController.abort(),135000);let submitted=false;
    try{
      if(!session){const data=await json('/api/ai/conversations',{method:'POST',signal});if(run!==generation)return;session=data.conversation_id;}
      const bytes=crypto.getRandomValues(new Uint8Array(16));bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
      const hex=[...bytes].map(value=>value.toString(16).padStart(2,'0')).join('');const requestId=[hex.slice(0,8),hex.slice(8,12),hex.slice(12,16),hex.slice(16,20),hex.slice(20)].join('-');
      message('user',text);submitted=true;question.value='';controls();
      const data=await json('/api/ai/ask',{method:'POST',headers:{'Content-Type':'application/json'},signal,body:JSON.stringify({conversation_id:session,request_id:requestId,question:text})});
      if(run!==generation)return;const answer=message('assistant',data.answer,data);byId('ai-complete').textContent='回答已完成，可查看本次检索资料。';
      if(data.remaining_rounds===0)feedback.textContent='本次对话已达到轮次上限，请开始新对话。';
      if(!byId('home').classList.contains('hidden'))window.scrollTo({top:window.scrollY+answer.getBoundingClientRect().top-24,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
    }catch(error){if(run!==generation)return;feedback.textContent=error.name==='AbortError'?'等待已结束，没有收到完整回答；本次不会自动重试。':error.message;if(error.code==='session_expired'){session=null;feedback.textContent='此对话已过期或服务配置已变更。点击“新对话”后重新提问。';}if(error.code==='disabled'||error.code==='configuration'){initialized=false;await init();}if(submitted)question.value=text;}
    finally{clearTimeout(timeout);if(run===generation){busy=false;controller=null;controls();}}
  });
  fresh.addEventListener('click',reset);question.addEventListener('input',controls);
  question.addEventListener('keydown',event=>{if(event.key==='Enter'&&(event.ctrlKey||event.metaKey)&&!event.isComposing){event.preventDefault();form.requestSubmit();}});
  document.querySelectorAll('[data-ai-question]').forEach(button=>button.addEventListener('click',()=>{if(!enabled||busy)return;question.value=button.dataset.aiQuestion;controls();question.focus();}));
  document.addEventListener('pagechange',event=>{if(event.detail==='home')init();});
  setInterval(()=>{if(!busy&&!byId('home').classList.contains('hidden')){initialized=false;init();}},10000);
  if(location.hash==='#home')init();controls();
})();
