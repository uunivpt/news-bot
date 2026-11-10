const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const home=fs.readFileSync('public/index.html','utf8');
const ui=fs.readFileSync('public/assets/ui.js','utf8');
const analytics=fs.readFileSync('public/assets/measurement.js','utf8');

test('homepage declares existing GA4 bootstrap without a second external Google tag',()=>{
 assert.match(home,/src="\/assets\/measurement\.js\?v=ga4coverage1"/);
 assert.match(home,/data-ga4-measurement-id="G-2HVZQST08G"/);
 assert.doesNotMatch(home,/src="https:\/\/www\.googletagmanager\.com\/gtag\/js/);
 const measurement=home.indexOf('src="/assets/measurement.js?v=ga4coverage1"');
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

test('no network GA or ad event is initiated without Google CMP consent',()=>{
 new vm.Script(analytics);
 assert.match(analytics,/CONSENT_MODE_DATA_READY/);
 assert.match(analytics,/getGoogleConsentModeValues/);
 assert.match(analytics,/if \(!analytics && !ads && !initialized\) return/);
 assert.match(analytics,/if \(analytics && !analyticsConfigured\)/);
 assert.match(analytics,/window\['ga-disable-G-2HVZQST08G'\] = !analytics/);
 assert.doesNotMatch(home,/name="google-site-verification"/);
});
