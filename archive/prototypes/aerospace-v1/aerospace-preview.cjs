const http=require('node:http');
const fs=require('node:fs');
const path=require('node:path');
const routes={'/':'aerospace.html','/aerospace.html':'aerospace.html','/aerospace.css':'aerospace.css','/aerospace.js':'aerospace.js'};
const types={'.html':'text/html; charset=utf-8','.css':'text/css; charset=utf-8','.js':'text/javascript; charset=utf-8'};
http.createServer((req,res)=>{const file=routes[new URL(req.url,'http://localhost').pathname];if(!file){res.writeHead(404);res.end('Not found');return;}fs.readFile(path.join(__dirname,file),(error,data)=>{if(error){res.writeHead(500);res.end('Unable to read file');return;}res.writeHead(200,{'Content-Type':types[path.extname(file)],'Cache-Control':'no-store'});res.end(data);});}).listen(4174,'127.0.0.1',()=>process.stdout.write('Aerospace preview ready: http://127.0.0.1:4174\n'));
