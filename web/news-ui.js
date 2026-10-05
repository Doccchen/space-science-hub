'use strict';
(() => {
  const page = document.getElementById('news');
  const toolbar = page.querySelector('.library-toolbar');
  const oldEmpty = page.querySelector('.news-empty');
  oldEmpty.remove();
  toolbar.lastElementChild.id = 'news-update';
  const filters = document.createElement('div'); filters.className = 'news-filters';
  filters.setAttribute('role','group'); filters.setAttribute('aria-label','按来源筛选');
  const status = document.createElement('p'); status.className = 'news-message'; status.setAttribute('role','status');
  const list = document.createElement('div'); list.className = 'real-news';
  const more = document.createElement('button'); more.className = 'secondary load-more'; more.textContent = '加载更多'; more.hidden = true;
  toolbar.after(filters, status, list, more);
  let source = '', cursor = null, generation = 0, busy = false;
  const buttons = [];
  function formatDate(date){return date ? new Date(date).toLocaleString('zh-CN',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}) : '未提供发布时间';}
  function safeLink(value){try{const url=new URL(value);return ['http:','https:'].includes(url.protocol)&&!url.username&&!url.password?url.href:null;}catch{return null;}}
  function renderItem(item){
    const row = document.createElement('article'); row.className='news-article';
    const meta = document.createElement('div'); meta.className='news-meta';
    meta.textContent=item.source_name+' · '+formatDate(item.published_at)+' · '+(item.lang==='en'?'英文原文':'原始语言');
    const heading=document.createElement('h2');const link=document.createElement('a');link.textContent=item.title;link.href=safeLink(item.original_url)||'#';link.target='_blank';link.rel='noopener noreferrer';heading.append(link);
    const summary=document.createElement('p');summary.textContent=item.summary||'来源未提供摘要，请查看原文。';
    const bottom=document.createElement('div');bottom.className='news-row-bottom';
    const badge=document.createElement('span');badge.textContent='官方来源 · 来源摘要节选';
    const action=document.createElement('button');action.className='link-button';action.textContent='查看新闻详情 →';action.addEventListener('click',()=>openDetail(item));
    bottom.append(badge,action);row.append(meta,heading,summary,bottom);return row;
  }
  const detail=document.createElement('dialog');detail.className='news-detail';document.body.append(detail);
  function openDetail(item){
    detail.replaceChildren();const top=document.createElement('div');top.className='dialog-heading';
    const label=document.createElement('h2');label.textContent='新闻详情';const close=document.createElement('button');close.textContent='×';close.setAttribute('aria-label','关闭新闻详情');close.addEventListener('click',()=>detail.close());top.append(label,close);
    const heading=document.createElement('h3');heading.textContent=item.title;
    const meta=document.createElement('p');meta.className='source-disclaimer';meta.textContent=item.source_name+' · '+formatDate(item.published_at);
    const summary=document.createElement('p');summary.textContent=item.summary||'来源未提供摘要。';
    const boundary=document.createElement('p');boundary.className='news-detail-boundary';boundary.textContent='此处只有来源摘要节选，不是完整报道。科普 Agent 尚未接入这篇新闻，页面中的科普内容仍为固定示例。';
    const link=document.createElement('a');link.textContent='阅读官方原文 ↗';link.href=safeLink(item.original_url)||'#';link.target='_blank';link.rel='noopener noreferrer';detail.append(top,heading,meta,summary,boundary,link);detail.showModal();
  }
  async function getJSON(path){const response=await fetch(path,{signal:AbortSignal.timeout(15000)});if(!response.ok)throw new Error('HTTP '+response.status);return response.json();}
  function renderSources(items){
    const relevant=source?items.filter(s=>s.id===source):items;
    const dates=relevant.map(s=>s.last_success_at).filter(Boolean).sort();
    const failures=relevant.filter(s=>s.last_error);
    document.getElementById('news-update').textContent=dates.length?'最近成功采集：'+formatDate(dates.at(-1))+(failures.length?' · '+failures.length+'个来源更新失败':''):'尚未成功采集';
    document.getElementById('news-update').title=relevant.map(s=>s.name+': '+(s.last_error?'本轮失败，保留历史内容；':'')+'最近成功 '+formatDate(s.last_success_at)).join('\n');
  }
  async function load(reset=false){
    if(busy&&!reset)return;
    const request=++generation;busy=true;more.disabled=true;
    if(reset){cursor=null;list.replaceChildren();}
    status.textContent='正在读取已入库的新闻…';
    const params=new URLSearchParams({limit:'20'});if(source)params.set('source',source);if(cursor)params.set('cursor',cursor);
    try{
      const [data,sources]=await Promise.all([getJSON('/api/news?'+params),getJSON('/api/news/sources')]);
      if(request!==generation)return;
      data.items.forEach(item=>list.append(renderItem(item)));cursor=data.next_cursor;
      more.hidden=!cursor;renderSources(sources.items);
      status.textContent=list.children.length?'':'尚无新闻。首次采集可能仍在进行，稍后点击刷新。';
    }catch(error){if(request!==generation)return;status.textContent='新闻暂时无法加载，已显示的内容仍可阅读。请点击刷新重试。';}
    finally{if(request===generation){busy=false;more.disabled=false;}}
  }
  [['','全部'],['nasa','NASA'],['esa','ESA']].forEach(([id,name])=>{
    const button=document.createElement('button');button.textContent=name;button.className=id===''?'active':'';button.setAttribute('aria-pressed',String(id===''));
    button.addEventListener('click',()=>{source=id;buttons.forEach(b=>{b.node.classList.toggle('active',b.id===id);b.node.setAttribute('aria-pressed',String(b.id===id));});load(true);});buttons.push({id,node:button});filters.append(button);
  });
  const refresh=document.createElement('button');refresh.textContent='刷新列表 ↻';refresh.className='refresh-news';refresh.addEventListener('click',()=>load(true));filters.append(refresh);
  more.addEventListener('click',()=>load(false));
  load(true);
})();
