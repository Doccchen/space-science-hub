// Exercise the actual news dialog with local fixtures; no publisher/API traffic.
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'C:/Users/14243/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const web = path.resolve(__dirname, '../web'), out = path.resolve(__dirname, '../artifacts/news-reader-20261023');
fs.mkdirSync(out, {recursive:true});
const original = 'https://www.nasa.gov/news-release/test/';
const preview = process.argv.includes('--preview');
const item = {id:1,title:'NASA Marshall 新闻正文与相关论文入口',source_name:'NASA',source_id:'nasa',original_url:original,published_at:'2026-10-23',lang:'en',reading_mode:'full_text',summary:'Local fixture',publisher_kind:'agency',region:'international',content_version:'fixture:1'};
if (preview) Object.assign(item, {title:'NASA’s DAVINCI Probe Can Stand the Heat',source_name:'本地界面样例',lang:'zh',original_url:'https://www.nasa.gov/image-article/nasas-davinci-probe-can-stand-the-heat/'});
let mode = 'full';
const content = () => ({reading_mode:mode === 'empty' ? 'link_only':'full_text',read_scope:mode === 'empty' ? 'link_only':'full_text',language:preview?'zh':'en',content_version:'fixture:1',credit:preview?'本地预览样例':'NASA / Example author',notes:mode === 'empty' ? '正文暂不可用，请查看发布方原文。':'自动转载政府来源原始语言正文，保留发布方署名和原文入口；图片另行处理。',assets:[],blocks:mode === 'empty' ? []:preview?[
  {type:'paragraph',block_id:'b001',text:'这是用于查看页面改进的本地界面样例。仅在标题附近保留“搜索相关论文”按钮；原有的转载、图片提示及核验入口已移除。'},
  {type:'heading',block_id:'b002',level:2,text:'正文中的网址可以直接点击'},
  {type:'paragraph',block_id:'b003',text:'For more information on NASA Marshall, visit:\nhttps://www.nasa.gov/marshall'},
  {type:'markdown',block_id:'b004',text:'也可以通过文字链接访问 [NASA Marshall](https://www.nasa.gov/marshall)。外部页面会在新标签页打开，当前阅读位置保留。'},
]:[
  {type:'paragraph',block_id:'b001',text:'For more information on NASA Marshall, visit:\nhttps://www.nasa.gov/marshall.\n(https://www.nasa.gov/a_(b))，以及 https://www.nasa.gov/search?q=mars&year=2026#results。'},
  {type:'paragraph',block_id:'b002',text:'🚀 Read NASA Marshall and source.',links:[{start:7,end:20,url:'https://www.nasa.gov/marshall'},{start:25,end:31,url:'/source?x=1#about'}]},
  {type:'markdown',block_id:'b003',text:'[Mission](../mission?x=1#about) and https://www.nasa.gov/plain\n\n`https://www.nasa.gov/code`\n\n[unsafe](javascript:alert) <script>window.pwned=true</script>'},
  {type:'list',block_id:'b004',items:['See https://www.nasa.gov/list']},
  {type:'table',block_id:'b005',rows:[['source']],links:[{row:0,column:0,start:0,end:6,url:'https://www.nasa.gov/table'}]},
  {type:'paragraph',block_id:'b006',text:'https://www.nasa.gov/'+ 'long-path-'.repeat(45)},
]});
const server = http.createServer(async (req,res) => {
  const url = new URL(req.url, 'http://localhost');
  if (url.pathname.startsWith('/api/')) {
    let data = {enabled:false,available:false,items:[],geographic_regions:[]};
    if (url.pathname === '/api/news') data = {items:[item],total:1,page:1,page_size:10,total_pages:1};
    if (url.pathname === '/api/news/1') data = item;
    if (url.pathname === '/api/news/1/content') {
      if (mode === 'error') {res.writeHead(503);res.end();return;}
      if (mode === 'loading') await new Promise(resolve=>setTimeout(resolve,2000));
      data = content();
    }
    res.writeHead(200,{'content-type':'application/json'});res.end(JSON.stringify(data));return;
  }
  const file = path.resolve(web, url.pathname === '/' ? 'index.html' : decodeURIComponent(url.pathname.replace(/^\/assets\//,'')));
  if (!file.startsWith(web+path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {res.writeHead(404);res.end();return;}
  const types = {'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css','.svg':'image/svg+xml','.webp':'image/webp'};
  res.writeHead(200,{'content-type':types[path.extname(file)] || 'application/octet-stream'});fs.createReadStream(file).pipe(res);
});
(async () => {
  await new Promise(resolve=>server.listen(preview ? Number(process.env.NEWS_PREVIEW_PORT || 0) : 0,'127.0.0.1',resolve));
  const origin = 'http://127.0.0.1:'+server.address().port;
  if (preview) {console.log('Local news preview: '+origin+'/#news/article/1');return;}
  const browser = await chromium.launch({executablePath:process.env.GALLERY_BROWSER || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
  const errors = [], report = [];
  try {
    const context = await browser.newContext();
    await context.route('https://www.nasa.gov/**',route=>route.fulfill({body:'Local destination fixture'}));
    const page = await context.newPage();page.on('pageerror',e=>errors.push(e.message));
    const open = async () => {await page.goto(origin+'/#news/article/1');await page.locator('[data-block-id="b001"]').waitFor();};
    await open();
    assert.equal(await page.locator('.reader-paper-button').count(),1);
    assert.equal(await page.locator('.reader-news').getByText('如何核验这条信息',{exact:true}).count(),0);
    assert.doesNotMatch(await page.locator('.reader-news').textContent(),/自动转载政府来源|图片请到原文查看/);
    assert.match(await page.locator('.reader-news').textContent(),/内容署名：NASA/);
    assert.equal(await page.locator('.reader-notice a').getAttribute('href'),original);
    const urls = await page.locator('[data-block-id="b001"] a').evaluateAll(nodes=>nodes.map(a=>a.href));
    assert.deepEqual(urls,['https://www.nasa.gov/marshall','https://www.nasa.gov/a_(b)','https://www.nasa.gov/search?q=mars&year=2026#results']);
    assert.deepEqual(await page.locator('[data-block-id="b002"] a').allTextContents(),['NASA Marshall','source']);
    assert.equal(await page.locator('[data-block-id="b002"] a').last().getAttribute('href'),'https://www.nasa.gov/source?x=1#about');
    assert.equal(await page.locator('[data-block-id="b003"] a').first().getAttribute('href'),'https://www.nasa.gov/news-release/mission?x=1#about');
    assert.equal(await page.locator('.reader-news a a,.reader-news script,.reader-news a[href^="javascript:"],.reader-news code a').count(),0);
    assert.equal(await page.locator('[data-block-id="b004"] a,[data-block-id="b005"] a').count(),2);
    assert.equal(await page.evaluate(()=>window.pwned),undefined);
    const nasa = page.locator('[data-block-id="b001"] a').first();
    assert.equal(await nasa.getAttribute('target'),'_blank');assert.equal(await nasa.getAttribute('rel'),'noopener noreferrer');
    const popupReady = page.waitForEvent('popup');await nasa.click();const popup = await popupReady;
    await popup.waitForLoadState();assert.equal(popup.url(),'https://www.nasa.gov/marshall');await popup.close();
    report.push('Plain URLs, punctuation, balanced parentheses, Unicode label ranges, relative/Markdown/list/table links, safe external popup');
    for (const width of [1440,768,390]) {
      await page.setViewportSize({width,height:900});
      await page.locator('.reader-body').evaluate(el=>{el.scrollTop=0;});
      const sizes = await page.locator('.reader-paper-button').first().evaluate(el=>{const r=el.getBoundingClientRect();const parent=el.parentElement.getBoundingClientRect();return {height:r.height,width:r.width,parentWidth:parent.width};});
      assert.ok(sizes.height>=44);
      if(width===390) assert.ok(Math.abs(sizes.width-sizes.parentWidth)<2,'Mobile button fills row');
      assert.equal(await page.locator('.reader-body').evaluate(el=>el.scrollWidth<=el.clientWidth),true,'Dialog overflow at '+width);
      assert.equal(await nasa.evaluate(el=>getComputedStyle(el).fontSize===getComputedStyle(el.parentElement).fontSize),true,'Body links retain readable text size');
      await page.screenshot({path:path.join(out,'news-'+width+'.png')});
      await page.locator('[data-block-id="b006"]').evaluate(el=>{el.parentElement.parentElement.scrollTop=el.offsetTop;});
      assert.equal(await page.locator('.reader-body').evaluate(el=>el.scrollWidth<=el.clientWidth),true);
    }
    await page.emulateMedia({reducedMotion:'reduce'});
    assert.equal(await page.locator('.reader-paper-button').first().evaluate(el=>getComputedStyle(el).transitionDuration),'0s');
    await page.locator('#reader-title').focus();await page.keyboard.press('Tab');await page.keyboard.press('Tab');
    assert.equal(await page.locator('.reader-paper-button').first().evaluate(el=>el.matches(':focus-visible')),true);
    await page.keyboard.press('Enter');await page.waitForURL('**/assets/research.html?news=1');
    report.push('1440/768/390 layouts, 44px targets, long URL wrapping, reduced motion, keyboard focus and paper-search navigation');
    const originalTitle = item.title;item.title = '这是用于检查新闻正文中长标题自动换行的本地样例'.repeat(6);
    await open();assert.equal(await page.locator('.reader-body').evaluate(el=>el.scrollWidth<=el.clientWidth),true);item.title = originalTitle;
    const touchContext = await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
    const touchPage = await touchContext.newPage();await touchPage.goto(origin+'/#news/article/1');
    await touchPage.locator('.reader-paper-button').first().tap();await touchPage.waitForURL('**/assets/research.html?news=1');await touchContext.close();
    report.push('Long-title wrapping and mobile touch navigation');
    mode='loading';await page.reload({waitUntil:'commit'});await page.getByRole('heading',{name:'正在读取新闻…'}).waitFor();await page.locator('[data-block-id="b001"]').waitFor();
    mode='empty';await page.reload();await page.getByText('正文暂不可用，请查看发布方原文。',{exact:true}).waitFor();assert.equal(await page.locator('.reader-notice a').count(),1);
    mode='error';await page.reload();await page.getByRole('heading',{name:'新闻读取失败'}).waitFor();
    mode='full';await page.getByRole('button',{name:'重试',exact:true}).click();await page.locator('[data-block-id="b001"]').waitFor();
    await page.keyboard.press('Escape');await page.locator('dialog.news-reader:not([open])').waitFor({state:'attached'});
    await page.locator('.news-article h2 a').click();await page.locator('[data-block-id="b001"]').waitFor();await page.locator('.reader-close').click();
    await page.locator('dialog.news-reader:not([open])').waitFor({state:'attached'});
    assert.equal(await page.evaluate(()=>document.activeElement.closest('.news-article')?.dataset.articleId),'1');
    report.push('Loading, unavailable body/source link, fetch failure/retry, Escape and close/focus restoration');
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(out,'checks.json'),JSON.stringify({report,errors},null,2));console.log(report.join('\n'));
    await context.close();
  } finally {await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
