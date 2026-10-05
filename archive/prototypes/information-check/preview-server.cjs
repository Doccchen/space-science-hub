const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const files = {'/':'index.html','/index.html':'index.html','/app.css':'app.css','/app.js':'app.js'};
const types = {'.html':'text/html; charset=utf-8','.css':'text/css; charset=utf-8','.js':'text/javascript; charset=utf-8'};
http.createServer((req,res)=>{
 const route=new URL(req.url,'http://localhost').pathname;
 if(!files[route]){res.writeHead(404);res.end('Not found');return;}
 fs.readFile(path.join(__dirname,files[route]),(error,data)=>{
  if(error){res.writeHead(500);res.end('Unable to read file');return;}
  res.writeHead(200,{'Content-Type':types[path.extname(files[route])],'Cache-Control':'no-store'});res.end(data);
 });
}).listen(4173,'127.0.0.1',()=>process.stdout.write('Preview ready: http://127.0.0.1:4173\n'));
