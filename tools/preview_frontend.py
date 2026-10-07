"""Offline fixture server for news UI regressions; no production DB or provider calls."""
import json
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs,urlsplit

ROOT=Path(__file__).resolve().parent.parent
SOURCES=[{'id':'cnsa','name':'国家航天局（离线样本）','region':'domestic','publisher_kind':'agency','enabled':1},
         {'id':'nasa','name':'NASA（离线样本）','region':'international','publisher_kind':'agency','enabled':1},
         {'id':'esa','name':'ESA（离线样本）','region':'international','publisher_kind':'agency','enabled':1},
         {'id':'demo-company','name':'商业航天（离线样本）','region':'domestic','publisher_kind':'company','geographic_region':'asia','enabled':0}]
ARTICLES=[]
for identity in range(1,36):
    source=SOURCES[0 if identity<=15 else 1 if identity<=25 else 2 if identity<=30 else 3]
    ARTICLES.append({'id':identity,'title':('中文阅读回归示例 ' if identity<=15 else 'English reading fixture ')+str(identity),
      'source_id':source['id'],'source_name':source['name'],'region':source['region'],'publisher_kind':source['publisher_kind'],
      'geographic_region':source.get('geographic_region',''),'lang':'zh' if identity<=15 else 'en','source_enabled':source['enabled'],
      'published_at':'2026-10-06T08:00:00+00:00','original_url':'https://example.org/fixture/'+str(identity),
      'summary':'离线回归示例，非真实新闻。','reading_mode':'full_text' if identity<=25 else 'link_only','content_version':'fixture-v1'})


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send_json(self,value,status=200):
        data=json.dumps(value,ensure_ascii=False).encode();self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8');self.end_headers();self.wfile.write(data)
    def do_GET(self):
        url=urlsplit(self.path);q=parse_qs(url.query);path=url.path
        if path=='/api/news/sources':return self.send_json({'items':SOURCES,'geographic_regions':[{'id':'asia','name':'亚洲'}]})
        if path=='/api/news':
            rows=list(ARTICLES);category=q.get('category',[''])[0]
            if category=='domestic_agency':rows=[a for a in rows if a['publisher_kind']=='agency' and a['region']=='domestic']
            elif category=='international_agency':rows=[a for a in rows if a['publisher_kind']=='agency' and a['region']=='international']
            elif category=='commercial':rows=[a for a in rows if a['publisher_kind']=='company']
            for key in ('source','region','geographic_region'):
                if key in q:rows=[a for a in rows if a['source_id' if key=='source' else key]==q[key][0]]
            size=int(q.get('page_size',['20'])[0]);pages=(len(rows)+size-1)//size;page=min(max(1,int(q.get('page',['1'])[0])),max(1,pages))
            return self.send_json({'items':rows[(page-1)*size:page*size],'page':page,'page_size':size,'total_pages':pages,'total':len(rows),'snapshot':35})
        if path.startswith('/api/news/'):
            parts=path.split('/');identity=int(parts[3]);item=next((a for a in ARTICLES if a['id']==identity),None)
            if not item:return self.send_json({},404)
            if len(parts)==4:
                # Deliberately reduced detail shape exercises the readingchange merge seam.
                if identity==2:return self.send_json({'id':2,'lang':'zh','content_version':'fixture-v1'})
                return self.send_json(item)
            if parts[4]=='content':
                if identity==4:return self.send_json({},500)
                if identity==5:time.sleep(.5)
                link_only=identity==3 or identity>25
                return self.send_json({'reading_mode':'link_only' if link_only else 'full_text','read_scope':'link_only' if link_only else 'full_text',
                    'source_reading_policy':'link_only' if link_only else 'government_candidate','content_version':'fixture-v1',
                    'language':item['lang'],'credit':'离线回归样本','notes':'此内容仅用于前端测试，不是真实新闻。','assets':[],
                    'blocks':[] if link_only else [{'type':'paragraph','text':('中文长文阅读示例，检查字体、行距和关闭后的列表位置。' if identity<=15 else 'Offline English reading fixture for navigation and focus checks.')+' '+str(i),'block_id':'b'+str(i)} for i in range(30)]})
        if path=='/api/ai/status':return self.send_json({'enabled':False,'message':'离线回归页面 · 未连接百炼','history_retention_seconds':3600})
        if path=='/api/resources':return self.send_json({'items':[],'pages':0,'total':0,'categories':[]})
        file=ROOT/'web'/'index.html' if path=='/' else ROOT/'web'/path.removeprefix('/assets/')
        if not file.resolve().is_relative_to((ROOT/'web').resolve()) or not file.is_file():return self.send_json({},404)
        types={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.svg':'image/svg+xml'}
        data=file.read_bytes()
        if path=='/' and q.get('legacy_preference')==['1']:
            data=data.replace(b'<body>',b'<body><script>localStorage.setItem("space-reduce-transparency","true");localStorage.setItem("fixture-retained","keep");</script>')
        self.send_response(200);self.send_header('Content-Type',types.get(file.suffix,'application/octet-stream'));self.end_headers();self.wfile.write(data)


if __name__=='__main__':
    print('Offline frontend fixtures: http://127.0.0.1:8095 (no DB / no paid calls)',flush=True)
    ThreadingHTTPServer(('127.0.0.1',8095),Handler).serve_forever()
