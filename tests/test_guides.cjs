// Real browser with local files and fixed news fixtures. No production access.
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'C:/Users/14243/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root = path.resolve(__dirname, '..'), web = path.join(root, 'web'), out = path.join(root, 'artifacts/guides-20261021');
fs.mkdirSync(out, {recursive:true});
const item = {id:1,title:'本地核验样例',source_name:'本地样例',source_id:'cnsa',original_url:'https://www.cnsa.gov.cn/',published_at:'2026-10-21',lang:'zh',reading_mode:'full_text',summary:'核验样例',publisher_kind:'agency',region:'domestic',content_version:'fixture:1'};
let markdownNews = false;
const server = http.createServer((req,res) => {
  const url = new URL(req.url, 'http://localhost');
  if (url.pathname.startsWith('/api/')) {
    let data = {enabled:false,available:false,items:[],geographic_regions:[]};
    if (url.pathname === '/api/news') data = {items:[item],total:1,page:1,page_size:10,total_pages:1};
    if (url.pathname === '/api/news/1') data = item;
    if (url.pathname === '/api/news/1/content') data = {reading_mode:'full_text',read_scope:'full_text',language:'zh',content_version:'fixture:1',blocks:markdownNews ? [{type:'markdown',block_id:'b001',text:'## 原文信息\n\n**计划**开展试验。\n\n![未审核图片](https://example.com/private.jpg)'}] : [{type:'paragraph',block_id:'b001',text:'原有新闻段落。'},{type:'table',block_id:'b002',rows:[['参数','值'],['高度','示例']]}],assets:[],notes:'本地固定样例'};
    res.writeHead(200,{'content-type':'application/json'}); res.end(JSON.stringify(data)); return;
  }
  const file = path.resolve(web, url.pathname === '/' ? 'index.html' : decodeURIComponent(url.pathname.replace(/^\/assets\//,'')));
  if (!file.startsWith(web + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {res.writeHead(404);res.end();return;}
  const types = {'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css','.json':'application/json','.md':'text/plain; charset=utf-8','.svg':'image/svg+xml','.png':'image/png','.webp':'image/webp','.jpg':'image/jpeg'};
  res.writeHead(200,{'content-type':types[path.extname(file)] || 'application/octet-stream'}); fs.createReadStream(file).pipe(res);
});
(async () => {
  await new Promise(resolve => server.listen(0,'127.0.0.1',resolve));
  const origin = 'http://127.0.0.1:' + server.address().port;
  if (process.argv.includes('--preview')) { console.log('Local fixture preview: ' + origin + '/assets/guides.html'); return; }
  const browser = await chromium.launch({executablePath:process.env.GALLERY_BROWSER || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
  const errors = [], report = [];
  try {
    const context = await browser.newContext({reducedMotion:'reduce'}), page = await context.newPage();
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(origin + '/assets/guides.html#using-ai');
    await page.waitForSelector('#guide-body .article-content');
    assert.equal(await page.locator('#guide-index a').count(),4);
    for (const width of [1440,820,390,320]) {
      await page.setViewportSize({width,height:900});
      for (const id of ['using-ai','evaluating-output','verifying-sources','academic-integrity']) {
        await page.locator('#guide-index a[href="#'+id+'"]').click();
        await page.waitForSelector('#guide-body .article-content');
        assert.equal(await page.locator('#guide-index [aria-current=page]').getAttribute('href'),'#'+id);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),true,'Guide overflow at '+width);
      }
      await page.screenshot({path:path.join(out,'guide-'+width+'.png'),fullPage:true});
    }
    report.push('Four documents, active navigation, responsive widths 1440 / 820 / 390 / 320, reduced motion');
    await page.goto(origin+'/assets/guides.html#using-ai'); await page.waitForSelector('#guide-body .article-content');
    await page.locator('#guide-body a').last().click(); await page.waitForFunction(()=>document.querySelector('#guide-title').textContent==='辨别模型输出');
    assert.equal(await page.evaluate(()=>document.activeElement.id),'guide-title');
    await page.goBack(); await page.waitForFunction(()=>document.querySelector('#guide-title').textContent==='正确使用 AI 工具');
    await page.locator('#guide-index a').nth(2).focus();await page.keyboard.press('Enter');
    await page.waitForFunction(()=>document.activeElement.id==='guide-title');
    await page.reload();await page.waitForSelector('#guide-body .article-content');assert.equal(await page.title(),'知航');
    await page.goto(origin+'/assets/guides.html#missing');await page.waitForFunction(()=>document.querySelector('#guide-title').textContent==='未找到这篇指南');
    assert.equal(await page.locator('#guide-actions').isVisible(),false);
    report.push('Direct links, refresh, body cross-links, browser back, keyboard selection and focus, unknown document');
    let fail = true;
    await page.route('**/guides/using-ai.md',route=>fail?route.fulfill({status:503,body:'unavailable'}):route.continue());
    await page.goto(origin+'/assets/guides.html#using-ai');await page.waitForSelector('#guide-retry:not([hidden])');
    fail = false;await page.click('#guide-retry');await page.waitForSelector('#guide-body .article-content');
    await page.unroute('**/guides/using-ai.md');
    await page.route('**/guides/evaluating-output.md',route=>route.fulfill({status:200,body:'   '}));
    await page.locator('#guide-index a').nth(1).click();await page.waitForSelector('#guide-retry:not([hidden])');
    await page.unroute('**/guides/evaluating-output.md');
    await page.click('#guide-retry');await page.waitForSelector('#guide-body .article-content');
    const failurePage = await context.newPage(); let manifestFails = true;
    await failurePage.route('**/guides/index.json', route => manifestFails ? route.fulfill({status:503,body:'unavailable'}) : route.continue());
    await failurePage.goto(origin+'/assets/guides.html');await failurePage.waitForSelector('#guide-retry:not([hidden])');
    manifestFails = false;await failurePage.click('#guide-retry');await failurePage.waitForSelector('#guide-body .article-content');await failurePage.close();
    await page.evaluate(() => { navigator.clipboard.writeText = async value => { window.copiedGuideURL = value; }; });
    await page.click('#guide-copy'); assert.equal(await page.evaluate(()=>window.copiedGuideURL),origin+'/assets/guides.html#evaluating-output');
    report.push('Document failure and empty content fail visibly; retry restores reading');
    const safe = await page.evaluate(() => {
      window.pwned = false;
      const target = ArticleRenderer.markdown('## Test\n\n<script>window.pwned=true</script>\n\n[bad](javascript:alert(1)) ![bad](https://example.com/a.png)\n\n**bold** *em* `code`\n\n1. first\n2. next\n\n> quoted\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\n```html\n<img src=x onerror=alert(1)>\n```');
      document.body.append(target);
      const deepQuote = ArticleRenderer.markdown('>'.repeat(11000)+' example');
      return {executed:window.pwned,scripts:target.querySelectorAll('script,iframe,img').length,unsafeLinks:target.querySelectorAll('a[href^="javascript:"]').length,bold:target.querySelectorAll('strong').length,code:target.querySelectorAll('pre code').length,table:target.querySelectorAll('th').length,list:target.querySelectorAll('ol li').length,quote:target.querySelectorAll('blockquote').length,boundedQuote:deepQuote.querySelectorAll('blockquote').length<=13};
    });
    assert.deepEqual(safe,{executed:false,scripts:0,unsafeLinks:0,bold:1,code:1,table:2,list:2,quote:1,boundedQuote:true});
    report.push('DOM-only rendering: scripts inert, dangerous URLs removed, unapproved images blocked, supported syntax rendered');
    await page.setViewportSize({width:1440,height:900});
    await page.goto(origin+'/#news/article/1');await page.waitForSelector('.reader-news [data-block-id="b001"]');
    assert.match(await page.locator('[data-block-id="b001"]').textContent(),/原有新闻/);
    assert.equal(await page.locator('.reader-table').count(),1);
    assert.equal(await page.locator('.reader-news .guide-help').count(),0);
    assert.equal(await page.locator('.reader-paper-button').count(),1);
    await page.keyboard.press('Escape');await page.waitForSelector('dialog.news-reader:not([open])',{state:'attached'});
    await page.locator('.news-article h2 a').click();await page.waitForSelector('.reader-news');await page.click('.reader-close');
    await page.waitForSelector('dialog.news-reader:not([open])',{state:'attached'});
    assert.equal(await page.evaluate(()=>document.activeElement.closest('.news-article')?.dataset.articleId),'1');
    markdownNews = true;
    await page.goto(origin+'/#news/article/1');await page.waitForSelector('[data-block-id="b001"] strong');
    assert.equal(await page.locator('[data-block-id="b001"] strong').textContent(),'计划');
    assert.equal(await page.locator('.reader-news img').count(),0);
    assert.equal(await page.locator('[data-block-id="b001"]').getAttribute('id'),'reading-1-fixture-1-b001');
    await page.screenshot({path:path.join(out,'news-markdown.png'),fullPage:true});
    for (const width of [820,390]) {await page.setViewportSize({width,height:900});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await page.screenshot({path:path.join(out,'news-markdown-'+width+'.png')});}
    report.push('Legacy and Markdown news, table, stable block ID, original-source link, removed guide entry, paper buttons, Escape, close/focus restoration');
    await page.route('**/api/ai/status',route=>route.fulfill({json:{enabled:true,message:'本地测试',history_retention_seconds:600}}));
    await page.route('**/api/ai/conversations',route=>route.fulfill({json:{conversation_id:'local-markdown-test'}}));
    const modelAnswer = '## 技术概念\n\n这是 **重点**，也是 *解释*。\n\n1. 核对原始资料\n2. 保留不确定性\n\n> 以下内容仍需核验。\n\n| 项目 | 说明 |\n| --- | --- |\n| 条件 | '+ '较长的单元格内容'.repeat(20) +' |\n\n```text\n'+ 'long_code_'.repeat(50) +'\n```\n\n[示例链接](https://example.org/source)\n\n<script>window.modelScriptExecuted=true</script>\n\n![模型图片](https://example.org/image.png)';
    await page.route('**/api/ai/ask',route=>route.fulfill({json:{answer:modelAnswer,status:'ok',remaining_rounds:2,sources:[{name:'本地样例资料',positions:['第 1 段']}],notice:'资料线索不代表逐条核验。'}}));
    await page.goto(origin+'/#page/home');await page.waitForSelector('#ai-question:not([disabled])');
    await page.fill('#ai-question','请解释 **原文措辞**');await page.click('#ai-send');
    const answer = page.locator('.ai-message[data-role="assistant"]');
    await answer.locator('table').waitFor();
    assert.equal(await answer.locator('h2').textContent(),'技术概念');
    assert.equal(await answer.locator('ol li').count(),2);assert.equal(await answer.locator('blockquote').count(),1);
    assert.equal(await answer.locator('script,img').count(),0);assert.equal(await page.evaluate(()=>Boolean(window.modelScriptExecuted)),false);
    assert.equal(await answer.locator('pre code').count(),1);assert.equal(await answer.locator('a').getAttribute('rel'),'noopener noreferrer');
    assert.match(await answer.locator('.ai-message-foot').textContent(),/2 轮/);
    await answer.locator('summary').click();assert.match(await answer.locator('.ai-source-list').textContent(),/本地样例资料/);
    assert.equal(await page.locator('.ai-message[data-role="user"] strong').count(),0);
    assert.match(await page.locator('.ai-message[data-role="user"]').textContent(),/\*\*原文措辞\*\*/);
    for (const width of [1440,820,390,320]) {
      await page.setViewportSize({width,height:900});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'AI Markdown overflow at '+width);
      const codeLayout = await answer.locator('pre').evaluate(el=>({scroll:el.scrollWidth,width:el.clientWidth,whiteSpace:getComputedStyle(el).whiteSpace,codeWhiteSpace:getComputedStyle(el.firstChild).whiteSpace}));
      assert.equal(codeLayout.scroll>codeLayout.width,true,'Code scrolls within answer: '+JSON.stringify(codeLayout));
      await page.screenshot({path:path.join(out,'ai-markdown-'+width+'.png'),fullPage:true});
    }
    await page.fill('#ai-question','请继续说明');await page.click('#ai-send');
    await page.waitForFunction(()=>document.querySelectorAll('.ai-message[data-role="assistant"]').length===2);
    report.push('AI answers: real submit/follow-up flow, Markdown tables/lists/quotes/code/links, literal user input, sources and rounds retained, safe images/HTML, four responsive widths');
    await page.goto(origin+'/assets/research.html');
    await page.locator('[data-mode="knowledge"]').click();
    await page.waitForSelector('#question:not([disabled])');
    await page.fill('#question','研究助手知识问答格式验证');await page.locator('#composer button[type="submit"]').click();
    await page.waitForSelector('.research-answer table');
    assert.equal(await page.locator('.research-answer h2').textContent(),'技术概念');
    assert.equal(await page.locator('.research-answer img,.research-answer script').count(),0);
    await page.locator('.message .sources summary').click();assert.match(await page.locator('.message .sources').textContent(),/本地样例资料/);
    for (const width of [1440,820,390]) {
      await page.setViewportSize({width,height:900});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'Research answer overflow at '+width);
      assert.equal(await page.locator('.research-answer pre').evaluate(el=>el.scrollWidth>el.clientWidth),true);
      await page.screenshot({path:path.join(out,'research-markdown-'+width+'.png')});
    }
    await page.reload();await page.waitForSelector('.research-answer table');
    await page.locator('[data-mode="papers"]').click();assert.equal(await page.locator('.research-answer').count(),0);
    await page.locator('[data-mode="knowledge"]').click();await page.waitForSelector('.research-answer table');
    report.push('Research assistant knowledge answers: shared Markdown, sources, responsive layout, saved-history refresh and mode isolation');
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(out,'checks.json'),JSON.stringify({report,errors},null,2));console.log(report.join('\n'));
    await context.close();
  } finally {await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
