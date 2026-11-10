const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const source=fs.readFileSync('public/admin.js','utf8');

function publicationHarness(result, refresh=true) {
  const requests=[], notices=[], renders=[];
  const elements={status:{value:'all'},review:{value:'all'}};
  const story={id:44,status:'pending',fact_check_status:'pending',revision:'copy-revision'};
  const context=vm.createContext({
    workspace:{access:{read_only:false},stats:{pending:1,published:0}},
    rows:[story],visibleRows:[{...story}],selected:new Set([44]),pageTotal:1,
    mutationBusy:false,sessionVersion:1,deliveryController:null,currentView:'news',queue:'all',Promise,
    $:id=>elements[id],
    action:async(url,body)=>{requests.push({url,body});return typeof result==='function'?result():result;},
    notice:(message,type)=>notices.push({message,type}),
    applyCapabilities(){},renderNews:(rows,total)=>renders.push({rows,total}),
    loadOverview:async()=>refresh?{mode:'live'}:null,
    loadNews:async()=>refresh,
    prompt:()=>{throw new Error('No publication prompt is permitted');},
    confirmAction:()=>{throw new Error('No publication confirmation is permitted');}
  });
  vm.runInContext(source.slice(source.indexOf('function markPublished('),source.indexOf('async function bulkAction(')),context);
  return {context,requests,notices,renders,elements};
}

test('verify publishes immediately using one authenticated action and no dialog',async()=>{
  const h=publicationHarness({ok:true,id:44,status:'published'});
  await vm.runInContext("newsAction('approve',44)",h.context);
  assert.equal(h.requests.length,1);
  assert.equal(h.requests[0].url,'/api/news/44/approve');
  assert.equal(h.requests[0].body.revision,'copy-revision');
  assert.deepEqual(Object.keys(h.requests[0].body),['revision']);
  assert.equal(h.context.visibleRows[0].status,'published');
  assert.equal(h.context.workspace.stats.pending,0);
  assert.equal(h.context.workspace.stats.published,1);
  assert.equal(h.context.selected.size,0);
  assert.equal(h.notices[0].message,'Story published.');
});

test('successful publication stays successful when the following refresh fails',async()=>{
  const h=publicationHarness({ok:true,id:44,status:'published'},false);
  await vm.runInContext("newsAction('approve',44)",h.context);
  assert.equal(h.requests.length,1);
  assert.equal(h.context.visibleRows[0].status,'published');
  assert.match(h.notices.at(-1).message,/published.*could not be refreshed/i);
  assert.equal(h.notices.at(-1).type,'warn');
});

test('publication cannot be double-clicked or reported without server confirmation',async()=>{
  let finish;
  const h=publicationHarness(()=>new Promise(resolve=>{finish=resolve;}));
  const first=vm.runInContext("newsAction('approve',44)",h.context);
  await vm.runInContext("newsAction('approve',44)",h.context);
  assert.equal(h.requests.length,1);
  finish({ok:true,id:44,status:'pending'}); await first;
  assert.equal(h.context.visibleRows[0].status,'pending');
  assert.match(h.notices.at(-1).message,/not confirmed/);
  assert.equal(h.context.mutationBusy,false);
});

test('legacy publish button uses the same one-step approval endpoint',async()=>{
  const h=publicationHarness({ok:true,id:44,status:'published'});
  await vm.runInContext("newsAction('publish',44)",h.context);
  assert.equal(h.requests[0].url,'/api/news/44/approve');
});

test('publication reports website sync status without claiming a queued article is live',async()=>{
  for (const [state,expected] of [['queued',/Checking that the story is visible/],['verifying',/Checking that the story is visible/],
                                ['not_configured',/sync is not configured/],
                                ['failed',/sync failed; publication is saved/],
                                ['synced',/published on the website/]]) {
    const h=publicationHarness({ok:true,id:44,status:'published',public_delivery:{state}});
    await vm.runInContext("newsAction('approve',44)",h.context);
    assert.match(h.notices[0].message,expected);
    if (state!=='synced') assert.doesNotMatch(h.notices[0].message,/published on the website/);
  }
  const h=publicationHarness({ok:true,id:44,status:'published',public_delivery:{state:'queued',configured:false}});
  await vm.runInContext("newsAction('approve',44)",h.context);
  assert.match(h.notices[0].message,/sync is not configured/);
});

test('published rows leave pending-only results immediately',async()=>{
  const h=publicationHarness({ok:true,id:44,status:'published'});
  h.elements.status.value='pending';
  await vm.runInContext("newsAction('approve',44)",h.context);
  assert.equal(h.renders[0].rows.length,0);
  assert.equal(h.renders[0].total,0);
});

test('all pending rows expose Verify and publish, including previously reviewed drafts',()=>{
  const context=vm.createContext({workspace:{access:{read_only:false}},Number,can:()=>true});
  vm.runInContext(source.slice(source.indexOf('function storyActions('),source.indexOf('function renderNews(')),context);
  const html=vm.runInContext("storyActions({id:44,status:'pending',article_available:false,fact_check_status:'reviewed'})",context);
  assert.match(html,/Verify &amp; publish/);
  assert.match(html,/data-news="approve"/);
  assert.doesNotMatch(html,/data-news="publish"/);
});

test('phone-published stories can be promoted and checked again without a new article',()=>{
  const context=vm.createContext({workspace:{access:{read_only:false}},Number,can:()=>true});
  vm.runInContext(source.slice(source.indexOf('function storyActions('),source.indexOf('function renderNews(')),context);
  const html=vm.runInContext("storyActions({id:44,status:'published',article_available:true})",context);
  assert.match(html,/Make main news \/ check website/);
  assert.match(html,/data-news="approve" data-id="44"/);
  assert.match(html,/data-permission="news.publish"/);
});

