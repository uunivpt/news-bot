const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ui = require('../public/assets/newsroom-ui.js');

test('news UI preserves story interactions without public statistics', () => {
  for (const name of ['bind','observe','icon']) assert.equal(typeof ui[name], 'function');
  assert.equal('dashboard' in ui, false);
  assert.equal('summarize' in ui, false);
  assert.match(ui.icon('search'), /<svg/);
});
test('public Reading Room and numerical counts are not rendered by homepage', () => {
  const js = fs.readFileSync('public/assets/newsroom-ui.js','utf8');
  const css = fs.readFileSync('public/assets/newsroom-ui.css','utf8');
  const homepage = fs.readFileSync('public/assets/editorial-home.js','utf8');
  const staticHome = fs.readFileSync('public/index.html','utf8');
  for (const source of [js, css, homepage, staticHome]) {
    assert.doesNotMatch(source, /THE READING ROOM|A little context\. A clearer picture\.|ph-ui-dashboard|ph-ui-stats|ph-ui-desks-tab|ph-ui-overview-tab/i);
  }
  assert.doesNotMatch(homepage, /ui\.dashboard|Named sources|list\.length\+' reports in '/);
  for (const preserved of ['ph14-hero','ph14-feed','data-news-density','Load more stories','homeNl',"ui.bind","ui.icon('search')"])
    assert.ok(homepage.includes(preserved), preserved);
});

test('homepage omits resource rail and trending list without losing news feed', () => {
 const home=fs.readFileSync('public/assets/editorial-home.js','utf8');
 const site=fs.readFileSync('public/assets/site.js','utf8');
 const css=fs.readFileSync('public/assets/newsroom-ui.css','utf8');
 for(const removed of ['EXPLORE MORE','Choose your desk.','READER RESOURCES','Go to the original.','Read with context.','Most read']) assert.ok(!home.includes(removed),removed);
 assert.doesNotMatch(home,/ph14-rail|\+rail\+/);
 assert.doesNotMatch(site,/function enhanceHome\(|\/api\/trending\?limit=5/);
 assert.match(css,/\.ph-ui-home \.ph14-feed \{ grid-template-columns: minmax\(0, 1fr\); \}/);
 for(const preserved of ['ph14-hero','ph14-feed','ph14-section-head','ph14-row','Load more stories','ph14-cats']) assert.ok(home.includes(preserved),preserved);
});
