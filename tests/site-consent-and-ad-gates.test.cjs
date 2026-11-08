const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');

const html=fs.readFileSync('public/index.html','utf8');
const site=fs.readFileSync('public/assets/site.js','utf8');
const staticUI=fs.readFileSync('public/assets/ui.js','utf8');
const monetization=fs.readFileSync('app/monetization.py','utf8');

test('consent controls remain user-accessible after making a choice',()=>{
  assert.match(html,/href="\/cookies\.html" data-open-consent>Site preferences/);
  assert.match(site,/\[data-open-consent\]/);
  assert.match(site,/function showConsentBanner\(force=false\)/);
  assert.match(staticUI,/const showSitePreferences = \(\) =>/);
  assert.match(staticUI,/if \(!mode\) showSitePreferences\(\)/);
  assert.match(staticUI,/\[data-open-consent\]/);
  // Local reading preferences do NOT impersonate advertising consent.
  assert.match(html,/These buttons do not grant consent to Google advertising/);
  assert.doesNotMatch(site,/localStorage\.setItem\(['"]ad_storage/);
});

test('potentially restricted news needs explicit advertising suitability evidence',()=>{
  assert.match(monetization,/def requires_sensitive_ad_review\(row\):/);
  assert.match(monetization,/Ad suitability reviewed for sensitive coverage/);
});
