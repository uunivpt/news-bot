const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const code = fs.readFileSync('public/assets/measurement.js', 'utf8');

function harness(path='/') {
  const scripts=[];
  const window={};
  const context=vm.createContext({window, location:{pathname:path}, Date,
    document:{createElement:()=>({}), head:{appendChild:s=>scripts.push(s)}, querySelector:()=>null}});
  vm.runInContext(code, context);
  const enums={CONSENT_MODE_PURPOSE_STATUS_UNKNOWN:0, CONSENT_MODE_PURPOSE_STATUS_GRANTED:1,
    CONSENT_MODE_PURPOSE_STATUS_DENIED:2, CONSENT_MODE_PURPOSE_STATUS_NOT_APPLICABLE:3,
    CONSENT_MODE_PURPOSE_STATUS_NOT_CONFIGURED:4};
  const callback=window.googlefc?.callbackQueue.find(item=>item.CONSENT_MODE_DATA_READY)?.CONSENT_MODE_DATA_READY;
  if (window.googlefc) window.googlefc.ConsentModePurposeStatusEnum=enums;
  function decide(analytics,ads) {
    window.googlefc.getGoogleConsentModeValues=()=>({analyticsStoragePurposeConsentStatus:analytics,
      adStoragePurposeConsentStatus:ads, adUserDataPurposeConsentStatus:ads,
      adPersonalizationPurposeConsentStatus:ads});
    callback();
  }
  return {window,scripts,decide};
}

test('no optional measurement request before CMP data or after denial',()=>{
  const h=harness(); assert.equal(h.scripts.length,0);
  h.decide(2,2); assert.equal(h.scripts.length,0); assert.equal(h.window.dataLayer,undefined);
  h.decide(0,0); h.decide(4,4); assert.equal(h.scripts.length,0);
});
test('analytics and advertising permissions are independent',()=>{
  const h=harness(); h.decide(1,2);
  assert.equal(h.scripts.length,1);
  const events=h.window.dataLayer.map(args=>Array.from(args));
  assert.ok(events.some(e=>e[0]==='config'&&e[1]==='G-2HVZQST08G'));
  assert.ok(!events.some(e=>e[0]==='config'&&e[1]==='AW-18495731647'));
  assert.ok(!events.some(e=>e[0]==='event'));
});
test('consent can expand then withdraw without duplicate script or conversions',()=>{
  const h=harness(); h.decide(1,2); h.decide(1,1); h.decide(1,1); h.decide(2,2);
  assert.equal(h.scripts.length,1);
  const events=h.window.dataLayer.map(args=>Array.from(args));
  assert.equal(events.filter(e=>e[0]==='event'&&e[1]==='conversion').length,1);
  assert.equal(events.at(-1)[0],'consent'); assert.equal(events.at(-1)[1],'update');
  assert.equal(events.at(-1)[2].ad_storage,'denied');
  assert.equal(h.window['ga-disable-G-2HVZQST08G'],true);
});
test('advertising permission alone never configures Analytics',()=>{
  const h=harness('/india/44-report'); h.decide(2,1);
  assert.match(h.scripts[0].src,/id=AW-18495731647$/);
  assert.ok(!h.window.dataLayer.some(e=>e[0]==='config'&&e[1]==='G-2HVZQST08G'));
  assert.ok(!h.window.dataLayer.some(e=>e[0]==='event'));
});
test('admin, API and private console never register measurement',()=>{
  for (const path of ['/admin/','/api/news','/newsroom-console-test.html','/debug.html']) {
    const h=harness(path); assert.equal(h.window.googlefc,undefined); assert.equal(h.scripts.length,0);
  }
});
