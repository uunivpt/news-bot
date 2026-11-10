const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const home=fs.readFileSync('public/index.html','utf8');
test('lengthy explainer sections are absent from the homepage',()=>{
  assert.doesNotMatch(home,/class="ph-guides(?:\s|")/);
  assert.doesNotMatch(home,/class="ph-guide-card"/);
  for(const heading of [
    'Understand the news, not just the headline.',
    'What to check before sharing a headline',
    'How to read and verify our news coverage'
  ])assert.ok(!home.includes(heading),'unexpected homepage explainer: '+heading);
  assert.match(home,/<main id="app"/);
  // Independent guide pages stay discoverable through the footer.
  assert.match(home,/href="\/guides\/election-results\.html"/);
  assert.match(home,/href="\/guides\/maharashtra-mlc\.html"/);
});
test('static homepage internal anchor texts are distinct and concise',()=>{
 const seen=new Set();
 for(const match of home.matchAll(/<a\b([^>]*)>([\s\S]*?)<\/a>/gi)){
   const href=match[1].match(/href="([^"]+)"/)?.[1];
   if(!href?.startsWith('/'))continue;
   // Publisher headlines in the initial feed retain their complete wording.
   if(/^\/(?:india|world)\/\d+$/.test(href))continue;
   const text=match[2].replace(/<[^>]+>/g,' ').replace(/&amp;/g,'&').replace(/\s+/g,' ').trim();
   if(!text)continue;
   assert.ok(text.length<=75,'overlong internal anchor: '+text);
   assert.ok(!seen.has(text),'duplicate internal anchor: '+text);
   seen.add(text);
 }
});

test('guide CTAs do not duplicate or masquerade as buttons, and Apple icon is declared',()=>{
 assert.doesNotMatch(home,/Read the guide ↗/);
 assert.doesNotMatch(home,/Read the policy ↗/);
 assert.match(home,/<link rel="apple-touch-icon" sizes="180x180" href="\/apple-touch-icon.png">/);
 const site=fs.readFileSync('public/assets/site.js','utf8');
 assert.match(site,/existing.hidden=false/);
 assert.match(site,/existing.style.removeProperty\('display'\)/);
 assert.match(site,/This does not grant advertising consent/);
});
