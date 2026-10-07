const fs=require('node:fs');
const path=require('node:path');
const root=path.resolve(__dirname,'../..');
const uri=(file,mime)=>'data:'+mime+';base64,'+fs.readFileSync(file).toString('base64');
const selected=['space-propulsion-technology','spacecraft-attitude-orbit-control','fundamentals-of-aerodynamics','solid-rocket-motor-design'];
const catalog=JSON.parse(fs.readFileSync(path.join(root,'content/resources.json'),'utf8'));
const books=selected.map(id=>{const b=catalog.find(b=>b.id===id);if(!b)throw Error('Missing book '+id);return {...b,image:uri(path.join(root,'web/resource-covers',b.cover_asset),'image/jpeg')}});
let html=fs.readFileSync(path.join(__dirname,'preview.template.html'),'utf8')
 .replace('@@LOGO@@',uri(path.join(root,'web/brand.svg'),'image/svg+xml'))
 .replace('@@EARTH@@',uri(path.join(__dirname,'earthrise.jpg'),'image/jpeg'))
 .replace('@@BOOKS@@',JSON.stringify(books).replace(/</g,'\\u003c'));
if(/@@[A-Z]+@@/.test(html))throw Error('Unresolved asset');
const js=html.match(/<script>([\s\S]*?)<\/script>/)[1];
new (require('node:vm').Script)(js);
fs.writeFileSync(path.join(__dirname,'星知航-三种视觉方向.html'),html);
console.log('Built standalone preview; embedded logo, NASA image, and '+books.length+' real covers. JavaScript syntax passed.');
