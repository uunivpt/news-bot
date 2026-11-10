const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const code = fs.readFileSync('public/assets/measurement.js', 'utf8');

function harness(path='/') {
  const scripts=[];
  const window={};
  const context=vm.createContext({window, location:{pathname:path}, Date,
    document:{createElement:()=>({dataset:{}}), head:{appendChild:s=>scripts.push(s)},
      querySelector:selector=>selector==='script[data-politicshub-google-tag]' ? scripts[0] : null}});
  vm.runInContext(code, context);
  const enums={CONSENT_MODE_PURPOSE_STATUS_UNKNOWN:0, CONSENT_MODE_PURPOSE_STATUS_GRANTED:1,
    CONSENT_MODE_PURPOSE_STATUS_DENIED:2, CONSENT_MODE_PURPOSE_STATUS_NOT_APPLICABLE:3,
    CONSENT_MODE_PURPOSE_STATUS_NOT_CONFIGURED:4};
  const callback=window.googlefc?.callbackQueue.find(item=>item.CONSENT_MODE_DATA_READY)?.CONSENT_MODE_DATA_READY;
  if (window.googlefc) window.googlefc.ConsentModePurposeStatusEnum=enums;
  function decide(analytics,ads,userData=ads,personalization=ads) {
    window.googlefc.getGoogleConsentModeValues=()=>({analyticsStoragePurposeConsentStatus:analytics,
      adStoragePurposeConsentStatus:ads, adUserDataPurposeConsentStatus:userData,
      adPersonalizationPurposeConsentStatus:personalization});
    callback();
  }
  return {window,scripts,decide,callback,rerun:()=>vm.runInContext(code,context)};
}

const events=h=>JSON.parse(JSON.stringify(h.window.dataLayer.map(args=>Array.from(args))));
const latestConsent=h=>events(h).filter(e=>e[0]==='consent').at(-1)[2];
const denied={analytics_storage:'denied',ad_storage:'denied',ad_user_data:'denied',ad_personalization:'denied'};

test('advanced consent bootstrap denies storage before configuration and loads one tag',()=>{
  const h=harness(),queue=events(h);
  assert.deepEqual(queue[0],['consent','default',{...denied,wait_for_update:500}]);
  assert.deepEqual(queue[1],['set','ads_data_redaction',true]);
  assert.deepEqual(queue.filter(e=>e[0]==='config').map(e=>e[1]),['G-2HVZQST08G','AW-18495731647']);
  assert.equal(h.scripts.length,1);
  assert.equal(h.scripts[0].src,'https://www.googletagmanager.com/gtag/js?id=G-2HVZQST08G');
  for(const state of [2,0,4,undefined]) {h.decide(state,state);assert.deepEqual(latestConsent(h),denied)}
  h.rerun();assert.equal(h.scripts.length,1);
});
test('analytics and advertising permissions are independent',()=>{
  const h=harness(); h.decide(1,2);
  assert.deepEqual(latestConsent(h),{...denied,analytics_storage:'granted'});
  h.decide(1,1,2,0);
  assert.deepEqual(latestConsent(h),{...denied,analytics_storage:'granted',ad_storage:'granted'});
  assert.ok(!events(h).some(e=>e[0]==='event'));
});
test('consent can expand then withdraw without duplicate script or conversions',()=>{
  const h=harness(); h.decide(1,2); h.decide(1,1); h.decide(1,1); h.decide(2,2);
  assert.equal(h.scripts.length,1);
  assert.equal(events(h).filter(e=>e[0]==='event').length,0);
  assert.equal(events(h).at(-1)[1],'update');
  assert.deepEqual(latestConsent(h),denied);
});
test('advertising permission alone leaves Analytics storage denied',()=>{
  const h=harness('/india/44-report'); h.decide(2,1);
  assert.deepEqual(latestConsent(h),{...denied,ad_storage:'granted',ad_user_data:'granted',ad_personalization:'granted'});
  assert.ok(!events(h).some(e=>e[0]==='event'));
});
test('missing CMP data keeps default denial and not-applicable states are handled',()=>{
  const h=harness(),initial=events(h).length;
  h.callback();assert.equal(events(h).length,initial);
  h.window.googlefc.getGoogleConsentModeValues=()=>null;
  h.callback();assert.equal(events(h).length,initial);
  h.decide(3,3);
  assert.ok(Object.values(latestConsent(h)).every(state=>state==='granted'));
  delete h.window.googlefc.ConsentModePurposeStatusEnum;
  const before=events(h).length;h.callback();assert.equal(events(h).length,before);
});
test('admin, API and private console never register measurement',()=>{
  for (const path of ['/admin/','/api/news','/newsroom-console-test.html','/debug.html']) {
    const h=harness(path); assert.equal(h.window.googlefc,undefined); assert.equal(h.scripts.length,0);
  }
});
