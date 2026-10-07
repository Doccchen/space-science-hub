"""Build a standalone view of the actual frontend; API fixtures never leave this preview."""
import base64
import json
import re
from pathlib import Path

from tools.preview_frontend import ARTICLES, SOURCES

ROOT = Path(__file__).resolve().parent.parent


def data_url(path):
    types = {'.jpg': 'image/jpeg', '.svg': 'image/svg+xml', '.png': 'image/png'}
    return 'data:' + types[path.suffix] + ';base64,' + base64.b64encode(path.read_bytes()).decode()


def main():
    web = ROOT / 'web'
    html = (web / 'index.html').read_text(encoding='utf-8')
    catalog = [item for item in json.loads((ROOT / 'content/resources.json').read_text(encoding='utf-8')) if item.get('published')]
    for item in catalog:
        item['cover_url'] = data_url(web / 'resource-covers' / item['cover_asset']) if item.get('cover_asset') else None
        item['download_url'] = '/api/resources/' + item['id'] + '/download'
    payload = json.dumps({'articles': ARTICLES, 'sources': SOURCES, 'catalog': catalog}, ensure_ascii=False).replace('<', '\\u003c')
    script = '''<script>
const previewData=PAYLOAD;
window.fetch=async input=>{
 const u=new URL(String(input),'https://offline.invalid');const q=u.searchParams;let result;
 if(u.pathname==='/api/news/sources')result={items:previewData.sources,geographic_regions:[{id:'asia',name:'亚洲'}]};
 else if(u.pathname==='/api/news'){
  const c=q.get('category');let rows=previewData.articles.filter(a=>!c||(c==='commercial'?a.publisher_kind==='company':a.publisher_kind==='agency'&&a.region===(c==='domestic_agency'?'domestic':'international')));
  for(const key of ['source','region','geographic_region'])if(q.get(key))rows=rows.filter(a=>a[key==='source'?'source_id':key]===q.get(key));
  const size=Number(q.get('page_size')||20),pages=Math.ceil(rows.length/size),page=Math.min(Math.max(1,Number(q.get('page')||1)),Math.max(1,pages));
  result={items:rows.slice((page-1)*size,page*size),page,page_size:size,total_pages:pages,total:rows.length,snapshot:35};
 }else if(u.pathname==='/api/resources'){
  const term=(q.get('q')||'').toLowerCase(),category=q.get('category');const rows=previewData.catalog.filter(b=>(!category||b.category===category)&&(b.title+' '+b.authors.join(' ')).toLowerCase().includes(term));
  const page=Number(q.get('page')||1),size=12;result={items:rows.slice((page-1)*size,page*size),pages:Math.ceil(rows.length/size),total:rows.length,categories:[...new Set(previewData.catalog.map(b=>b.category))].sort()};
 }else if(u.pathname==='/api/ai/status')result={enabled:false,message:'离线前端预览 · 未连接百炼',history_retention_seconds:3600};
 else if(/^\\/api\\/news\\/\\d+$/.test(u.pathname))result=previewData.articles.find(a=>a.id===Number(u.pathname.split('/')[3]));
 else if(/^\\/api\\/news\\/\\d+\\/content$/.test(u.pathname))result={reading_mode:'full_text',read_scope:'full_text',language:'zh',credit:'离线样本',notes:'仅展示排版，不是真实新闻。',assets:[],blocks:[{type:'paragraph',text:'这是用于查看正式前端排版的离线样本。正式网站继续显示原有新闻正文与来源。',block_id:'preview'}]};
 return {ok:!!result,status:result?200:404,json:async()=>result||{error:{message:'离线预览未连接此功能。'}}};
};
document.addEventListener('click',e=>{const link=e.target.closest('a');if(link&&link.getAttribute('href')?.startsWith('/api/resources/')){e.preventDefault();const t=document.getElementById('toast');t.textContent='离线预览不下载文件，请在正式网站下载资料。';t.classList.remove('hidden');setTimeout(()=>t.classList.add('hidden'),3000)}});
</script>'''.replace('PAYLOAD', payload)
    html = re.sub(r'<link rel="stylesheet" href="/assets/([^"?]+)(?:\?[^\"]*)?">', lambda m: '<style>' + (web / m[1]).read_text(encoding='utf-8') + '</style>', html)
    html = re.sub(r'<link rel="preload"[^>]+>', '', html)
    html = html.replace('<body class="editorial-ui">', '<body class="editorial-ui"><div style="padding:8px 20px;background:#10233f;color:#f3f1ea;font-size:12px;text-align:center">新版正式前端 · 离线预览 · 新闻为测试样本，资料为现有目录，未连接百炼</div>' + script)
    html = re.sub(r'<script src="/assets/([^"?]+)(?:\?[^\"]*)?"></script>', lambda m: '<script>' + (web / m[1]).read_text(encoding='utf-8') + '</script>', html)
    html = re.sub(r'/assets/(brand\.svg|favicon\.svg|earthrise\.jpg|history-[a-z0-9]+\.(?:jpg|png))(?:\?[^\" ]*)?', lambda m: data_url(web / m[1]), html)
    output = ROOT / 'artifacts/magazine-preview/星知航-新版正式前端预览.html'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding='utf-8')
    output.with_name('轨道志-新版正式前端预览.html').write_text(html, encoding='utf-8')
    output.with_name('知航-新版正式前端预览.html').write_text(html, encoding='utf-8')
    print(output)


if __name__ == '__main__':
    main()
