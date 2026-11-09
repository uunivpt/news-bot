const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const source=fs.readFileSync('public/admin.js','utf8');
const rendering=source.slice(source.indexOf('function renderSources('),source.indexOf('function telemetryAvailable('));
const options=source.slice(source.indexOf('function sourceOptions('),source.indexOf('async function loadOverview('));
const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
function harness(inventory,mode='live') {
  const elements=new Map();
  const workspace={mode,coverage:{sample_size:200,sources:[{name:'Recent sample only',count:200}],categories:[{name:'world',count:200}],quality:[]}};
  if(inventory)workspace.source_inventory=inventory;
  const context=vm.createContext({workspace,
    $:id=>{if(!elements.has(id))elements.set(id,{innerHTML:'',textContent:'',value:'',classList:{toggle(){}}});return elements.get(id);},
    arr:value=>Array.isArray(value)?value:[],esc,number:value=>value==null?'—':String(value),date:value=>'DATE '+value,
    safeUrl:value=>{try{const url=new URL(value);return ['http:','https:'].includes(url.protocol)?url.href:'';}catch{return '';}},
    metric:(label,value,detail)=>`${label}:${value};${detail}\n`,
    barChart:(items,total)=>JSON.stringify({items,total}),empty:(title,message)=>`${title}: ${message}`,
  });
  vm.runInContext(rendering+options,context);
  return {context,elements,workspace,render:()=>vm.runInContext('renderSources()',context)};
}
function inventory() {
  return {scope:'database',total_stories:454,configured_count:3,represented_count:2,categories_count:2,errors:[],items:[
    {name:'TV9 Marathi',category:'maharashtra',kind:'rss',enabled:true,configured:true,story_count:0,collection_status:'awaiting_collection',feed_url:'https://tv9marathi.com/feed'},
    {name:'ABP माझा',category:'maharashtra',kind:'rss',enabled:true,configured:true,story_count:10,collection_status:'failed',last_error:'HTTP 503',latest_collected_at:'2026-11-01T00:00:00Z'},
    {name:'The Hindu',category:'india',kind:'rss',enabled:true,configured:true,story_count:444,collection_status:'healthy',last_success_at:'2026-11-02T00:00:00Z'},
  ]};
}
test('all configured publishers and full database counts replace the recent sample',()=>{
  const h=harness(inventory());h.render();
  const table=h.elements.get('sourceTable').innerHTML;
  assert.match(table,/TV9 Marathi/);assert.match(table,/ABP माझा/);assert.match(table,/The Hindu/);
  assert.match(table,/Awaiting first collection/);assert.match(table,/Collection failed/);assert.match(table,/HTTP 503/);
  assert.match(table,/Fetch succeeded/);assert.match(table,/DATE 2026-11-01/);
  assert.match(h.elements.get('sourceMetrics').innerHTML,/Stored reports:454;Entire database/);
  const chart=JSON.parse(h.elements.get('sourceChart').innerHTML);
  assert.equal(chart.total,454);assert.equal(chart.items[0].name,'The Hindu');assert.equal(chart.items[0].count,444);
  assert.doesNotMatch(table,/Recent sample only/);
  assert.doesNotMatch(table,/data-source-filter="TV9 Marathi"/);
  assert.match(table,/data-source-filter="ABP माझा"/);
  assert.match(h.elements.get('qualityScope').textContent,/200 loaded stories/);
  assert.match(h.elements.get('sourceScope').textContent,/3 of 3 publishers/);
});
test('publisher search includes zero-count names, Marathi text and desk metadata',()=>{
  const h=harness(inventory());h.render();
  h.elements.get('sourceSearch').value='TV9';h.render();
  assert.match(h.elements.get('sourceTable').innerHTML,/TV9 Marathi/);
  assert.doesNotMatch(h.elements.get('sourceTable').innerHTML,/The Hindu/);
  assert.match(h.elements.get('sourceScope').textContent,/1 of 3 publishers/);
  h.elements.get('sourceSearch').value='माझा';h.render();
  assert.match(h.elements.get('sourceTable').innerHTML,/ABP माझा/);
  h.elements.get('sourceSearch').value='maharashtra';h.render();
  assert.match(h.elements.get('sourceScope').textContent,/2 of 3 publishers/);
  h.elements.get('sourceSearch').value='absent publisher';h.render();
  assert.match(h.elements.get('sourceTable').innerHTML,/No matching publishers/);
});
test('Newsroom source options retain configured publishers absent from the latest 200',()=>{
  const h=harness(inventory());
  const names=vm.runInContext('sourceOptions().map(source=>source.name)',h.context);
  assert.ok(names.includes('TV9 Marathi'));assert.ok(names.includes('Recent sample only'));
});
test('snapshot counts never claim to check private collection health',()=>{
  const data=inventory();data.scope='snapshot';const h=harness(data,'snapshot');h.render();
  assert.match(h.elements.get('sourceMetrics').innerHTML,/Saved public snapshot only/);
  assert.match(h.elements.get('sourceTable').innerHTML,/Collection status unavailable/);
  assert.doesNotMatch(h.elements.get('sourceTable').innerHTML,/Fetch succeeded|HTTP 503/);
  assert.match(h.elements.get('sourceInventoryNotice').textContent,/not checked here/);
});
test('unavailable counts are distinct from an empty publisher and old APIs disclose sample scope',()=>{
  const data=inventory();data.scope='unavailable';data.total_stories=null;data.represented_count=null;
  data.items.forEach(item=>{item.story_count=null;item.collection_status='unknown';});
  let h=harness(data);h.render();
  assert.match(h.elements.get('sourceTable').innerHTML,/Counts unavailable/);
  assert.doesNotMatch(h.elements.get('sourceTable').innerHTML,/No stored stories/);
  assert.match(h.elements.get('sourceChart').innerHTML,/Database counts could not be loaded/);
  h=harness();h.render();
  assert.match(h.elements.get('sourceInventoryNotice').textContent,/Refresh the workspace to retry/);
  assert.match(h.elements.get('sourceMetrics').innerHTML,/Loaded sample only/);
  assert.doesNotMatch(h.elements.get('sourceMetrics').innerHTML,/Entire database/);
});
test('publisher metadata and collection errors cannot inject markup or unsafe links',()=>{
  const data=inventory();data.items=[{name:'<img src=x onerror=alert(1)>',story_count:1,collection_status:'failed',last_error:'<script>alert(1)</script>',url:'javascript:alert(1)'}];
  const h=harness(data);h.render();const table=h.elements.get('sourceTable').innerHTML;
  assert.doesNotMatch(table,/<img|<script|href="javascript:/);
  assert.match(table,/&lt;img/);assert.match(table,/&lt;script/);
});

test('Phase 3 shows actual private source triage and publication latency, not guessed health',()=>{
  const h=harness(inventory());
  h.workspace.source_triage={scope:'database',status:'attention',tracked:3,observed:2,attention:1,
    counts:{failed:1,stale:0,healthy:1,awaiting_collection:1},
    incidents:[{name:'ABP माझा',state:'failed',last_attempt_at:'2026-11-02T12:00:00Z',
      last_success_at:null,error_class:'HTTPError'}]};
  h.workspace.newsroom_operations={scope:'database',
    latency:{sample_limit:300,evaluated:10,measured:8,median_minutes:12.5,
      p95_minutes:45,definition:'Recorded collection to publication, not live visibility.'},
    delivery:{recorded:true,counts:{queued:2,syncing:1,failed:1,synced:5}},
    corrections:{recorded:true,counts:{pending:3,published:4}}};
  h.render();
  assert.match(h.elements.get('sourceTriageMetrics').innerHTML,/Recorded checks:2 \/ 3/);
  assert.match(h.elements.get('sourceTriageMetrics').innerHTML,/Failed checks:1/);
  assert.match(h.elements.get('sourceIncidents').innerHTML,/ABP माझा/);
  assert.match(h.elements.get('sourceOperationsMetrics').innerHTML,/Median collection → publish:12.5 min/);
  assert.match(h.elements.get('sourceOperationsMetrics').innerHTML,/Queued \/ failed delivery:4/);
  assert.match(h.elements.get('sourceOperationsMetrics').innerHTML,/Pending editorial updates:3/);
  assert.match(h.elements.get('sourceOperationsNote').textContent,/not live visibility/);
});
test('Phase 3 snapshot remains unavailable; incident text is HTML-escaped',()=>{
  const h=harness({...inventory(),scope:'snapshot'},'snapshot');
  h.workspace.source_triage={scope:'snapshot',status:'unavailable',counts:null,incidents:[]};
  h.workspace.newsroom_operations={scope:'unavailable'};
  h.render();
  assert.match(h.elements.get('sourceTriageMetrics').innerHTML,/Collector checks:Unavailable/);
  assert.match(h.elements.get('sourceIncidents').innerHTML,/Collector status not checked/);
  assert.match(h.elements.get('sourceOperationsMetrics').innerHTML,/Delivery queue:Unavailable/);
  assert.doesNotMatch(h.elements.get('sourceTriageMetrics').innerHTML,/Failed checks:0/);
  const e=harness(inventory());
  e.workspace.source_triage={scope:'database',status:'attention',tracked:1,observed:1,attention:1,
    counts:{failed:1},incidents:[{name:'<img src=x onerror=alert(1)>',state:'failed',
      error_class:'<script>alert(1)</script>'}]};
  e.render();
  const html=e.elements.get('sourceIncidents').innerHTML;
  assert.match(html,/&lt;img/);
  assert.match(html,/&lt;script/);
  assert.doesNotMatch(html,/<img|<script/);
});

test('Phase 4 renders real operational alerts and 14-day history without auto actions',()=>{
  const h=harness(inventory());
  h.workspace.newsroom_alerts={
    scope:'database',status:'attention',alert_limit:30,
    alerts:[{kind:'source',severity:'high',title:'Source failed',source:'TV9 Marathi',
      detail:'Check actual phone logs.',at:'2026-11-02T10:00:00Z'},
      {kind:'correction',severity:'high',title:'Correction awaiting review',item_id:12,
      detail:'Human review required',at:'2026-11-01T10:00:00Z'}],
    followups:[{kind:'correction',item_id:12,age_minutes:1000}],
    availability:{collector_history:true,delivery:true,corrections:true},
    trend:{collector_history_available:true,recorded_outcomes:3,series:[
      {day:'2026-11-01',healthy:2,failed:1,not_configured:0,published:4}
    ],note:'Actual append-only checks; not generated history.'},
    note:'Do not automatically publish or retry.'
  };
  h.render();
  assert.match(h.elements.get('phase4Metrics').innerHTML,/Active alerts:2/);
  assert.match(h.elements.get('phase4Metrics').innerHTML,/Overdue corrections:1/);
  assert.match(h.elements.get('phase4Metrics').innerHTML,/Recorded source outcomes:3/);
  assert.match(h.elements.get('phase4Alerts').innerHTML,/TV9 Marathi/);
  assert.match(h.elements.get('phase4Alerts').innerHTML,/Story #12/);
  assert.match(h.elements.get('phase4Trend').innerHTML,/2026-11-01/);
  assert.match(h.elements.get('phase4Trend').innerHTML,/>4<\/td>/);
  assert.match(h.elements.get('phase4Notice').textContent,/Do not automatically publish/);
});
test('Phase 4 refuses to paint private phone metrics from a public snapshot',()=>{
  const h=harness({...inventory(),scope:'snapshot'},'snapshot');
  h.workspace.newsroom_alerts={scope:'unavailable',status:'unavailable',alerts:[],trend:null};
  h.render();
  assert.match(h.elements.get('phase4Metrics').innerHTML,/Operational alerts:Unavailable/);
  assert.match(h.elements.get('phase4Alerts').innerHTML,/Private alerts unavailable/);
  assert.match(h.elements.get('phase4Trend').innerHTML,/Historical data unavailable/);
  assert.doesNotMatch(h.elements.get('phase4Metrics').innerHTML,/Active alerts:0/);
});
test('Phase 4 escapes source-provided alert strings before writing to the DOM',()=>{
  const h=harness(inventory());
  h.workspace.newsroom_alerts={
    scope:'database',status:'attention',alert_limit:30,
    alerts:[{severity:'high',kind:'source',title:'<script>alert(1)</script>',
      source:'<img src=x onerror=alert(1)>',detail:'<svg onload=alert(1)>',
      at:'2026-11-02T10:00:00Z'}],
    followups:[],availability:{collector_history:true,delivery:true,corrections:true},
    trend:{collector_history_available:true,recorded_outcomes:1,series:[
      {day:'<svg onload=alert(1)>',healthy:1,failed:0,not_configured:0,published:1}
    ]}
  };
  h.render();
  const markup=h.elements.get('phase4Alerts').innerHTML+' '+h.elements.get('phase4Trend').innerHTML;
  assert.match(markup,/&lt;script/);
  assert.match(markup,/&lt;img/);
  assert.match(markup,/&lt;svg/);
  assert.doesNotMatch(markup,/<script|<img|<svg/);
});
