const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const source=fs.readFileSync('public/assets/site.js','utf8');
// Execute the real data-loading functions without the browser UI bootstrap.
const prefix=source.slice(0,source.indexOf('function setActive'));
const feeds=source.slice(source.indexOf('function mergeFeeds'),source.indexOf('function home'));
function harness(responses){
 const context=vm.createContext({URL,Date,AbortSignal,fetch:async url=>{
  const result=responses[url];if(result instanceof Error)throw result;
  return {ok:true,headers:{get:()=>null},json:async()=>result};
 },document:{addEventListener(){}},ticker(){},render(){},updateFeedStatus(){},updateSearchSources(){}});
 vm.runInContext(prefix+feeds,context);return context;
}
test('healthy API removes stale snapshot items and preserves full article',async()=>{
 const ctx=harness({'/api/news?category=all&limit=120':[{id:2,title:'Current',article:'Full article'}],'/news-data.json':[{id:1,title:'Removed'}]});
 await vm.runInContext('load()',ctx);
 assert.equal(vm.runInContext("S.items.filter(i=>i.id!=='nana-tribute').length",ctx),1);
 assert.equal(vm.runInContext("S.items.find(i=>i.id==='2').body",ctx),'Full article');
 assert.equal(vm.runInContext('S.mode',ctx),'api');
});
test('empty successful API clears previously cached stories',async()=>{
 const ctx=harness({'/api/news?category=all&limit=120':[],'/news-data.json':[{id:1,title:'Old'}]});
 vm.runInContext("S.items=[{id:'3',title:'Cached'}]",ctx);
 await vm.runInContext('load()',ctx);
 assert.equal(vm.runInContext("S.items.filter(i=>i.id!=='nana-tribute').length",ctx),0);
});
test('API outage serves snapshot with a non-live state',async()=>{
 const ctx=harness({'/api/news?category=all&limit=120':new Error('offline'),'/news-data.json':[{id:1,title:'Saved'}]});
 await vm.runInContext('load()',ctx);
 assert.equal(vm.runInContext("S.items.find(i=>i.id==='1').title",ctx),'Saved');
 assert.equal(vm.runInContext('S.mode',ctx),'snapshot');
});
test('out-of-order search responses cannot replace the newest query',async()=>{
 const elements={'#si':{value:'first'},'#sc':{textContent:''},'#sres':{innerHTML:''}};
 const pending=[];
 const context=vm.createContext({AbortController,window:{},$:(s)=>elements[s],get:()=>new Promise(resolve=>pending.push(resolve)),ENDPOINTS:{search:'/api/search'},S:{items:[]},norm:x=>x,inCat:()=>true,esc:String,articleHref:x=>'/'+x.id,ago:()=>'',doS(){}});
 vm.runInContext(source.slice(source.indexOf('let searchRequest='),source.indexOf('const __article=')),context);
 const old=vm.runInContext('doS()',context);elements['#si'].value='second';const current=vm.runInContext('doS()',context);
 pending[1]([{id:2,title:'Second result'}]);await current;
 pending[0]([{id:1,title:'First result'}]);await old;
 assert.match(elements['#sres'].innerHTML,/Second result/);
 assert.doesNotMatch(elements['#sres'].innerHTML,/First result/);
});

