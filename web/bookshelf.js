/* Existing, reviewed catalog -> stable book spines and accessible details. */
(() => {
  'use strict';
  const books=window.ZhihangBooks||[],byId=new Map(books.map(b=>[b.id,b]));
  const tones=[['#233d46','#f6efe1'],['#9c4c34','#fff2dc'],['#c7b58b','#243332'],['#344a65','#f3e8cf'],['#6f7761','#fff5de'],['#d9cbb0','#27392f']];
  const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n;};
  const dialog=el('dialog','book-detail');dialog.setAttribute('aria-labelledby','book-detail-title');
  const close=el('button','book-detail-close','关闭 ×');close.type='button';close.autofocus=true;
  const host=el('div','book-detail-body');dialog.append(close,host);document.body.append(dialog);
  let returnTo=null,openedByUs=false,oldOverflow='';
  function draw(item){
    host.replaceChildren();
    const figure=el('figure','detail-cover'),image=el('img');image.src=item.cover;image.alt=item.cover_alt||item.name+'封面';
    image.addEventListener('error',()=>{image.remove();figure.append(el('p','',item.name+' · 封面暂不可用'));},{once:true});
    figure.append(image);if(item.cover_kind&&item.cover_kind!=='封面')figure.append(el('figcaption','',item.cover_kind));
    const info=el('div','detail-info');info.append(el('p','shelf-eyebrow','ZHihang / 工程书架'));
    const title=el('h2','',item.name);title.id='book-detail-title';info.append(title);
    const meta=el('dl','detail-meta');
    for(const [label,value]of [['作者',item.authors],['出版社',item.publisher],['版次',item.edition],['ISBN',item.isbn],['语言',(item.language||[]).join(' / ')]]){
      if(!value)continue;const row=el('div');row.append(el('dt','',label),el('dd','',value));meta.append(row);
    }
    info.append(meta,el('h3','','内容简介'),el('p','detail-description',item.desc),el('p','detail-topics',(item.topics||[]).join(' / ')),el('p','detail-footnote','这里展示书目信息与简介，不提供整本 PDF 下载。'));
    host.append(figure,info);
  }
  function open(item,trigger,writeHistory=true){
    if(!item)return;draw(item);returnTo=trigger||document.activeElement;
    if(!dialog.open){oldOverflow=document.body.style.overflow;document.body.style.overflow='hidden';dialog.showModal();}
    if(writeHistory){const u=new URL(location.href);u.searchParams.set('book',item.id);history.pushState({book:item.id},'',u);openedByUs=true;}
    close.focus({preventScroll:true});
  }
  function hide(update=true){
    if(dialog.open)dialog.close();document.body.style.overflow=oldOverflow;
    const target=returnTo?.isConnected?returnTo:document.getElementById('search');target?.focus({preventScroll:true});
    if(update){if(openedByUs){openedByUs=false;history.back();}else{const u=new URL(location.href);u.searchParams.delete('book');history.replaceState({},'',u);}}
  }
  close.addEventListener('click',()=>hide());
  dialog.addEventListener('cancel',e=>{e.preventDefault();hide();});
  dialog.addEventListener('click',e=>{const r=dialog.getBoundingClientRect();if(e.target===dialog&&(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom))hide();});
  window.addEventListener('popstate',()=>{const item=byId.get(new URL(location.href).searchParams.get('book'));if(item)open(item,null,false);else hide(false);});
  function book(item){
    const index=books.indexOf(item),slot=el('article','shelf-slot');slot.dataset.bookId=item.id;
    const hit=el('button','shelf-hit');hit.type='button';hit.setAttribute('aria-label','查看《'+item.name+'》图书详情');hit.setAttribute('aria-haspopup','dialog');
    const tone=tones[Math.max(0,index)%tones.length],height=276+(Math.max(index,0)%4)*12;
    slot.style.setProperty('--spine-color',tone[0]);slot.style.setProperty('--spine-ink',tone[1]);slot.style.setProperty('--book-height',height+'px');
    if(item.name.length>20)slot.classList.add('long-title');
    const solid=el('span','book-solid'),spine=el('span','book-spine');
    spine.append(el('span','spine-number',String(index+1).padStart(2,'0')),el('span','spine-title',item.name),el('span','spine-mark','↗'));
    const face=el('span','book-front'),cover=el('img');cover.src=item.cover;cover.alt='';cover.loading='lazy';cover.decoding='async';
    cover.addEventListener('error',()=>{cover.remove();face.append(el('span','',item.name));},{once:true});
    face.append(cover);solid.append(spine,face,el('span','book-pages'));hit.append(solid);slot.append(hit);
    hit.addEventListener('click',()=>open(item,hit));return slot;
  }
  window.ZhihangShelf={book};
  const initial=byId.get(new URL(location.href).searchParams.get('book'));
  if(initial)requestAnimationFrame(()=>open(initial,null,false));
})();
