const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const script = fs.readFileSync('public/assets/story-page.js','utf8');
function visit(path, hidden=false){
 const calls=[]; let onVisible;
 const context={
   location:{pathname:path},
   document:{hidden,addEventListener:(name,callback)=>{if(name==='visibilitychange')onVisible=callback;}},
   navigator:{sendBeacon:(url)=>{calls.push(url);return true;}},
   Blob:class Blob {},
 };
 vm.runInNewContext(script,context);
 return {calls,show(){context.document.hidden=false;onVisible?.();}};
}
test('canonical numeric article pages record a single view',()=>{
 for(const desk of ['india','world','politics','business','technology','sports','entertainment','science','health','hindi','maharashtra']){
   const visitResult=visit('/'+desk+'/617958005290');
   assert.deepEqual(visitResult.calls,['/api/news/617958005290/view'],desk);
 }
});
test('legacy slugged articles work; non-stories are ignored',()=>{
 assert.deepEqual(visit('/india/123-news-title').calls,['/api/news/123/view']);
 for(const path of ['/','/admin/','/privacy.html','/india/','/india/not-a-number','/india/42/other'])
   assert.deepEqual(visit(path).calls,[],path);
});
test('hidden tab waits for visibility and records only once',()=>{
 const result=visit('/politics/617958005290',true);
 assert.deepEqual(result.calls,[]);
 result.show();result.show();
 assert.deepEqual(result.calls,['/api/news/617958005290/view']);
});
test('retired duplicate HTML has a permanent compatibility redirect',()=>{
 const config=JSON.parse(fs.readFileSync('vercel.json','utf8'));
 assert.ok(config.redirects.some(r=>r.source==='/story.html'&&r.destination==='/article.html'&&r.permanent));
 assert.equal(fs.existsSync('public/story.html'),false);
 assert.ok(fs.existsSync('public/article.html'));
 for(const desk of ['business','technology','sports','entertainment','science','health']){
   assert.equal(config.rewrites.some(r=>r.source==='/'+desk||r.source==='/'+desk+'/'),false,desk);
   assert.ok(config.rewrites.some(r=>r.source==='/'+desk+'/:story'),desk);
 }
});