test('editorial homepage script is CSP compatible',()=>{
 const html=fs.readFileSync('public/index.html','utf8');
 const script=fs.readFileSync('public/assets/editorial-home.js','utf8');
 assert.doesNotMatch(html,/<script id="ph-v14-script">/);
 assert.match(html,/src="\/assets\/editorial-home\.js\?v=[a-z0-9]+"/);
 assert.match(script,/home=function\(c\)/);
 for(const removed of ['EXPLORE MORE','READER RESOURCES','Choose your desk.','Go to the original.','Read with context.']) assert.ok(!script.includes(removed),'unwanted homepage sidebar: '+removed);
 assert.doesNotMatch(script,/ph14-rail|enhanceHome/);
 assert.doesNotMatch(script,/FEED STATUS|Your news connection/);
 assert.doesNotMatch(script,/onerror=/);
});
test('service worker does not cache API, live snapshot or error responses',()=>{
 const sw=fs.readFileSync('public/service-worker.js','utf8');
 assert.match(sw,/politicshub-shell-v\d+/);
 assert.match(sw,/url\.pathname==="\/news-data\.json"/);
 assert.match(sw,/if\(response\.ok/);
});

test('Nana Patekar and Indian obituaries are India news, not Entertainment',()=>{
 const ctx=harness({'/api/news?category=all&limit=120':[],'/news-data.json':[]});
 assert.equal(vm.runInContext('typeof NANA_TRIBUTE',ctx),'undefined');
 assert.equal(vm.runInContext("newsCategory('entertainment','Nana Patekar dies at 75','')",ctx),'india');
 assert.equal(vm.runInContext("newsCategory('entertainment','Indian actor dies at 82','Bollywood mourns')",ctx),'india');
 assert.equal(vm.runInContext("newsCategory('entertainment','New Bollywood movie announced','')",ctx),'india');
 assert.equal(vm.runInContext("newsCategory('entertainment','Hollywood awards show','')",ctx),'world');
 assert.equal(vm.runInContext("newsCategory('entertainment','Film actor joins election campaign','')",ctx),'politics');
 assert.equal(vm.runInContext("inCat({category:'india'},'india')",ctx),true);
 assert.equal(vm.runInContext("inCat({category:'india'},'entertainment')",ctx),false);
});

test('Politics desk includes political India headlines without rewriting canonical story URLs',()=>{
 const ctx=harness({'/api/news?category=all&limit=120':[],'/news-data.json':[]});
 assert.equal(vm.runInContext("inCat({category:'india',title:'Three AAP MLAs join BJP in Punjab'},'politics')",ctx),true);
 assert.equal(vm.runInContext("inCat({category:'india',title:'New hospital opens in district'},'politics')",ctx),false);
 assert.equal(vm.runInContext("inCat({category:'world',title:'Congress meets in Europe'},'politics')",ctx),false);
 assert.equal(vm.runInContext("articleHref({id:'77',news_number:'8765',category:'india',title:'Three AAP MLAs join BJP in Punjab'})",ctx),'/india/8765');
});

test('Marathi publishers appear in Maharashtra view but preserve canonical India links',()=>{
 const ctx=harness({'/api/news?category=all&limit=120':[],'/news-data.json':[]});
 assert.equal(vm.runInContext("ck({category:'india',source_name:'TV9 Marathi - Maharashtra'})",ctx),'maharashtra');
 assert.equal(vm.runInContext("inCat({category:'india',source_name:'ABP Majha - Maharashtra'},'maharashtra')",ctx),true);
 assert.equal(vm.runInContext("inCat({category:'india',source_name:'ABP Majha - Maharashtra'},'india')",ctx),false);
 assert.equal(vm.runInContext("articleHref({id:'77',news_number:'8765',category:'india',source_name:'TV9 Marathi - Maharashtra'})",ctx),'/india/8765');
});
test('source snapshot supersedes stale browser cache and stays source-fed',async()=>{
 const ctx=harness({'/api/news?category=all&limit=120':new Error('database quota'),
  '/news-data.json':[{id:123,title:'Fresh source-linked story',category:'india'}]});
 vm.runInContext("S.items=[{id:'9999',title:'Stale cached story',category:'india'}]",ctx);
 await vm.runInContext('load()',ctx);
 assert.equal(vm.runInContext("S.items.some(i=>i.title==='Stale cached story')",ctx),false);
 assert.equal(vm.runInContext("S.items.some(i=>i.title==='Fresh source-linked story')",ctx),true);
 assert.equal(vm.runInContext('S.mode',ctx),'snapshot');
});

test('reader notices are quiet when stories are available and explain unavailable stories',()=>{
 assert.match(source,/if\(mode==='api'\|\|mode==='snapshot'\)\{box\?\.remove\(\);return\}/);
 assert.doesNotMatch(source,/SOURCE FEED|GitHub public news feed is active|Termux \+ GitHub delivery/);
 assert.match(source,/Connection unavailable\. Showing previously loaded stories/);
 assert.match(source,/Stories are temporarily unavailable\. Please try again/);
});

test('mobile page requests explicit web fonts with stable fallback',()=>{
 const css=fs.readFileSync('public/assets/site.css','utf8');
 assert.match(css,/fonts\.googleapis\.com/);
 assert.match(css,/Bricolage\+Grotesque/);
 assert.match(css,/--sans:'Inter',Arial,Helvetica,sans-serif/);
});

test('archive search loads beyond fifty results and filters category on the server',async()=>{
 const elements={'#si':{value:'India'},'#sc':{textContent:''},'#sres':{innerHTML:''},'#searchMore':{}};
 const urls=[];
 const context=vm.createContext({AbortController,window:{searchCat:'india'},$:(s)=>elements[s],get:async url=>{
  urls.push(url);const offset=Number(new URL(url,'https://example.com').searchParams.get('offset'));
  return Array.from({length:offset===0?50:12},(_,i)=>({id:offset+i+1,title:'Result '+(offset+i+1),category:'india'}));
 },ENDPOINTS:{search:'/api/search'},S:{items:[]},norm:x=>x,inCat:()=>true,esc:String,articleHref:x=>'/'+x.id,ago:()=>'',doS(){}});
 vm.runInContext(source.slice(source.indexOf('let searchRequest='),source.indexOf('const __article=')),context);
 await vm.runInContext('doS()',context);
 await vm.runInContext('doS(true)',context);
 assert.match(urls[1],/offset=50&category=india/);
 assert.equal((elements['#sres'].innerHTML.match(/class="sr"/g)||[]).length,62);
 assert.match(elements['#sres'].innerHTML,/Result 62/);
 assert.doesNotMatch(elements['#sres'].innerHTML,/id="searchMore"/);
});

test('archive search displays the server total rather than only the loaded page count',async()=>{
 const elements={'#si':{value:'exam'},'#sc':{textContent:''},'#sres':{innerHTML:''},'#searchMore':{}};
 const context=vm.createContext({AbortController,Number,window:{},$:(s)=>elements[s],get:async()=>{
  const rows=Array.from({length:50},(_,i)=>({id:String(i),title:'Official exam notice'}));rows.searchTotal=127;return rows;
 },ENDPOINTS:{search:'/api/search'},S:{items:[]},norm:x=>x,inCat:()=>true,esc:String,articleHref:x=>'/'+x.id,ago:()=>'',doS(){}});
 vm.runInContext(source.slice(source.indexOf('let searchRequest='),source.indexOf('const __article=')),context);
 await vm.runInContext('doS()',context);
 assert.match(elements['#sc'].textContent,/50 of 127/);
 assert.match(elements['#sres'].innerHTML,/searchMore/);
});