test('a fresh post-write workspace response cannot be replaced by an older refresh',async()=>{
  const deferred=[];
  const nodes={refresh:{disabled:false},shell:{classList:{contains:()=>false}},
    connectionBadge:{},workspaceBanner:{classList:{remove(){}}}};
  const context=vm.createContext({AbortController,sessionVersion:1,workspaceSequence:0,
    workspacePromise:null,workspaceController:null,workspace:{version:'initial'},
    $:id=>nodes[id],notice(){},renderWorkspace(){},
    api:(_url,options)=>new Promise(resolve=>deferred.push({resolve,signal:options.signal}))});
  vm.runInContext(source.slice(source.indexOf('async function loadOverview('),source.indexOf('function filteredSnapshot(')),context);
  const old=vm.runInContext('loadOverview()',context);
  const fresh=vm.runInContext('loadOverview(true,{fresh:true})',context);
  assert.equal(deferred[0].signal.aborted,true);
  deferred[1].resolve({version:'after publication'}); await fresh;
  deferred[0].resolve({version:'before publication'}); await old;
  assert.equal(context.workspace.version,'after publication');
  assert.equal(nodes.refresh.disabled,false);
});

function installBulk(h) {
  vm.runInContext(source.slice(source.indexOf('async function bulkAction('),source.indexOf('async function inspectStory(')),h.context);
}
test('explicit bulk verify publishes selected stories sequentially with no questions',async()=>{
  const h=publicationHarness({ok:true,status:'published'});
  h.context.visibleRows.push({id:45,status:'pending'});
  h.context.rows.push({id:45,status:'pending'});
  h.context.selected.add(45);
  h.context.workspace.stats.pending=2;
  installBulk(h);
  await vm.runInContext("bulkAction('approve')",h.context);
  assert.deepEqual(h.requests.map(r=>r.url),['/api/news/44/approve','/api/news/45/approve']);
  assert.equal(h.context.workspace.stats.pending,0);
  assert.equal(h.context.workspace.stats.published,2);
  assert.equal(h.context.selected.size,0);
  assert.match(h.notices.at(-1).message,/2 stories published/);
});
test('bulk publication stops at failure and preserves the successful first story',async()=>{
  let attempt=0;
  const h=publicationHarness(()=>{if (++attempt===2) throw new Error('Story has no title');return {ok:true,status:'published'};});
  for (const id of [45,46]) {
    h.context.visibleRows.push({id,status:'pending'});
    h.context.rows.push({id,status:'pending'});
    h.context.selected.add(id);
  }
  installBulk(h);
  await vm.runInContext("bulkAction('approve')",h.context);
  assert.equal(h.requests.length,2);
  assert.equal(h.context.visibleRows[0].status,'published');
  assert.equal(h.context.visibleRows[1].status,'pending');
  assert.deepEqual(Array.from(h.context.selected),[45,46]);
  assert.match(h.notices.at(-1).message,/1 story published.*Stopped: Story has no title/);
});

function deliveryHarness(response) {
  let elapsed=0;
  const reads=[];
  const context=vm.createContext({AbortController,AbortSignal,sessionVersion:1,deliveryController:null,
    Date:{now:()=>elapsed},setTimeout:callback=>{elapsed+=2000;callback();},
    api:async url=>{reads.push(url);return typeof response==='function'?response(context):response;}});
  vm.runInContext(source.slice(source.indexOf('async function waitForPublicationDelivery('),source.indexOf('function showPublicationNotice(')),context);
  return {context,reads,elapsed:()=>elapsed};
}
test('hosted publication confirmation never polls the phone delivery queue',async()=>{
  const h=deliveryHarness(()=>{throw new Error('A synced hosted publication must not poll');});
  const result=await vm.runInContext("waitForPublicationDelivery(44,{ok:true,status:'published',public_delivery:{state:'synced',configured:true,mode:'hosted',public_url:'https://www.politicshub.in/india/44'}},1)",h.context);
  assert.deepEqual(h.reads,[]);
  assert.equal(result.public_delivery.mode,'hosted');
  assert.equal(result.public_delivery.public_url,'https://www.politicshub.in/india/44');
});
test('publication delivery polls read-only status and preserves the versioned public URL',async()=>{
  const h=deliveryHarness({state:'synced',public_url:'https://www.politicshub.in/india/44-story?v=abc'});
  const result=await vm.runInContext("waitForPublicationDelivery(44,{ok:true,status:'published',public_delivery:{state:'queued',configured:true}},1)",h.context);
  assert.deepEqual(h.reads,['/api/admin/story/44/delivery']);
  assert.equal(result.public_delivery.state,'synced');
  assert.match(result.public_delivery.public_url,/\?v=abc$/);
});
test('delivery status waiting is bounded and never repeats publication',async()=>{
  const h=deliveryHarness({state:'queued'});
  const result=await vm.runInContext("waitForPublicationDelivery(44,{ok:true,status:'published',public_delivery:{state:'queued',configured:true}},1)",h.context);
  assert.equal(result.status,'published');
  assert.equal(result.public_delivery.state,'queued');
  assert.ok(h.elapsed()<=20000);
  assert.ok(h.reads.every(url=>url.endsWith('/delivery')));
});
test('logout stops delivery polling before another status request',async()=>{
  const h=deliveryHarness(context=>{context.sessionVersion=2;return {state:'queued'};});
  await vm.runInContext("waitForPublicationDelivery(44,{ok:true,status:'published',public_delivery:{state:'queued',configured:true}},1)",h.context);
  assert.equal(h.reads.length,1);
  assert.equal(h.context.deliveryController,null);
});
