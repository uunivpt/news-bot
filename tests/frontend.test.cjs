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
 },document:{addEventListener(){}},ticker(){},render(){},updateFeedStatus(){}});
 vm.runInContext(prefix+feeds,context);return context;
}
test('healthy API removes stale snapshot items and preserves full article',async()=>{
 const ctx=harness({'/api/news?category=all&limit=120':[{id:2,title:'Current',article:'Full article'}],'/news-data.json':[{id:1,title:'Removed'}]});
 await vm.runInContext('load()',ctx);
 assert.equal(vm.runInContext('S.items.length',ctx),1);
 assert.equal(vm.runInContext('S.items[0].body',ctx),'Full article');
 assert.equal(vm.runInContext('S.mode',ctx),'api');
});
test('empty successful API clears previously cached stories',async()=>{
 const ctx=harness({'/api/news?category=all&limit=120':[],'/news-data.json':[{id:1,title:'Old'}]});
 vm.runInContext("S.items=[{id:'3',title:'Cached'}]",ctx);
 await vm.runInContext('load()',ctx);
 assert.equal(vm.runInContext('S.items.length',ctx),0);
});
test('API outage serves snapshot with a non-live state',async()=>{
 const ctx=harness({'/api/news?category=all&limit=120':new Error('offline'),'/news-data.json':[{id:1,title:'Saved'}]});
 await vm.runInContext('load()',ctx);
 assert.equal(vm.runInContext('S.items[0].title',ctx),'Saved');
 assert.equal(vm.runInContext('S.mode',ctx),'snapshot');
});
test('out-of-order search responses cannot replace the newest query',async()=>{
 const elements={'#si':{value:'first'},'#sc':{textContent:''},'#sres':{innerHTML:''}};
 const pending=[];
 const context=vm.createContext({window:{},$:(s)=>elements[s],get:()=>new Promise(resolve=>pending.push(resolve)),ENDPOINTS:{search:'/api/search'},S:{items:[]},norm:x=>x,inCat:()=>true,esc:String,articleHref:x=>'/'+x.id,ago:()=>'',doS(){}});
 vm.runInContext(source.slice(source.indexOf('let searchRequest='),source.indexOf('const __article=')),context);
 const old=vm.runInContext('doS()',context);elements['#si'].value='second';const current=vm.runInContext('doS()',context);
 pending[1]([{id:2,title:'Second result'}]);await current;
 pending[0]([{id:1,title:'First result'}]);await old;
 assert.match(elements['#sres'].innerHTML,/Second result/);
 assert.doesNotMatch(elements['#sres'].innerHTML,/First result/);
});
