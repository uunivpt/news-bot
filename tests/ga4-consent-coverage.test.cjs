const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const home=fs.readFileSync('public/index.html','utf8');
const ui=fs.readFileSync('public/assets/ui.js','utf8');
const analytics=fs.readFileSync('public/assets/measurement.js','utf8');

test('homepage declares existing GA4 bootstrap without a second external Google tag',()=>{
 assert.equal((home.match(/src="\/assets\/measurement\.js\?v=[^"\s]+"/g)||[]).length,1);
 assert.match(home,/data-ga4-measurement-id="G-2HVZQST08G"/);
 assert.doesNotMatch(home,/src="https:\/\/www\.googletagmanager\.com\/gtag\/js/);
 const measurement=home.indexOf('src="/assets/measurement.js?v=');
 const chrome=home.indexOf('src="/assets/ui.js?v=');
 assert.ok(measurement>0 && measurement<chrome);
});

test('public pages reuse one measurement bootstrap and exclude noindex/private pages',()=>{
 new vm.Script(ui);
 assert.match(ui,/document\.querySelector\('script\[src\*="\/assets\/measurement\.js"\]'\)/);
 assert.match(ui,/meta\[name="robots"\]\[content\*="noindex"\]/);
 assert.match(ui,/admin/);
 assert.match(ui,/newsroom-console/);
 assert.match(ui,/measurement\.dataset\.ga4MeasurementId = 'G-2HVZQST08G'/);
});

test('measurement declares denied consent defaults and delegates updates to the Google CMP',()=>{
 new vm.Script(analytics);
 assert.match(analytics,/CONSENT_MODE_DATA_READY/);
 assert.match(analytics,/getGoogleConsentModeValues/);
 assert.match(analytics,/'consent', 'default'/);
 assert.match(analytics,/'consent', 'update'/);
 for(const purpose of ['analytics_storage','ad_storage','ad_user_data','ad_personalization']){
  assert.ok(analytics.includes(purpose+": 'denied'"));
 }
 assert.doesNotMatch(analytics,/'event',\s*'conversion'/);
 assert.doesNotMatch(analytics,/ph-consent-v1/);
 assert.doesNotMatch(home,/name="google-site-verification"/);
});
