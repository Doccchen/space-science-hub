'use strict';
(() => {
  const $ = id => document.getElementById(id), make = (tag, text) => { const node = document.createElement(tag); if (text) node.textContent = text; return node; };
  let csrf = '', storage = {enabled:false}, page = 1, articleId = null, current = null, generation = 0, editing = false;
  const message = text => { $('message').textContent = text; };
  async function api(path, data) {
    const response = await fetch(path, {method:data === undefined ? 'GET':'POST', credentials:'same-origin', cache:'no-store',
      headers:data === undefined ? {} : {'Content-Type':'application/json','X-CSRF-Token':csrf}, body:data === undefined ? undefined : JSON.stringify(data), signal:AbortSignal.timeout(20000)});
    const value = await response.json();
    if (!response.ok) { if (response.status === 401) loggedOut(); throw new Error(value.detail || '请求失败'); }
    return value;
  }
  function loggedOut() { csrf=''; articleId=null; generation++; $('workspace').hidden=true; $('login').hidden=false; $('logout').hidden=true; $('account').textContent=''; $('password').value=''; }
  async function loggedIn() { const session=await api('/api/session'); csrf=session.csrf; storage=session.storage; $('account').textContent=session.username; $('logout').hidden=false; $('login').hidden=true; $('workspace').hidden=false; await list(); }
  async function act(button, fn) { button.disabled=true; try { await fn(); } catch(error) { message(error.message); } finally { button.disabled=false; } }
  $('login-form').addEventListener('submit', event => { event.preventDefault(); act(event.submitter, async()=>{const password=$('password').value; $('password').value=''; const result=await api('/api/login',{username:$('username').value,password}); csrf=result.csrf; await loggedIn(); message('登录成功。');}); });
  $('logout').addEventListener('click', ()=>act($('logout'),async()=>{await api('/api/logout',{}); loggedOut();}));
  async function list() {
    const request=++generation; const data=await api('/api/articles?page='+page+'&q='+encodeURIComponent($('search').value)); if(request!==generation)return;
    $('queue').hidden=false; $('editor').hidden=true; $('articles').replaceChildren();
    for(const item of data.items) { const row=make('div'); row.className='article'; const button=make('button','审核这篇新闻'); button.addEventListener('click',()=>act(button,()=>open(item.id)));
      row.append(make('h2',item.title),make('p',item.source_name+' · '+(item.withdrawn?'正文已撤回':item.version?'有发布版本':item.draft_revision?'有待审核草稿':'未准备正文')),button); $('articles').append(row); }
    $('page').textContent='第 '+page+' 页'; $('previous').disabled=page===1; $('next').disabled=!data.more;
  }
  $('search-form').addEventListener('submit',event=>{event.preventDefault();page=1;act(event.submitter,list);});
  $('previous').addEventListener('click',()=>{page--;act($('previous'),list);}); $('next').addEventListener('click',()=>{page++;act($('next'),list);});
  $('back').addEventListener('click',()=>{articleId=null;editing=false;act($('back'),list);});
  function drawJobs(data) {
    $('jobs').replaceChildren(); for(const job of data.jobs){const row=make('p',({capture:'正文抓取',image:'图片抓取保存'}[job.kind]||job.kind)+' · '+({queued:'排队',running:'处理中',done:'完成',failed:'失败'}[job.state]||job.state));row.className='job';if(job.result){try { const value=JSON.parse(job.result); if(value.error)row.append(make('span',' · '+value.error)); }catch{}}$('jobs').append(row);}
  }
  function input(label, text, multiline=false) { const wrapper=make('label',label), field=make(multiline?'textarea':'input');field.value=text||'';field.maxLength=4000;wrapper.append(field); return {wrapper,field}; }
  function drawBlock(block) { const row=make('div'), top=make('div'), area=make('textarea'), remove=make('button','删除本块'); row.className='block';top.className='block-header';top.append(make('span',({paragraph:'段落',heading:'小标题',list:'列表（每行一项）',table:'表格（单元格以Tab分隔）'}[block.type]||block.type)),remove);
    row.dataset.type=block.type;row.dataset.level=block.level||2;row.dataset.ordered=String(Boolean(block.ordered));area.maxLength=24000;area.value=block.type==='list'?block.items.join('\n'):block.type==='table'?block.rows.map(r=>r.join('\t')).join('\n'):block.text;row.append(top,area);remove.addEventListener('click',()=>{row.remove();editing=true;});area.addEventListener('input',()=>{editing=true;});$('blocks').append(row);
  }
  function documentValue() {
    const document=structuredClone(current.document); document.blocks=[...$('blocks').children].map(row=>{const type=row.dataset.type,text=row.querySelector('textarea').value; if(type==='list')return{type,items:text.split('\n'),ordered:row.dataset.ordered==='true'};if(type==='table')return{type,rows:text.split('\n').map(r=>r.split('\t'))};return{type,text,...(type==='heading'?{level:Number(row.dataset.level)}:{})};});
    document.language=$('language').value;document.credit=$('credit').value;document.notes=$('notes').value;document.permissions.text={status:$('permission').value,basis:$('basis').value,rightsholder:$('rightsholder').value,purpose:'public_web_text',third_party_check:$('exceptions').value};if($('expiry').value)document.permissions.text.expires_at=$('expiry').value;return document;
  }
  async function save() { const id=articleId, revision=current.revision, document=documentValue(), view=generation;
    const result=await api('/api/articles/'+id+'/draft',{revision,document});
    if(articleId!==id||generation!==view)throw new Error('页面已切换，原草稿已保存；请重新核对当前文章。');
    if(JSON.stringify(documentValue())!==JSON.stringify(document)){current.revision=result.revision;editing=true;throw new Error('保存期间正文或许可有修改，请再次保存并核对后发布。');}
    current.revision=result.revision;current.document=document;editing=false;message('草稿已保存，尚未发布。');
    return {id,revision:result.revision,view};
  }
  async function open(id) {
    articleId=id; const request=++generation,data=await api('/api/articles/'+id); if(request!==generation||articleId!==id)return;current=data;editing=false;$('queue').hidden=true;$('editor').hidden=false;$('title').textContent=data.article.title;$('meta').textContent=data.article.source_name+' · 当前展示：'+({full_text:'本站全文',link_only:'原文阅读',unavailable:'暂不可用'}[data.public.reading_mode]||'原文阅读');$('original').href=data.article.original_url;
    $('draft').hidden=!data.document;$('blocks').replaceChildren();if(data.document){data.document.blocks.forEach(drawBlock);const d=data.document,p=d.permissions.text;$('language').value=d.language;$('credit').value=d.credit;$('notes').value=d.notes;$('permission').value=p.status;$('basis').value=p.basis||'';$('rightsholder').value=p.rightsholder||'';$('exceptions').value=p.third_party_check||'';$('expiry').value=p.expires_at||'';}
    ['license-checked','complete-checked','republish'].forEach(id=>$(id).checked=false);drawJobs(data);drawImages(data);drawAssets(data);
  }
  function drawImages(data) {
    $('storage').textContent='图片保存在服务器持久数据卷，审核后直接从本站加载。';$('images').replaceChildren();
    for(const candidate of data.candidates){const row=make('div');row.className='image-review';const original=make('a','在原站查看候选图片 ↗');original.href=candidate.source_url;original.target='_blank';original.rel='noopener noreferrer';row.append(original);
      const caption=input('图注',candidate.caption,true),credit=input('图片署名/credit',''),basis=input('图片转载许可依据','',true),holder=input('图片权利人',''),exceptions=input('第三方例外核对','',true),expiry=input('图片许可有效期（可空，带时区）','');[caption,credit,basis,holder,exceptions,expiry].forEach(v=>row.append(v.wrapper));
      const imagePermission=make('select'), permissionLabel=make('label','图片许可类型');
      [['policy_reviewed','符合已核对的公开条款'],['explicit_grant','已取得明确授权']].forEach(([value,name])=>{const option=make('option',name);option.value=value;imagePermission.append(option);});permissionLabel.append(imagePermission);row.append(permissionLabel);
      const position=make('select'), positionLabel=make('label','图片显示位置（请按当前正文重新核对）');positionLabel.append(position);
      const before=make('option','正文之前');before.value='0';position.append(before);
      data.document?.blocks.forEach((block,index)=>{const excerpt=(block.text||(block.items||[]).join(' ')||(block.rows||[]).flat().join(' ')).slice(0,35);const option=make('option','在此内容之后：'+excerpt);option.value=String(index+1);position.append(option);});
      position.value=candidate.block_index<=data.document?.blocks.length?String(candidate.block_index):'';row.append(positionLabel);
      const check=make('input');check.type='checkbox';const label=make('label','已核对图片对应本文、显示位置、图注和署名，确认允许本站存储与展示');label.className='check';label.prepend(check);row.append(label);const button=make('button','审核图片并抓取保存');button.disabled=!storage.enabled||data.public.reading_mode!=='full_text';row.append(button);
      button.addEventListener('click',()=>act(button,async()=>{if(!check.checked||position.value==='')throw new Error('请先核对图片许可和显示位置。');if(editing)throw new Error('正文有修改，请先保存并发布当前版本。');const permission={status:imagePermission.value,basis:basis.field.value,rightsholder:holder.field.value,purpose:'public_web_image',third_party_check:exceptions.field.value};if(expiry.field.value)permission.expires_at=expiry.field.value;await api('/api/articles/'+articleId+'/images',{revision:current.revision,source_url:candidate.source_url,block_index:Number(position.value),position_checked:true,caption:caption.field.value,credit:credit.field.value,permission});message('图片已进入抓取保存队列。保存成功且许可有效后将自动展示。');drawJobs(await api('/api/articles/'+articleId));}));$('images').append(row);
    }
  }
  function drawAssets(data) { $('assets').replaceChildren();for(const asset of data.assets){const row=make('div');row.className='asset';row.append(make('p',asset.caption+' · '+asset.credit+' · '+asset.status+' · '+(asset.current?'当前正文版本':'历史正文版本')));if(asset.status==='ready'){const reason=input('图片撤回原因',''),button=make('button','撤回图片');row.append(reason.wrapper,button);button.addEventListener('click',()=>act(button,async()=>{await api('/api/assets/'+asset.id+'/withdraw',{reason:reason.field.value});await open(articleId);message('图片已撤下。本站图片接口不再提供新的访问。');}));}$('assets').append(row);} }
  $('capture').addEventListener('click',()=>act($('capture'),async()=>{if(editing)throw new Error('先保存编辑的草稿。');await api('/api/articles/'+articleId+'/capture',{revision:current.revision});message('正文抓取已排队，完成后请重新读取并人工核对。');drawJobs(await api('/api/articles/'+articleId));}));
  $('reload').addEventListener('click',()=>act($('reload'),async()=>{if(editing)throw new Error('请先保存草稿，避免丢失编辑。');await open(articleId);}));
  $('add-paragraph').addEventListener('click',()=>{drawBlock({type:'paragraph',text:''});editing=true;}); $('save').addEventListener('click',()=>act($('save'),save));
  $('approve').addEventListener('click',()=>act($('approve'),async()=>{if(!$('license-checked').checked||!$('complete-checked').checked)throw new Error('请确认正文许可与完整性。');const republish=$('republish').checked;const saved=await save();if(articleId!==saved.id||generation!==saved.view)throw new Error('页面已切换，请重新核对许可。');await api('/api/articles/'+saved.id+'/approve',{revision:saved.revision,license_checked:true,complete_checked:true,republish});if(articleId===saved.id&&generation===saved.view){await open(saved.id);message('审核通过，当前版本已发布。');}}));
  $('withdraw').addEventListener('click',()=>act($('withdraw'),async()=>{await api('/api/articles/'+articleId+'/withdraw',{reason:$('withdraw-reason').value});await open(articleId);message('正文已撤回；关联图片不再提供新的访问链接。');}));
  $('draft').addEventListener('input',()=>{editing=true;});
  setInterval(async()=>{if(!articleId||!csrf)return;const id=articleId;try{const data=await api('/api/articles/'+id);if(articleId===id)drawJobs(data);}catch{}},5000);
  loggedIn().catch(()=>loggedOut());
})();
