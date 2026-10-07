const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const context = {window:{}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../web/news-state.js'),'utf8'),context);
const merge = context.window.NewsPresentation.mergeItem;
const list = {id:2,title:'中文列表标题',source_name:'来源',source_id:'cnsa',original_url:'https://example.org/2',
  published_at:'2026-10-06',lang:'zh',reading_mode:'full_text',summary:'合法摘要'};
const partial = merge(list,{id:2,lang:'zh',reading_mode:'full_text',summary:'更新摘要'});
assert.equal(partial.title,list.title);
assert.equal(partial.source_name,list.source_name);
assert.equal(partial.original_url,list.original_url);
assert.equal(partial.summary,'更新摘要');
assert.equal(list.summary,'合法摘要');
assert.equal(merge(list,{id:2,title:'',source_name:null}).title,list.title);
assert.equal(merge(list,{id:3,reading_mode:'unavailable'}),null);
assert.equal(merge(list,{id:2,reading_mode:'unavailable',summary:'不得泄露'}).summary,'');
assert.equal(merge(list,{id:2,reading_mode:'link_only'}).title,list.title);
console.log('News metadata merge regressions passed');
const preferences = new Map([['space-reduce-transparency','true'],['fixture-retained','keep']]);
const attributes = new Map([['data-reduce-transparency','true']]);
const themeContext = {window:{addEventListener(){}},localStorage:{removeItem(key){preferences.delete(key);}},
  document:{documentElement:{removeAttribute(key){attributes.delete(key);}},body:{dataset:{}},
    addEventListener(){},querySelectorAll(){return [{id:'news',classList:{contains(){return false;}}}];}}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../web/glass-theme.js'),'utf8'),themeContext);
assert.equal(preferences.has('space-reduce-transparency'),false);
assert.equal(preferences.get('fixture-retained'),'keep');
assert.equal(attributes.has('data-reduce-transparency'),false);
assert.equal(themeContext.document.body.dataset.themePage,'news');
console.log('Retired preference cleanup preserves other settings');
