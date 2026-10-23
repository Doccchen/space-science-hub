// Verify public bytes and actual news with GET requests only; never submit research/model jobs.
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'C:/Users/14243/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const base = 'https://8.137.164.100:8080', out = path.resolve(__dirname, '../artifacts/news-reader-release-20261023');
(async () => {
  const browser = await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
  try {
    const context = await browser.newContext({viewport:{width:1440,height:960},reducedMotion:'reduce'});
    const errors = [], methods = new Set(), checked = [];
    context.on('request', request => {methods.add(request.method());assert.equal(request.method(),'GET');});
    const page = await context.newPage();page.on('pageerror', error => errors.push(error.message));
    const manifest = JSON.parse(fs.readFileSync(path.join(out,'manifest.json'),'utf8'));
    for (const [name, expected] of Object.entries(manifest.files)) {
      if (!name.startsWith('web/')) continue;
      const response = await context.request.get(base+(name==='web/index.html'?'/':'/assets/'+name.slice(4)));
      assert(response.ok(),name);
      assert.equal(crypto.createHash('sha256').update(await response.body()).digest('hex'),expected,name);
      checked.push(name);
    }
    const response = await context.request.get(base+'/api/news?source=nasa&limit=30');assert(response.ok());
    const news = await response.json();let selected, content;
    for (const item of news.items.filter(item=>item.reading_mode==='full_text').slice(0,15)) {
      const current = await (await context.request.get(base+'/api/news/'+item.id+'/content')).json();
      if (!selected) {selected=item;content=current;}
      if (current.blocks.some(block=>/https?:\/\//i.test(block.text || JSON.stringify(block.items || block.rows || [])))) {selected=item;content=current;break;}
    }
    assert(selected,'No actual full-text NASA article available');
    await page.goto(base+'/#news/article/'+selected.id);await page.locator('[data-block-id]').first().waitFor();
    assert.equal(await page.locator('#reader-title').textContent(),selected.title,'Original headline');
    assert.equal(await page.locator('.reader-paper-button').count(),1,'One opening paper entry');
    assert.equal(await page.locator('.reader-paper-button').getAttribute('href'),'/assets/research.html?news='+selected.id);
    assert.equal(await page.locator('.reader-news .guide-help').count(),0);
    assert.doesNotMatch(await page.locator('.reader-notice').textContent(),/自动转载|图片请到原文查看/);
    assert.equal(await page.locator('.reader-notice a').getAttribute('href'),selected.original_url);
    const links = page.locator('[data-block-id] a');
    assert.ok(await links.count()>0,'Real news body has clickable links');
    const targets = await links.evaluateAll(nodes=>nodes.map(a=>({label:a.textContent,url:a.href,target:a.target,rel:a.rel})));
    for (const link of targets) {
      assert.match(link.url,/^https?:\/\//);
      if (new URL(link.url).origin!==base) {assert.equal(link.target,'_blank');assert.equal(link.rel,'noopener noreferrer');}
    }
    for (const width of [1440,768,390]) {
      await page.setViewportSize({width,height:960});
      await page.locator('.reader-body').evaluate(el=>{el.scrollTop=0;});
      assert(await page.locator('.reader-body').evaluate(el=>el.scrollWidth<=el.clientWidth));
      assert(await page.locator('.reader-paper-button').evaluate(el=>el.getBoundingClientRect().height>=44));
      await page.screenshot({path:path.join(out,'live-news-'+width+'.png')});
    }
    await page.locator('#reader-title').focus();await page.keyboard.press('Tab');await page.keyboard.press('Tab');
    assert(await page.locator('.reader-paper-button').evaluate(el=>el.matches(':focus-visible')));
    await page.keyboard.press('Enter');await page.waitForURL('**/assets/research.html?news='+selected.id);
    await page.waitForFunction(title=>document.getElementById('question')?.value.includes(title),selected.title);
    await page.goto(base+'/assets/guides.html#using-ai');await page.locator('#guide-body .article-content').waitFor();
    assert.deepEqual(errors,[]);
    const result = {status:'passed',public_files_checked:checked.length,article:{id:selected.id,title:selected.title},body_links:targets.length,widths:[1440,768,390],single_opening_paper_entry:true,original_title:true,source_link:true,keyboard_navigation:true,research_news_prefill:true,page_errors:errors,request_methods:[...methods],model_calls:0};
    fs.writeFileSync(path.join(out,'live-verification.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
    await context.close();
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
