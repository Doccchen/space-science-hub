// Real browser, local static server and fixed API fixtures. Never calls production.
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'C:/Users/14243/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root=path.resolve(__dirname,'..'), web=path.join(root,'web'), output=path.join(root,'artifacts/server-aligned-verification-20261017');
fs.mkdirSync(output,{recursive:true});
const item={id:1,title:'本地样例：航天工程阅读',source_name:'本地固定样例',source_id:'cnsa',original_url:'https://www.cnsa.gov.cn/',published_at:'2026-10-12',lang:'zh',reading_mode:'full_text',summary:'本地验证摘要',publisher_kind:'agency',region:'domestic',content_version:'fixture:1'};
const server=http.createServer((req,res)=>{
 const url=new URL(req.url,'http://localhost');
 if(url.pathname.startsWith('/api/')){
  assert.equal(req.method,'GET','No model or mutation requests are permitted');
  let data={enabled:false,available:false,message:'本地预览：服务未连接',items:[],geographic_regions:[]};
  if(url.pathname==='/api/news')data={items:[item],total:1,page:1,page_size:10,total_pages:1};
  if(url.pathname==='/api/news/1')data=item;
  if(url.pathname==='/api/news/1/content')data={reading_mode:'full_text',read_scope:'full_text',language:'zh',content_version:'fixture:1',blocks:[{type:'paragraph',block_id:'1',text:'这是本地固定样例正文，用于验证双栏布局与返回焦点。'}],assets:[],notes:'本地样例'};
  res.writeHead(200,{'content-type':'application/json'});res.end(JSON.stringify(data));return;
 }
 const file=path.resolve(web,url.pathname==='/'?'index.html':decodeURIComponent(url.pathname.replace(/^\/assets\//,'')));
 if(!file.startsWith(web+path.sep)||!fs.existsSync(file)){res.writeHead(404);res.end();return;}
 const types={'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json','.svg':'image/svg+xml','.jpg':'image/jpeg','.webp':'image/webp','.png':'image/png'};
 res.writeHead(200,{'content-type':types[path.extname(file)]||'application/octet-stream'});fs.createReadStream(file).pipe(res);
});


const report=[];
(async()=>{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const origin='http://127.0.0.1:'+server.address().port;
 if(process.argv.includes('--preview')){console.log('Server-aligned preview: '+origin);await new Promise(()=>{});}
 const browser=await chromium.launch({executablePath:process.env.GALLERY_BROWSER || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
 try{
  if(process.argv.includes('--books')){
   const c=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'}),p=await c.newPage(),errors=[];
   p.on('pageerror',e=>errors.push(e.message));
   await p.goto(origin+'/assets/resource-navigation.html');await p.waitForSelector('.book-card');
   assert.equal(await p.evaluate(()=>window.ZhihangBooks.length),27);assert.equal(await p.locator('.book-card').count(),27);
   const data=await p.evaluate(()=>window.ZhihangBooks);
   const heat=data.find(b=>b.name==='传热学');assert.equal(heat.edition,'第5版');assert.equal(heat.isbn,'9787040514223');assert.equal(heat.authors,'陶文铨 编著');
   assert.equal(data.filter(b=>b.name==='传热学').length,1);
   for(const book of data){const response=await p.request.get(origin+book.cover);assert(response.ok(),'Missing cover '+book.name);}
   await p.locator('#category-index button').filter({hasText:'专业图书'}).click();
   assert.equal(await p.locator('.book-card').count(),27);
   await p.fill('#search','9787040514223');await p.waitForFunction(()=>document.querySelectorAll('.book-card').length===1);
   assert.match(await p.locator('.book-card').textContent(),/第5版/);assert.match(await p.locator('.book-card').textContent(),/陶文铨/);
   await p.locator('.book-card').screenshot({path:path.join(output,'heat-transfer-fifth.png')});
   assert(data.every(b=>b.material_type==='图书'));
   assert(data.every(b=>!['book-01','book-08','book-10'].includes(b.id)));
   await p.fill('#search','不存在的书目测试');await p.waitForSelector('#empty:not([hidden])');
   await p.fill('#search','');await p.waitForFunction(()=>document.querySelectorAll('.book-card').length===27);
   await p.locator('.book-card').first().scrollIntoViewIfNeeded();await p.locator('.book-card').first().locator('img').evaluate(n=>n.decode());
   await p.locator('.book-card').first().screenshot({path:path.join(output,'professional-books-first.png')});
   await p.locator('.book-card').last().scrollIntoViewIfNeeded();await p.locator('.book-card').last().locator('img').evaluate(n=>n.decode());
   await p.locator('.book-card').last().screenshot({path:path.join(output,'professional-books-last.png')});
   await p.setViewportSize({width:390,height:844});await p.fill('#search','传热学');await p.waitForFunction(()=>document.querySelectorAll('.book-card').length===1);
   assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
   await p.locator('.book-card').screenshot({path:path.join(output,'heat-transfer-mobile.png')});
   assert.deepEqual(errors,[]);console.log('27 formal book entries, all cover assets, heat-transfer fifth edition, ISBN search, no notes or lecture materials, empty state and mobile layout passed.');
   await c.close();return;
  }
  const context=await browser.newContext({viewport:{width:1440,height:900}}),page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(origin);await page.waitForSelector('#gallery-welcome[open]');await page.waitForTimeout(600);await page.screenshot({path:path.join(output,'welcome.png')});await page.click('#gallery-skip');
  await page.waitForSelector('#news:not(.hidden) .space-cover[data-slide="earthrise"]');await page.hover('.space-cover');await page.waitForTimeout(500);
  assert.equal(await page.locator('main#gallery').count(),0);assert.equal(await page.locator('body > header').isVisible(),true);assert.equal(await page.locator('#cover-dots button').count(),12);
  await page.screenshot({path:path.join(output,'desktop-live-layout.png')});
  const slides=JSON.parse(fs.readFileSync(path.join(web,'history-slides.json'),'utf8'));
  for(let i=0;i<slides.length;i++){await page.locator('#cover-dots button').nth(i).click();await page.waitForSelector('.space-cover[data-slide="'+slides[i].id+'"]');assert.equal(await page.locator('#cover-credit').textContent(),(slides[i].date?slides[i].date+' / ':'')+slides[i].credit);}
  assert.equal(await page.locator('#cover-dots [aria-pressed=true]').count(),1);
  await page.locator('#cover-dots button').nth(5).click();await page.waitForSelector('.space-cover[data-slide="landspace-sunset"]');await page.waitForTimeout(800);await page.screenshot({path:path.join(output,'desktop-added-slide.png')});
  await page.reload();await page.waitForSelector('.space-cover');assert.equal(await page.locator('#gallery-welcome').getAttribute('open'),null);
  report.push('Live news-page carousel restored: original 5 + 7 official additions, metadata aligned');
  await page.locator('.news-article h2 a').click();await page.waitForSelector('.reader-split');await page.waitForSelector('.reader-assistant .news-agent-status');
  const panes=await page.evaluate(()=>{const a=document.querySelector('.reader-news').getBoundingClientRect(),b=document.querySelector('.reader-assistant').getBoundingClientRect();return {sideBySide:a.right<=b.left+1,sameTop:Math.abs(a.top-b.top)<2};});assert.equal(panes.sideBySide,true);assert.equal(panes.sameTop,true);
  await page.screenshot({path:path.join(output,'reader-two-columns.png')});await page.click('.reader-close');await page.waitForSelector('dialog.news-reader:not([open])',{state:'attached'});assert.equal(await page.evaluate(()=>document.activeElement.closest('.news-article')?.dataset.articleId),'1');
  await page.click('header [data-page=home]');await page.waitForSelector('#home:not(.hidden)');await page.click('#home-link');await page.waitForSelector('#news:not(.hidden)');await page.click('header [data-page=library]');await page.waitForURL('**/assets/resource-navigation.html');await page.click('a.brand');await page.waitForURL('**/#news');
  report.push('Two-column reading, close/focus, AI, brand and resource routes retained');
  for(const route of ['#news','#home','#news/article/1']){const c=await browser.newContext(),p=await c.newPage();await p.goto(origin+'/'+route);await p.waitForTimeout(200);assert.equal(await p.locator('#gallery-welcome').getAttribute('open'),null);assert.equal(await p.locator('main.page:not(.hidden)').getAttribute('id'),route==='#home'?'home':'news');if(route.includes('article'))await p.waitForSelector('.reader-split');await c.close();}
  const reduced=await browser.newContext({reducedMotion:'reduce'}),rp=await reduced.newPage();await rp.goto(origin);await rp.waitForSelector('.space-cover');assert.equal(await rp.locator('#gallery-welcome').getAttribute('open'),null);await reduced.close();
  const blocked=await browser.newContext(),bp=await blocked.newPage();await bp.addInitScript(()=>Object.defineProperty(window,'localStorage',{get(){throw Error('blocked')}}));await bp.goto(origin);await bp.waitForSelector('.space-cover');assert.equal(await bp.locator('#gallery-welcome').getAttribute('open'),null);await blocked.close();
  report.push('Welcome once, direct routes bypass intro, storage and reduced-motion fallback');
  for(const viewport of [{width:320,height:667},{width:390,height:844},{width:768,height:1024}]){
   const c=await browser.newContext({viewport,reducedMotion:'reduce'}),p=await c.newPage();await p.goto(origin);await p.waitForSelector('#cover-dots button');assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
   await p.locator('#cover-dots button').last().click();await p.waitForSelector('.space-cover[data-slide="landspace-testbed"]');await p.screenshot({path:path.join(output,'mobile-'+viewport.width+'.png'),fullPage:true});await c.close();
  }
  report.push('320/390/768px layout and 12th-slide access');assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(output,'browser-checks.json'),JSON.stringify({origin,checks:report,errors},null,2));console.log(report.join('\n'));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>server.close());
