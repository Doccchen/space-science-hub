'use strict';
(() => {
  const $ = id => document.getElementById(id), KEY = 'zhihang-research-preview-v1', WEEK = 7 * 86400000;
  const el = (tag, text, cls) => { const n = document.createElement(tag); if (text != null) n.textContent = text; if (cls) n.className = cls; return n; };
  const uid = () => crypto.randomUUID();
  let works = [], selected, available = false, sourceCount=4, wanfangEnabled = false, offlinePreview = false, serviceMessage = '正在检查知识库服务…', manageAction, opener;
  const pending = new Map();
  try { const saved = JSON.parse(localStorage.getItem(KEY)); works = (saved?.works || []).filter(w => w && typeof w.id === 'string' && typeof w.title === 'string' && Array.isArray(w.messages) && Date.now() - w.updated < WEEK); selected = works.some(w => w.id === saved.selected) ? saved.selected : works[0]?.id; } catch { /* A new browser or invalid saved preview starts empty. */ }
  let selectedByMode = {};
  try { selectedByMode = JSON.parse(localStorage.getItem(KEY))?.selectedByMode || {}; } catch { /* No saved mode selection. */ }
  // Older versions put both modes in one transcript. Split by response type,
  // keeping the original id/draft on its last active mode and the knowledge session.
  works = works.flatMap(work => {
    const groups = {papers:[],knowledge:[]}; let mode = work.mode || 'papers';
    for (let i=0;i<work.messages.length;i++) {
      const msg=work.messages[i];
      if(msg.role==='user') {
        const next=work.messages.slice(i+1).find(item=>item.role==='user'||['answer','topics','papers'].includes(item.type));
        mode=msg.text?.startsWith('查找论文：')?'papers':next?.role!=='user'&&next?(next.type==='answer'?'knowledge':'papers'):(work.mode||'papers');
      } else if(['answer','topics','papers'].includes(msg.type))mode=msg.type==='answer'?'knowledge':'papers';
      groups[mode].push(msg);
    }
    return ['papers','knowledge'].filter(mode=>mode===work.mode||groups[mode].length).map(mode=>({...work,
      id:mode===work.mode?work.id:uid(),mode,messages:groups[mode],
      draft:mode===work.mode?work.draft:'',scroll:mode===work.mode?work.scroll:0,
      session:mode==='knowledge'?work.session:null}));
  });
  const current = () => works.find(w => w.id === selected);
  function save() { try { const stored=works.map(work=>({...work,messages:work.messages.map(msg=>msg.type==='papers'?{...msg,papers:(msg.papers||[]).filter(p=>!p.sources?.includes('ScienceDirect')),source_results:msg.source_results?.map(group=>group.source==='ScienceDirect'?{source:group.source,state:'transient',papers:[],count:0,message:'该来源结果不保存在浏览器，请重新检索。'}:group),transient_missing:msg.transient_missing||(msg.papers||[]).some(p=>p.sources?.includes('ScienceDirect'))}:msg)}));localStorage.setItem(KEY, JSON.stringify({selected, selectedByMode, works:stored})); } catch { $('storage-note').textContent = '浏览器存储不可用或已满，最新记录未保存。'; } }
  function create(mode = current()?.mode || 'papers') {
    if (works.filter(work=>work.mode===mode).length >= 20) { $('activity').textContent = '当前模式最多保留 20 项研究，请先删除不再需要的记录。'; return; }
    const work = {id: uid(), title: '新的研究', mode, draft: '', messages: [], updated: Date.now(), session: null};
    works.unshift(work); selected = work.id; selectedByMode[mode] = selected; save(); render(); closeSidebar(); return work;
  }
  function update(work) { work.updated = Date.now(); save(); renderList(); if (work.id === selected) renderThread(); }
  function renderList() {
    $('work-list').replaceChildren();
    for (const work of works.filter(work=>work.mode===current().mode).sort((a,b) => b.updated - a.updated)) {
      const row = el('div', null, 'work-row'), button = el('button'); button.type = 'button'; button.setAttribute('aria-current', String(work.id === selected));
      button.append(el('strong', work.title), el('small', pending.has(work.id) ? '正在处理…' : work.demo ? '交互示例 · 演示内容' : new Date(work.updated).toLocaleDateString('zh-CN', {month:'numeric',day:'numeric'}) + ' · ' + (work.mode === 'papers' ? '论文查找' : '知识问答')));
      button.onclick = () => { selected = work.id; selectedByMode[work.mode] = selected; save(); render(); closeSidebar(); }; row.append(button); $('work-list').append(row);
    }
  }
  function setMode(mode) {
    const w=current(); if(w.mode===mode)return;
    w.draft=$('question').value;w.scroll=$('conversation').scrollTop;selectedByMode[w.mode]=w.id;
    const target=works.find(item=>item.id===selectedByMode[mode]&&item.mode===mode)||works.find(item=>item.mode===mode);
    if(target){selected=target.id;selectedByMode[mode]=selected;save();render();}else create(mode);
    $('question').focus();
  }
  function renderComposer() {
    const w = current(), isPaper = w.mode === 'papers', busy = pending.has(w.id);
    document.querySelector('.workspace').dataset.empty = String(!w.messages.length);
    $('welcome-title').textContent = isPaper ? '我们要研究什么？' : '今天，想了解什么？';
    document.querySelectorAll('.mode-switch [data-mode]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.mode === w.mode)));
    $('question').value = w.draft || ''; $('question').maxLength = isPaper ? 6000 : 1500;
    $('question').placeholder = isPaper ? '输入技术名称，或粘贴一段航天新闻…' : '向本站航天知识库提问…';
    $('question').disabled = busy;
    $('scope').textContent = isPaper ? (wanfangEnabled ? '中英文论文检索' : sourceCount+'源论文检索') : '航天知识库';
    $('input-note').textContent = isPaper ? '先识别主题，确认检索词后查找论文' : '独立知识库回答，不自动读取检索到的论文';
    $('service-note').textContent = w.demo ? '当前为交互示例，内容仅用于展示布局。' : isPaper ? '识别内容可能发送至模型；检索词将发送至论文来源。' : available ? '知识库会话有有效期与轮次限制，来源可展开查看。' : serviceMessage;
    if(offlinePreview && !w.demo)$('service-note').textContent = '离线交互预览 · 输入仅用于本机演示，不调用模型。';
    $('send').disabled = busy || !w.draft?.trim() || (!isPaper && !available);
    $('cancel').hidden = !busy; $('activity').textContent = pending.get(w.id)?.label || '';
    $('conversation').setAttribute('aria-busy', String(busy));
  }
  function render() { const w = current(); $('work-title').textContent = w.title; $('work-type').textContent = w.demo ? '交互示例' : '论文与知识'; renderList(); renderThread(); $('conversation').scrollTop = w.scroll || 0; }
  function renderThread() {
    const w = current(); $('welcome').hidden = w.messages.length > 0; $('messages').replaceChildren();
    for (const msg of w.messages) {
      const box = el('section', null, 'message ' + (msg.role === 'user' ? 'user' : msg.type === 'error' ? 'error' : 'assistant'));
      if (msg.role === 'user') box.textContent = msg.text;
      else {
        const heading = el('div', null, 'message-heading'), mark = el('img'); mark.src = '/assets/brand.svg'; mark.alt = '';
        heading.append(mark, el('span', msg.type === 'topics' ? '检索主题' : msg.type === 'papers' ? '论文检索' : msg.type === 'error' ? '本次请求未完成' : '知识库回答')); box.append(heading);
        if (msg.type === 'topics') renderTopics(box, msg, w);
        else if (msg.type === 'papers') renderPapers(box, msg, w);
        else {
          if (msg.type === 'answer') {
            const answer = window.ArticleRenderer.markdown(msg.text);
            answer.classList.add('research-answer'); box.append(answer);
          } else box.append(el('p', msg.text));
          if (msg.sources?.length) { const details = el('details', null, 'sources'); details.append(el('summary', '本次检索资料 · ' + msg.sources.length + ' 项')); for (const s of msg.sources) details.append(el('p', s.name + (s.positions?.length ? ' · 返回位置：' + s.positions.join('、') : ''))); if(msg.notice)details.append(el('p', msg.notice)); box.append(details); }
          if (msg.remaining != null) box.append(el('p', msg.remaining === 0 ? '本次已达到轮次上限，下次提问将开始新的知识库上下文。' : '本次知识库对话还可追问 ' + msg.remaining + ' 轮。', 'muted'));
        }
      }
      $('messages').append(box);
    }
    renderComposer();
  }
  function scrollEnd() { $('conversation').scrollTop = $('conversation').scrollHeight; }
  function link(text, url) {
    try { const parsed = new URL(url); if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password) return null; const a = el('a', text); a.href = parsed.href; a.target = '_blank'; a.rel = 'noopener noreferrer'; return a; } catch { return null; }
  }
  function renderTopics(box, msg, work) {
    box.append(el('p', '选择一个技术主题，确认或修改检索词。'));
    const choices = el('div', null, 'topic-options'), form = el('form', null, 'query-form'), input = el('input');
    input.value = msg.query || ''; input.required = true; input.minLength = 2; input.maxLength = 160; input.setAttribute('aria-label', '论文检索词');
    const zh = el('input'); zh.value=msg.query_zh || msg.topics?.[0]?.query_zh || msg.topics?.[0]?.name || ''; zh.maxLength=160;zh.setAttribute('aria-label','万方中文检索词');
    zh.oninput=()=>{msg.query_zh=zh.value;save();};
    for (const topic of msg.topics || []) { const b = el('button', topic.name); b.type = 'button'; b.setAttribute('aria-pressed', String(input.value === topic.query)); b.onclick = () => { input.value = topic.query; msg.query = topic.query; zh.value=topic.query_zh || topic.name;msg.query_zh=zh.value;choices.querySelectorAll('button').forEach(n => n.setAttribute('aria-pressed', String(n === b))); save(); }; choices.append(b); }
    input.oninput = () => { msg.query = input.value; save(); }; const submit = el('button', '查找论文', 'primary'); submit.disabled = pending.has(work.id); form.append(input, submit);
    if(wanfangEnabled){const label=el('label','万方中文检索词（可修改）','query-zh');label.append(zh);form.append(label);}
    msg.wanfang_options ||= wfDefaults();
    if(wanfangEnabled){const options=wfControls(msg.wanfang_options,()=>save());form.append(options);}
    form.onsubmit = event => { event.preventDefault(); search(work,input.value.trim(),zh.value.trim(),{...msg.wanfang_options,page:1}); };
    box.append(choices, form, el('p', msg.notice || '检索词可以直接修改；确认后再访问论文来源。', 'muted'));
  }
  const wfDefaults = () => ({field:'topic',library:'papers',sort:'relevance',page:1,page_size:20,year_from:null,year_to:null});
  function wfControls(options, onChange) {
    const controls=el('div',null,'wf-controls');
    for(const [key,label,choices] of [
      ['field','检索字段',[['topic','主题（题名 / 关键词 / 摘要）'],['title','题名'],['all','全部字段']]],
      ['library','文献范围',[['papers','全部论文'],['periodical','期刊论文'],['thesis','学位论文'],['conference','会议论文'],['patent','专利'],['all','综合（含专利）']]],
      ['sort','排序',[['relevance','来源相关度'],['date','发表时间从新到旧']]],
      ['page_size','每页',[['10','10 条'],['20','20 条'],['50','50 条']]]
    ]) {const l=el('label',label), select=el('select');select.setAttribute('aria-label',label);for(const [value,text] of choices)select.append(new Option(text,value));select.value=String(options[key]);select.onchange=()=>{options[key]=key==='page_size'?Number(select.value):select.value;options.page=1;onChange?.();};l.append(select);controls.append(l);}
    const years=el('div',null,'wf-years');
    for(const [key,label] of [['year_from','开始年份'],['year_to','结束年份']]){const l=el('label',label),input=el('input');input.type='number';input.min=1900;input.max=2100;input.placeholder='不限';input.value=options[key]||'';input.setAttribute('aria-label',label);input.oninput=()=>{options[key]=input.value?Number(input.value):null;options.page=1;onChange?.();};l.append(input);years.append(l);}
    controls.append(years);return controls;
  }
  function sourceGroups(msg) {
    if(msg.source_results?.length)return msg.source_results;
    return (msg.sources||[]).map(status=>({...status,papers:(msg.papers||[]).filter(p=>p.sources?.includes(status.source)),total:null,pagination_supported:false,order:'legacy'}));
  }
  function combineGroups(groups) {
    const rows=[],norm=s=>(s||'').toLowerCase().replace(/[^\p{L}\p{N}]/gu,'');
    for(const group of groups)for(const p of group.papers||[]){const old=rows.find(r=>(r.doi&&p.doi&&r.doi.toLowerCase()===p.doi.toLowerCase())||(norm(r.title)===norm(p.title)&&!(r.doi&&p.doi&&r.doi.toLowerCase()!==p.doi.toLowerCase())));if(old){old.sources=[...new Set([...old.sources,...p.sources])];}else rows.push({...p,sources:[...p.sources]});}
    return rows;
  }
  async function changeSource(work,msg,name,options) {
    if(pending.has(work.id))return;
    if(options?.year_from&&options?.year_to&&options.year_from>options.year_to){msg.request_error='开始年份不能晚于结束年份。';renderThread();return;}
    const requested=options?{...options}:undefined;msg.request_error='';
    await run(work,'正在更新 '+name+' 的检索结果…',async signal=>{
      const result=await api('/api/reader/search',{query:msg.query,query_zh:msg.query_zh||'',source:name,wanfang:requested},signal);
      const group=result.source_results?.find(g=>g.source===name);
      if(!group)throw new Error('来源未返回有效的分组结果。');
      if(group.state!=='ok'){msg.request_error=(group.message||'本次来源请求失败')+'；原结果已保留。';msg.retry_options=requested;msg.retry_source=name;return;}
      msg.source_results=sourceGroups(msg).map(g=>g.source===name?group:g);
      msg.sources=msg.source_results.map(({papers,...meta})=>meta);msg.papers=combineGroups(msg.source_results);
      msg.selected_source=name;msg.shown=10;msg.filters={year:'',kind:'',oa:false};msg.request_error='';msg.retry_options=null;
    });
    if(work.id===selected){const panel=document.getElementById(msg.panel_id);if(panel){const viewport=$('conversation');viewport.scrollTop+=panel.getBoundingClientRect().top-viewport.getBoundingClientRect().top-12;}}
  }
  function renderPapers(box, msg, work) {
    msg.panel_id ||= 'paper-results-'+uid();const surface=el('div',null,'source-surface');surface.id=msg.panel_id;box.append(surface);
    const draw=()=>{
      surface.replaceChildren();const groups=sourceGroups(msg),all=combineGroups(groups);
      if(msg.preview)surface.append(el('p','本地交互样本 · 以下题录及命中数量均为演示，不是真实检索结果。','preview-notice'));
      if(msg.selected_source!=='all'&&!groups.some(g=>g.source===msg.selected_source))msg.selected_source=groups.some(g=>g.source==='万方'&&g.state==='ok')?'万方':'all';
      const chosen=groups.find(g=>g.source===msg.selected_source),busy=pending.has(work.id),tabs=el('div',null,'source-tabs');tabs.setAttribute('role','group');tabs.setAttribute('aria-label','论文来源');
      const ordered=[...groups].sort((a,b)=>['万方','Crossref','Semantic Scholar','arXiv','NASA NTRS','ScienceDirect'].indexOf(a.source)-['万方','Crossref','Semantic Scholar','arXiv','NASA NTRS','ScienceDirect'].indexOf(b.source));
      for(const [name,caption] of [['all','全部来源'],...ordered.map(g=>[g.source,g.source])]){const group=groups.find(g=>g.source===name),b=el('button');b.type='button';b.dataset.source=name;b.setAttribute('aria-pressed',String(msg.selected_source===name));b.append(el('span',caption),el('small',name==='all'?'已加载 '+all.length:group.state==='ok'?(group.total!=null?'共 '+Number(group.total).toLocaleString():'已取回 '+group.count):group.state==='transient'?'需重新检索':'暂不可用'));b.onclick=()=>{msg.selected_source=name;msg.shown=10;msg.filters={year:'',kind:'',oa:false};save();draw();[...surface.querySelectorAll('.source-tabs button')].find(n=>n.dataset.source===name)?.focus({preventScroll:true});};tabs.append(b);}
      surface.append(tabs);
      if(msg.request_error){const error=el('div',null,'source-error');error.setAttribute('role','status');error.append(el('p',msg.request_error));const retry=el('button','重试本次请求','text-button');retry.disabled=busy;retry.onclick=()=>changeSource(work,msg,msg.retry_source||msg.selected_source,msg.retry_options);error.append(retry);surface.append(error);}
      const head=el('div',null,'source-heading'),description=el('div');description.append(el('h3',chosen?chosen.source+' 文献':'全部来源'));
      description.append(el('p',chosen?'本来源检索词：'+(chosen.query|| (chosen.source==='万方'?msg.query_zh||msg.query:msg.query)):'合并各来源当前已加载的记录，按 DOI 和题名去重。','muted'));
      head.append(description);if(chosen?.source==='万方'){const q=msg.query_zh||msg.query,prefix=chosen.options?.field==='title'?'题名:':chosen.options?.field==='all'?'':'主题:';const a=link('到万方官网对照 ↗','https://s.wanfangdata.com.cn/paper?'+new URLSearchParams({q:prefix+q}));if(a)head.append(a);}surface.append(head);
      if(chosen&&chosen.state!=='ok'){
        surface.append(el('p',chosen.message||(chosen.state==='transient'?'此来源结果不保存在浏览器，请重新检索。':'该来源暂不可用，其他来源仍可查看。'),'source-error'));
        const retry=el('button','重新检索该来源','primary');retry.disabled=busy;retry.onclick=()=>changeSource(work,msg,chosen.source,chosen.source==='万方'?wfDefaults():undefined);surface.append(retry);return;
      }
      if(chosen?.source==='万方'&&chosen.pagination_supported){
        const page=chosen.page||1,size=chosen.page_size||20,total=chosen.total,summary=el('p',total!=null?'万方命中 '+Number(total).toLocaleString()+' 条 · 本页返回 '+chosen.count+' 条 · 第 '+page+' / '+Math.max(1,Math.ceil(total/size))+' 页':'总命中数未返回 · 本页返回 '+chosen.count+' 条 · 第 '+page+' 页','source-summary');surface.append(summary);
        const options={...wfDefaults(),...chosen.options,page,page_size:size},form=el('form',null,'wf-refine');form.append(wfControls(options));
        const foot=el('div',null,'wf-refine-footer'),note=el('p','按所选字段与范围查询，保留万方 API 返回顺序；主题范围为题名、关键词、摘要，排序可能与官网不同。','muted'),submit=el('button','按此条件检索','primary');submit.disabled=busy;foot.append(note,submit);form.append(foot);form.onsubmit=e=>{e.preventDefault();options.page=1;changeSource(work,msg,'万方',options);};const settings=el('details',null,'wf-settings');const labels={topic:'主题',title:'题名',all:'全部字段',papers:'全部论文',periodical:'期刊论文',thesis:'学位论文',conference:'会议论文',patent:'专利',relevance:'来源相关度',date:'发表时间'};settings.open=Boolean(msg.wf_details_open);settings.append(el('summary','调整检索条件 · '+(chosen.options?labels[options.field]+' / '+(options.library==='all'?'综合（含专利）':labels[options.library])+' / '+labels[options.sort]:'普通关键词 / 期刊 / 来源默认')+' / '+size+' 条每页'),form);settings.ontoggle=()=>{msg.wf_details_open=settings.open;save();};surface.append(settings);
      } else surface.append(el('p',chosen?'本来源当前取回 '+chosen.count+' 条'+(chosen.cached?'（缓存）':'')+(chosen.order==='legacy'?'，历史记录已重排，重新检索可保留来源顺序。':'，保留返回顺序；暂未获取总量和后续页。'):'当前已加载 '+all.length+' 条去重记录；此数量不是所有数据库的总命中数。','source-summary'));
      const base=chosen?.papers||all,filters=el('div',null,'filters'),year=el('select'),kind=el('select'),oa=el('input');
      year.setAttribute('aria-label','已加载记录的年份');kind.setAttribute('aria-label','已加载记录的类型');
      year.append(new Option('全部年份',''),...[...new Set(base.map(p=>p.year).filter(Boolean))].sort((a,b)=>b-a).map(y=>new Option(String(y),String(y))));
      kind.append(...['全部类型','期刊论文','学位论文','会议论文','专利','预印本','技术报告','其他文献'].map((v,i)=>new Option(v,i?v:'')));
      msg.filters ||= {year:'',kind:'',oa:false};year.value=msg.filters.year;kind.value=msg.filters.kind;oa.type='checkbox';oa.checked=msg.filters.oa;
      for(const [text,control] of [['本页年份',year],['本页类型',kind],['公开全文',oa]]){const label=el('label',text);label.append(control);filters.append(label);}surface.append(filters);
      const rows=base.filter(p=>(!year.value||String(p.year)===year.value)&&(!kind.value||p.type===kind.value)&&(!oa.checked||p.fulltext)),list=el('div',null,'source-paper-list'),shown=chosen?.source==='万方'&&chosen.pagination_supported?rows.length:msg.shown||10;
      for(const [index,p] of rows.slice(0,shown).entries()){
        const row=el('article',null,'paper'),title=el('h3'),open=el('button',p.title);open.type='button';open.onclick=()=>openPaper(p,open);title.append(open);
        row.append(el('p',(chosen&&p.source_rank?'来源序号 '+p.source_rank+' · ':'')+[p.year,p.type,p.sources.join(' / ')].filter(Boolean).join(' · '),'meta'),title,el('p',[(p.authors||[]).slice(0,3).join('、'),p.venue].filter(Boolean).join(' · '),'authors'));
        if(p.abstract)row.append(el('p',p.abstract.slice(0,180)+(p.abstract.length>180?'…':''),'paper-excerpt'));
        const actions=el('div',null,'paper-actions'),detail=el('button','摘要与详情');detail.type='button';detail.onclick=()=>openPaper(p,detail);actions.append(detail);const original=link('原始页面 ↗',p.url);if(original)actions.append(original);row.append(actions);list.append(row);
      }
      if(!rows.length)list.append(el('p',base.length?'当前页筛选后没有记录，请放宽本页筛选。':'本次未取得文献，请修改检索词或文献范围。','muted'));surface.append(list);
      for(const control of [year,kind,oa])control.onchange=()=>{msg.filters={year:year.value,kind:kind.value,oa:oa.checked};msg.shown=10;save();draw();};
      if(rows.length>shown){const more=el('button','展开本页剩余 '+(rows.length-shown)+' 条','text-button');more.onclick=()=>{msg.shown=shown+10;save();draw();};surface.append(more);}
      if(chosen?.source==='万方'&&chosen.pagination_supported){
        const options={...wfDefaults(),...chosen.options},page=chosen.page||1,pager=el('form',null,'source-pagination');
        const prev=el('button','上一页'),next=el('button','下一页'),jump=el('input'),go=el('button','跳转');prev.type=next.type='button';prev.disabled=busy||page<=1;next.disabled=busy||!chosen.has_more||page>=1000;
        prev.onclick=()=>changeSource(work,msg,'万方',{...options,page:page-1,page_size:chosen.page_size});next.onclick=()=>changeSource(work,msg,'万方',{...options,page:page+1,page_size:chosen.page_size});
        jump.type='number';jump.min=1;jump.max=chosen.total!=null?Math.min(1000,Math.max(1,Math.ceil(chosen.total/chosen.page_size))):1000;jump.value=page;jump.required=true;jump.setAttribute('aria-label','万方页码');go.disabled=busy;
        const label=el('label','第');label.append(jump,document.createTextNode('页'));pager.append(prev,label,go,next);pager.onsubmit=e=>{e.preventDefault();changeSource(work,msg,'万方',{...options,page:Number(jump.value),page_size:chosen.page_size});};surface.append(pager);
      }
      surface.append(el('p','题录与摘要来自所标注来源；检索结果尚未经过全文阅读。'+(msg.preview?' 当前为离线交互样本，数量和题名均用于演示。':''),'muted'));
    };draw();
  }
  function openPaper(paper, button) {
    opener = button; const detail = $('paper-detail'); detail.replaceChildren(el('p', (paper.type || '文献信息') + ' · ' + (paper.year || '年份未提供'), 'muted'));
    const title = el('h2', paper.title); title.id = 'paper-title'; detail.append(title, el('p', (paper.authors || []).join('、') || '作者信息未提供', 'muted'));
    if(paper.doi) detail.append(el('p', 'DOI：' + paper.doi, 'muted'));
    detail.append(el('h3', '来源摘要'), el('p', paper.abstract || '来源未提供摘要，请前往原始页面查看。'));
    if(paper.reason) detail.append(el('p', paper.reason, 'muted'));
    for(const [text,url] of [['查看原始页面 ↗',paper.url],['公开全文入口 ↗',paper.fulltext]]) { const a = link(text,url); if(a)detail.append(a); }
    $('paper-dialog').showModal();
  }
  async function api(path, body, signal) {
    const response = await fetch(path, {method:body ? 'POST':'GET',credentials:'same-origin',cache:'no-store',headers:body ? {'Content-Type':'application/json'}:undefined,body:body ? JSON.stringify(body):undefined,signal});
    const data = await response.json(); if (!response.ok) { const error = new Error(data.error?.message || (typeof data.detail === 'string' ? data.detail : '服务暂不可用，请稍后重试。')); error.code = data.error?.code; throw error; } return data;
  }
  async function run(work, label, operation) {
    if (pending.has(work.id)) return;
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 135000); pending.set(work.id, {controller,label}); save(); renderList(); if(work.id === selected) renderThread();
    try { await operation(controller.signal); }
    catch (error) { if(works.includes(work)){ if(error.code === 'session_expired' || error.code === 'history_limit') work.session = null; work.messages.push({type:'error',text:error.name === 'AbortError' ? '已停止等待，尚未收到完整结果。记录已保留；停止等待不会撤销已经发送的服务请求。' : error.message + (error.code === 'session_expired' || error.code === 'history_limit' ? ' 下次提问将开始新的知识库上下文。' : '')}); } }
    finally { clearTimeout(timer); pending.delete(work.id); if(works.includes(work)){ update(work); if(work.id === selected)scrollEnd(); } }
  }
  function nameWork(work,text) { if(work.title === '新的研究')work.title = text.replace(/\s+/g,' ').slice(0,22); }
  async function search(work, query, query_zh='',wanfang_options=wfDefaults()) {
    if(query.length < 2 || query.length > 160 || pending.has(work.id)) return;
    if(work.demo) { work.messages.push({type:'error',text:'交互示例不会调用真实检索。请新建研究后查找论文。'}); update(work); scrollEnd(); return; }
    work.messages.push({role:'user',text:'查找论文：' + query}); nameWork(work,query);
    let created;
    await run(work,'正在检索论文来源，可切换到其他研究…',async signal => { const result = await api('/api/reader/search',{query,query_zh,wanfang:wanfang_options},signal); if(works.includes(work)){created={type:'papers',...result};work.messages.push(created);} });
    if(created&&work.id===selected){const panel=document.getElementById(created.panel_id);if(panel){const viewport=$('conversation');viewport.scrollTop+=panel.getBoundingClientRect().top-viewport.getBoundingClientRect().top-12;}}

  }
  $('composer').onsubmit = async event => {
    event.preventDefault(); const work = current(), text = $('question').value.trim(); if(!text || pending.has(work.id))return;
    if(work.demo) { $('activity').textContent = '当前为交互示例，请新建研究后提交真实问题。'; return; }
    if(work.mode === 'knowledge' && !available) { $('activity').textContent = serviceMessage; return; }
    if(text.length > (work.mode === 'papers' ? 6000 : 1500)){ $('activity').textContent = '内容超过当前模式的长度限制，请精简后发送。'; return; }
    nameWork(work,text); work.messages.push({role:'user',text}); work.draft = '';
    if(work.mode === 'papers') await run(work,'正在识别技术主题…',async signal => {
      let result;
      try { result = await api('/api/reader/analyze',{text},signal); }
      catch(error) { if(error.name === 'AbortError')throw error; result = {topics:[],notice:'主题识别未完成，可修改下方检索词直接查找。'}; }
      if(works.includes(work))work.messages.push({type:'topics',topics:result.topics || [],query:result.topics?.[0]?.query || text.slice(0,160),query_zh:result.topics?.[0]?.query_zh || text.slice(0,160),notice:result.notice});
    });
    else await run(work,'正在检索知识库并整理回答…',async signal => {
      if(!work.session){ const data = await api('/api/ai/conversations',{},signal); work.session = data.conversation_id; }
      const result = await api('/api/ai/ask',{conversation_id:work.session,request_id:uid(),question:text},signal);
      if(works.includes(work)){work.messages.push({type:'answer',text:result.answer,sources:result.sources,notice:result.notice,remaining:result.remaining_rounds}); if(result.remaining_rounds === 0)work.session = null;}
    });
  };
  $('question').oninput = () => { const w = current(); w.draft = $('question').value; save(); $('send').disabled = !w.draft.trim() || pending.has(w.id) || (w.mode === 'knowledge' && !available); };
  let scrollTimer;
  $('conversation').addEventListener('scroll',()=>{current().scroll=$('conversation').scrollTop;clearTimeout(scrollTimer);scrollTimer=setTimeout(save,200);});
  $('question').onkeydown = event => { if(event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !event.isComposing){ event.preventDefault(); $('composer').requestSubmit(); } };
  document.querySelectorAll('.mode-switch button').forEach(b => b.onclick = () => setMode(b.dataset.mode));

  $('cancel').onclick = () => pending.get(selected)?.controller.abort(); $('new-work').onclick = () => {if(create())$('question').focus();};
  $('quick-new').onclick = $('new-work').onclick;
  function closeSidebar() { $('sidebar').classList.remove('open'); $('sidebar-shade').hidden = true; $('open-sidebar').setAttribute('aria-expanded','false'); $('sidebar').removeAttribute('role'); $('sidebar').removeAttribute('aria-modal'); }
  $('open-sidebar').onclick = () => { $('sidebar').classList.add('open'); $('sidebar-shade').hidden = false; $('open-sidebar').setAttribute('aria-expanded','true'); $('sidebar').setAttribute('role','dialog'); $('sidebar').setAttribute('aria-modal','true'); $('close-sidebar').focus(); };
  $('close-sidebar').onclick = () => { closeSidebar(); $('open-sidebar').focus(); }; $('sidebar-shade').onclick = $('close-sidebar').onclick;
  document.addEventListener('keydown', event => { if(!$('sidebar').classList.contains('open'))return; if(event.key === 'Escape'){ $('close-sidebar').click(); } if(event.key === 'Tab'){const nodes = [...$('sidebar').querySelectorAll('button')],first = nodes[0],last = nodes.at(-1); if(event.shiftKey && document.activeElement === first){event.preventDefault();last.focus();} else if(!event.shiftKey && document.activeElement === last){event.preventDefault();first.focus();}} });
  $('close-paper').onclick = () => $('paper-dialog').close(); $('paper-dialog').addEventListener('close',()=>opener?.isConnected && opener.focus());
  function manage(action) { manageAction = action; $('manage-title').textContent = action === 'rename' ? '重命名研究' : '删除这项研究？'; $('manage-copy').textContent = action === 'rename' ? '研究名称' : '将删除此浏览器中的记录与草稿，此操作无法撤销。'; $('name-input').hidden = action !== 'rename'; $('name-input').required = action === 'rename'; $('name-input').value = current().title; $('manage-confirm').textContent = action === 'rename' ? '保存' : '删除研究'; $('manage-dialog').showModal(); if(action === 'rename')$('name-input').select();else $('manage-cancel').focus(); }
  $('rename-work').onclick = () => manage('rename'); $('delete-work').onclick = () => manage('delete'); $('manage-cancel').onclick = () => $('manage-dialog').close();
  const recordActions=el('div',null,'record-actions');
  for(const [text,action] of [['重命名当前研究','rename'],['删除当前研究','delete']]){const button=el('button',text,'text-button');button.onclick=()=>{closeSidebar();manage(action);};recordActions.append(button);}
  $('sidebar').insertBefore(recordActions,document.querySelector('.side-bottom'));
  $('manage-form').onsubmit = event => { event.preventDefault(); const w = current(); if(manageAction === 'rename'){const name = $('name-input').value.trim();if(!name)return;w.title=name;} else {pending.get(w.id)?.controller.abort();works = works.filter(x=>x.id!==w.id);selected=works[0]?.id; if(w.session)fetch('/api/ai/conversations/'+encodeURIComponent(w.session),{method:'DELETE',credentials:'same-origin'}).catch(()=>{}); } $('manage-dialog').close(); if(!works.length)create();else{save();render();} };
  if(!works.length)create();else render();
  const params = new URLSearchParams(location.search); if(params.get('mode') === 'knowledge'){setMode('knowledge');}
  async function boot() {
    try {const config=await api('/api/reader/config',null,AbortSignal.timeout(10000));wanfangEnabled=Boolean(config.wanfang_enabled);sourceCount=Number(config.source_count)||4;renderThread();}catch{/* Existing four-source search stays available. */}
    try { const status = await api('/api/ai/status',null,AbortSignal.timeout(10000)); available = Boolean(status.enabled); serviceMessage = status.message || '知识库服务暂未开放。'; offlinePreview = Boolean(status.preview || /离线/.test(serviceMessage)); if(offlinePreview)$('storage-note').nextElementSibling.textContent = '离线交互预览 · 未连接模型'; }
    catch { serviceMessage = '知识库服务暂不可用，仍可使用论文查找。'; }
    if(!pending.has(selected))renderComposer();
    const news = params.get('news'); if(!news || !/^[1-9]\d*$/.test(news))return;
    const work=create('papers'); if(!work)return;
    await run(work,'正在带入新闻内容…',async signal => { const detail = await api('/api/news/'+news,null,signal); let body=''; try{const content=await api('/api/news/'+news+'/content',null,signal);body=(content.blocks||[]).map(b=>b.text||(b.items||[]).join(' ')).join('\n');}catch(error){if(error.name==='AbortError')throw error;} work.draft=[detail.title,body].filter(Boolean).join('\n\n').slice(0,6000);work.title=detail.title.slice(0,22); });
  }
  boot();
})();
