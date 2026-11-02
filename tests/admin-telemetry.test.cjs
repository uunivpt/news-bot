const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const source=fs.readFileSync('public/assets/admin-telemetry.js','utf8');

function harness(data) {
  const elements=new Map();
  const context=vm.createContext({
    $:id=>{if(!elements.has(id))elements.set(id,{innerHTML:''});return elements.get(id);},
    api:async()=>data,telemetryAvailable:()=>true,telemetryError:(_,message)=>{throw Error(message);},
    metric:(label,value,detail='')=>`${label}:${value};${detail}\n`,number:value=>String(value),
    esc:value=>String(value??''),arr:value=>Array.isArray(value)?value:[],
    pct:value=>value==null?'—':value+'%',date:value=>value||'Not recorded',
  });
  vm.runInContext(source,context);
  return {context,elements};
}

test('upgrade displays measured database and actual stored story inventory',async()=>{
  const data={counts:{scores:0,events:0},availability:{scores:true,events:true},
    inventory:{total:454,published:1,pending:453,sources:[{source:'Source desk',records:454,published:1}]},
    resources:{database:{status:'available',engine:'postgresql',bytes:13*1048576},media:{status:'not_configured',bytes:null}},
    history:{counts:{scores:0,alerts:0,failures:0}}};
  const h=harness(data);await vm.runInContext('loadUpgrade()',h.context);
  assert.match(h.elements.get('upgradeMetrics').innerHTML,/Stored stories:454/);
  assert.match(h.elements.get('upgradeResources').innerHTML,/DB:13 MB/);
  assert.match(h.elements.get('upgradeResources').innerHTML,/Media:Unavailable/);
  assert.match(h.elements.get('upgradeSources').innerHTML,/Stored source coverage/);
  assert.match(h.elements.get('upgradeSources').innerHTML,/454/);
  assert.match(h.elements.get('upgradeScores').innerHTML,/No scoring runs recorded/);
});

test('missing or legacy storage measurement never renders a zero MB database',async()=>{
  const h=harness({resources:{local_bytes:{db:0,media:0}},history:{counts:{scores:null}}});
  await vm.runInContext('loadUpgrade()',h.context);
  assert.match(h.elements.get('upgradeResources').innerHTML,/DB:Unavailable/);
  assert.doesNotMatch(h.elements.get('upgradeResources').innerHTML,/0 MB/);
  assert.match(h.elements.get('upgradeHistory').innerHTML,/Scores:Unavailable/);
  assert.match(h.elements.get('upgradeMetrics').innerHTML,/Stored stories:Unavailable/);
});

test('unavailable collection is distinguished from an empty recorded collection',async()=>{
  const h=harness({availability:{alerts:false,scores:false,events:true}});
  await vm.runInContext('loadUpgrade()',h.context);
  assert.match(h.elements.get('upgradeAlerts').innerHTML,/Data unavailable/);
  assert.match(h.elements.get('upgradeScores').innerHTML,/Data unavailable/);
  assert.match(h.elements.get('upgradeEvents').innerHTML,/No event groups recorded/);
});
