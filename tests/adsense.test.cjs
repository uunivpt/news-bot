const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const source=fs.readFileSync('public/assets/adsense.js','utf8');
async function setup({enabled=true,hostname='www.politicshub.in',hash='',client='ca-pub-1752666987448533'}={}){
 const scripts=[];let callback,requests=0;
 const ctx=vm.createContext({location:{hostname,hash},fetch:async()=>{requests++;return {ok:true,json:async()=>({enabled,client})}},document:{getElementById:()=>scripts[0],createElement:()=>({}),head:{append:s=>scripts.push(s)}},window:{__tcfapi:(name,version,cb)=>{callback=cb},addEventListener(){}}});
 vm.runInContext(source,ctx);await new Promise(resolve=>setImmediate(resolve));
 return {scripts,callback,requests,ctx};
}
test('pending approval makes no advertising request or CMP subscription',async()=>{const h=await setup({enabled:false});assert.equal(h.scripts.length,0);assert.equal(h.callback,undefined)});
test('preview domains and settings do not initialize ads',async()=>{for(const options of [{hostname:'localhost'},{hostname:'preview.vercel.app'},{hash:'#/settings'}]){const h=await setup(options);assert.equal(h.requests,0)}});
test('invalid publisher identifiers cannot become script URLs',async()=>{const h=await setup({client:'https://example.com'});assert.equal(h.callback,undefined)});
test('CMP consent required; repeated consent events create only one loader',async()=>{const h=await setup();h.callback({eventStatus:'tcloaded',gdprApplies:true},true);assert.equal(h.scripts.length,0);const granted={eventStatus:'useractioncomplete',gdprApplies:true,vendor:{consents:{755:true}},purpose:{consents:{1:true,3:true,4:true}}};h.callback(granted,true);h.callback(granted,true);assert.equal(h.scripts.length,1);assert.equal(h.scripts[0].crossOrigin,'anonymous');assert.match(h.scripts[0].src,/client=ca-pub-1752666987448533$/)});
test('a loading/failed CMP decision never requests ads',async()=>{const h=await setup();h.callback({eventStatus:'cmpuishown',gdprApplies:false},true);h.callback({eventStatus:'tcloaded',gdprApplies:false},false);assert.equal(h.scripts.length,0)});
test('navigation to settings while awaiting consent suppresses ads',async()=>{const h=await setup();h.ctx.location.hash='#/settings';h.callback({eventStatus:'tcloaded',gdprApplies:false},true);assert.equal(h.scripts.length,0)});
