const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const source=fs.readFileSync('public/admin.js','utf8');
const functions=source.slice(source.indexOf('function newsNumberInput('),source.indexOf('function updateSelection('));
const article={id:17484337268349,news_number:'617958005290',title:'Historical story',summary:'Saved summary',article:'Saved full text',category:'india',published_at_iso:'2026-10-01T10:00:00Z'};
function harness(respond,mode='live') {
 const requests=[],renders=[],notices=[];
 const elements={search:{value:article.news_number},newsList:{setAttribute(){},removeAttribute(){}},newsScope:{textContent:''},category:{value:'world'},source:{value:'Another publisher'},status:{value:'pending'},review:{value:'needs_review'},sort:{value:'newest'}};
 const context=vm.createContext({AbortController,URL,URLSearchParams,Date,Number,String,encodeURIComponent,
  workspace:{mode,access:{read_only:mode==='snapshot'}},newsSequence:0,newsController:null,pageNumber:1,selected:new Set(),queue:'quality',
  $:id=>elements[id],api:async(url,options)=>{requests.push(url);return respond(url,options);},
  renderNews:(rows,total)=>renders.push({rows:rows.map(r=>({...r})),total}),notice:(message)=>notices.push(message),filteredSnapshot:()=>[]});
 vm.runInContext(functions,context);return {context,requests,renders,elements,notices};
}
test('number finds a public historical article when the old phone has no private copy',async()=>{
 const h=harness(async url=>{if(url.startsWith('/api/news/'))return article;throw Object.assign(new Error('not found'),{status:404});});
 assert.equal(await vm.runInContext('loadNews(true)',h.context),true);
 assert.equal(h.renders[0].rows[0].news_number,article.news_number);
 assert.equal(h.renders[0].total,1);
 assert.equal(h.renders[0].rows[0].archived,true);
 assert.equal(h.requests.some(url=>url.startsWith('/api/admin/stories')),false);
 assert.match(h.elements.newsScope.textContent,/Public article found/);
});
test('read-only snapshot search finds an article outside the 200-row dashboard',async()=>{
 const h=harness(async()=>article,'snapshot');
 await vm.runInContext('loadNews(true)',h.context);
 assert.deepEqual(h.requests,['/api/news/'+article.news_number]);
 assert.equal(h.renders[0].rows[0].id,article.id);
 assert.match(h.elements.newsScope.textContent,/filters do not hide/);
});
test('existing private copy is editable without relying on numeric queue support',async()=>{
 const h=harness(async url=>url.startsWith('/api/news/')?article:{id:article.id,status:'pending',title:'Private edited headline',summary:'Draft',revision:'rev1'});
 await vm.runInContext('loadNews(true)',h.context);
 assert.equal(h.renders.at(-1).rows[0].archived,false);
 assert.equal(h.renders.at(-1).rows[0].status,'pending');
 assert.equal(h.renders.at(-1).rows[0].news_number,article.news_number);
});
test('404 public number lookup falls back to authenticated private queue search',async()=>{
 const h=harness(async url=>{if(url.startsWith('/api/news/'))throw Object.assign(new Error('not found'),{status:404});return {stories:[{id:10}],total:1};});
 await vm.runInContext('loadNews(true)',h.context);
 assert.ok(h.requests[1].startsWith('/api/admin/stories?'));
 assert.equal(h.renders[0].rows[0].id,10);
});
test('a slow previous numeric search cannot replace a newer result',async()=>{
 let finish;
 const h=harness(url=>url.endsWith(article.news_number)?new Promise(resolve=>finish=resolve):Promise.resolve({...article,id:22,news_number:'123456789012'}),'snapshot');
 const first=vm.runInContext('loadNews(true)',h.context);
 h.elements.search.value='123456789012';await vm.runInContext('loadNews(true)',h.context);
 finish(article);await first;
 assert.equal(h.renders.length,1);assert.equal(h.renders[0].rows[0].id,22);
});
test('number parser accepts displayed labels and copied article URLs',()=>{
 const h=harness(async()=>article);
 for(const value of ['617958005290','#617958005290','News No. 617958005290','https://www.politicshub.in/india/617958005290']) {
  h.context.input=value;assert.equal(vm.runInContext('newsNumberInput(input)',h.context),article.news_number);
 }
 h.context.input='daily political news';assert.equal(vm.runInContext('newsNumberInput(input)',h.context),'');
});
