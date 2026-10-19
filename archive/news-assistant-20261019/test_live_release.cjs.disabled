// Read-only production acceptance: API writes are blocked, no model calls.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'C:/Users/14243/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root=path.resolve(__dirname,'..'),out=path.join(root,'artifacts/live-release-20261017');fs.mkdirSync(out,{recursive:true});
const origin=process.env.SITE_URL || 'https://8.137.164.100:8080';
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.GALLERY_BROWSER || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
 const errors=[],writes=[],checks=[];
 try{
  const c=await browser.newContext({viewport:{width:1440,height:1000}});
  await c.route('**/api/**',r=>{if(r.request().method()!=='GET'){writes.push(r.request().method()+' '+r.request().url());return r.abort();}return r.continue();});
  const p=await c.newPage();p.on('pageerror',e=>errors.push(e.message));
  const response=await p.request.get(origin+'/');assert(response.ok());
  const manifest=JSON.parse(fs.readFileSync(path.join(root,'artifacts/server-aligned-release-20261017/manifest.json'),'utf8'));
  assert.equal(crypto.createHash('sha256').update(await response.body()).digest('hex'),manifest.files.find(f=>f.path==='web/index.html').sha256);
  await p.goto(origin+'/?release=20261017',{waitUntil:'domcontentloaded'});await p.waitForSelector('#gallery-welcome[open]');await p.click('#gallery-skip');
  await p.waitForSelector('#cover-dots button');await p.hover('.space-cover');
  assert.equal(await p.locator('#cover-dots button').count(),12);assert.equal(await p.locator('main#gallery').count(),0);
  await p.screenshot({path:path.join(out,'homepage.png')});checks.push('Public HTTPS index matches release; welcome and 12-slide news carousel');
  const links=p.locator('.news-article h2 a');await links.first().waitFor();await links.first().click();
  await p.waitForSelector('.reader-split');await p.waitForSelector('.reader-assistant .news-agent-status');
  assert.equal(await p.evaluate(()=>{const a=document.querySelector('.reader-news').getBoundingClientRect(),b=document.querySelector('.reader-assistant').getBoundingClientRect();return a.right<=b.left+1 && Math.abs(a.top-b.top)<2;}),true);
  await p.screenshot({path:path.join(out,'reader.png')});await p.click('.reader-close');checks.push('Real news article opens in left/right reader panes');
  await p.goto(origin+'/assets/resource-navigation.html?release=20261017');await p.waitForSelector('.book-card');
  assert.equal(await p.locator('.book-card').count(),27);assert.equal(await p.evaluate(()=>window.ZhihangBooks.every(b=>b.material_type==='图书')),true);
  await p.fill('#search','9787040514223');await p.waitForFunction(()=>document.querySelectorAll('.book-card').length===1);
  assert.match(await p.locator('.book-card').textContent(),/第5版/);assert.match(await p.locator('.book-card').textContent(),/陶文铨/);
  await p.locator('.book-card').scrollIntoViewIfNeeded();await p.locator('.book-card img').evaluate(n=>n.decode());
  await p.locator('.book-card').screenshot({path:path.join(out,'heat-transfer-fifth.png')});
  await p.setViewportSize({width:390,height:844});assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await p.locator('.book-card').screenshot({path:path.join(out,'heat-transfer-mobile.png')});checks.push('27 formal books, fifth-edition heat transfer and mobile layout');
  assert.deepEqual(writes,[]);assert.deepEqual(errors,[]);
  const report={origin,checks,apiWrites:writes,errors};fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
