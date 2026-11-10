
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const read=p=>fs.readFileSync(p,'utf8');
const hrefs=html=>[...html.matchAll(/href="([^"]+)"/g)].map(x=>x[1]);
test('Home Maharashtra India World India Exams are the five primary links',()=>{
 const site=read('public/assets/site.js'),editorial=read('public/assets/editorial-home.js'),home=read('public/index.html');
 assert.ok(site.includes("const NAV_CATS=[['all','Home'],['maharashtra','Maharashtra'],['india','India'],['world','World'],['exams','India Exams']]"));
 const build=site.slice(site.indexOf('function build(){'),site.indexOf('function ticker(){'));
 assert.equal((build.match(/NAV_CATS\.map/g)||[]).length,2);
 assert.ok(editorial.includes('var cats=NAV_CATS.map'));
 const nav=home.match(/<nav class="main" id="nav"[^>]*>([\s\S]*?)<\/nav>/)?.[1];
 assert.ok(nav);assert.deepEqual(hrefs(nav),['/','/maharashtra/','/india/','/world/','/exams/']);
 assert.ok(home.includes('<li><a href="/exams/">Browse examination updates</a></li>'));
});
test('India Exams page is index-eligible, in the sitemap, and links back to primary desks',()=>{
 const page=read('public/exams/index.html'),robots=read('public/robots.txt'),sitemap=read('public/static-sitemap.xml');
 const nav=page.match(/<nav class="exam-top-nav"[^>]*>([\s\S]*?)<\/nav>/)?.[1];
 assert.ok(nav);assert.deepEqual(hrefs(nav),['/','/maharashtra/','/india/','/world/','/exams/']);
 assert.ok(page.includes('<h1>India Exams: Official Notices and Updates</h1>'));
 assert.ok(page.includes('<link rel="canonical" href="https://www.politicshub.in/exams/">'));
 assert.ok(page.includes('<meta name="robots" content="index,follow,max-image-preview:large">'));
 assert.ok(page.includes('"@type":"CollectionPage"'));
 assert.ok(sitemap.includes('<loc>https://www.politicshub.in/exams/</loc>'));
 assert.ok(robots.includes('Sitemap: https://www.politicshub.in/sitemap.xml'));
 assert.ok(!robots.includes('Disallow: /exams/'));
 assert.ok(JSON.parse(read('vercel.json')).rewrites.some(r=>r.source==='/exams/'&&r.destination==='/exams/index.html'));
});
