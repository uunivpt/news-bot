const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const home=fs.readFileSync('public/index.html','utf8');
const css=fs.readFileSync('public/assets/reading-guides-home.css','utf8');
test('homepage guide cards use short, descriptive linked headings',()=>{
  const cards=[...home.matchAll(/<article class="ph-guide-card">([\s\S]*?)<\/article>/g)];
  assert.equal(cards.length,4);
  for(const [,card] of cards){
    assert.match(card,/<h3><a href="\/[^"]+">[^<]+<\/a><\/h3>/);
    assert.match(card,/<p>[^<]+<\/p>/);
    assert.ok(card.indexOf('</a>')<card.indexOf('<p>'),'description must not be link text');
  }
  assert.match(css,/\.ph-guides-grid>\.ph-guide-card/);
});
test('static homepage internal anchor texts are distinct and concise',()=>{
 const seen=new Set();
 for(const match of home.matchAll(/<a\b([^>]*)>([\s\S]*?)<\/a>/gi)){
   const href=match[1].match(/href="([^"]+)"/)?.[1];
   if(!href?.startsWith('/'))continue;
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
