const {test} = require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const site=fs.readFileSync('public/assets/site.js','utf8');
const visual=fs.readFileSync('public/assets/editorial-home.js','utf8');
const from=site.indexOf('function newsPhoto(item){');
const to=site.indexOf('function img(item){',from);
assert.ok(from>=0 && to>from,'missing image validation');
const newsPhoto=vm.runInNewContext(site.slice(from,to)+'\nnewsPhoto',{URL});
const begin=visual.indexOf(' function phMedia(i,lead){');
const end=visual.indexOf('\n home=function(c){',begin);
assert.ok(begin>=0 && end>begin,'missing homepage photo rendering');
const esc=(value)=>String(value).replace(/[&<>"']/g, x=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]));
const phMedia=vm.runInNewContext(visual.slice(begin,end)+'\nphMedia',{newsPhoto,esc});

test('missing image produces text-led article, never invented SVG artwork',()=>{
 assert.equal(phMedia({title:'World news',image:''},true),'');
 assert.equal(phMedia({title:'India news',image:null},false),'');
 assert.doesNotMatch(visual,/ph14-editorial-visual|ph14-visual-footer|INDEPENDENT NEWSROOM/);
});
test('licensed and credited sources display real photos and keep attribution',()=>{
 const row={image:'/api/image/31',title:'Public statement',image_credit:'Photographer & agency',image_license:'licensed'};
 const html=phMedia(row,true);
 assert.match(html,/class="ph14-media"/);
 assert.match(html,/data-news-photo/);
 assert.match(html,/Illustrative source photo/);
 assert.match(html,/Photographer &amp; agency/);
 assert.match(html,/referrerpolicy="no-referrer"/);
});
test('unverified links, image placeholders and publisher logos never render',()=>{
 const row={image:'https://images.example.org/photos/report.jpg'};
 assert.equal(newsPhoto(row),'');
 assert.equal(newsPhoto({...row,image_license:'licensed',image_source:'article-source',image_credit:'Agency'}),row.image);
 for(const bad of ['javascript:alert(1)','//example.org/x.png','https://example.org/logo.jpg','https://example.org/placeholder.png','https://example.org/tiny.svg']) {
   assert.equal(newsPhoto({...row,image:bad,image_license:'licensed',image_source:'article-source',image_credit:'Agency'}),'',bad);
 }
 assert.equal(newsPhoto({image:'/api/image/42'}),'/api/image/42');
 assert.equal(newsPhoto({image:'/api/x-card/42'}),'/api/x-card/42');
});
test('layout removes misleading generated media and checks broken or small photos',()=>{
 const css=fs.readFileSync('public/assets/home-critical.css','utf8');
 const ui=fs.readFileSync('public/assets/ui.js','utf8');
 assert.doesNotMatch(css,/ph14-editorial-visual/);
 assert.match(ui,/naturalWidth/);
 assert.match(ui,/naturalHeight/);
 assert.match(ui,/removeUnusablePhoto/);
 assert.match(css,/ph14-photo-credit/);
});
