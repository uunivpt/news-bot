const {test}=require('node:test');
const assert=require('node:assert/strict');
const {KEY,MAX_ITEMS,clean,create,select}=require('../public/assets/reading-list.js');
const origin='https://www.politicshub.in';
function memory(){const data=new Map();return {getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v),removeItem:k=>data.delete(k)}}
const story=(id=1)=>({url:'/india/'+id+'-public-report',title:'Public report '+id,savedAt:id});

test('reading list requires optional preferences before reading or writing',()=>{
 const storage=memory();storage.setItem(KEY,JSON.stringify([story()]));
 const list=create(storage,origin,()=>false);
 assert.deepEqual(list.read(),[]);assert.equal(list.add(story(2)),false);
 assert.equal(JSON.parse(storage.getItem(KEY)).length,1);
});
test('only valid same-origin article links may be saved',()=>{
 for(const url of ['javascript:alert(1)','https://evil.example/india/1-report','//evil.example/india/1-report','/admin/','/newsletter/confirm?token=private','/#/settings','/'])assert.equal(clean({title:'Test',url},origin),null,url);
 assert.equal(clean(story(),origin).url,story().url);
 assert.equal(clean({title:'Legacy report',url:'/#/article/42'},origin).url,'/#/article/42');
});
test('saving is deduplicated, bounded and survives a new store instance',()=>{
 const storage=memory(),list=create(storage,origin,()=>true);
 for(let id=1;id<=MAX_ITEMS+20;id++)assert.equal(list.add(story(id)),true);
 assert.equal(list.read().length,MAX_ITEMS);
 assert.equal(list.read()[0].url,story(120).url);
 list.add({...story(120),title:'Corrected title'});
 assert.equal(list.read().length,MAX_ITEMS);
 assert.equal(create(storage,origin,()=>true).read()[0].title,'Corrected title');
 list.remove(story(120).url);assert.equal(list.read().length,MAX_ITEMS-1);
 list.clear();assert.deepEqual(list.read(),[]);
});
test('corrupt data and blocked or full browser storage are recoverable',()=>{
 const storage=memory();storage.setItem(KEY,'malformed');assert.deepEqual(create(storage,origin,()=>true).read(),[]);
 storage.setItem(KEY,JSON.stringify([story(),story(),{title:'Bad',url:'javascript:alert(1)'}]));
 assert.equal(create(storage,origin,()=>true).read().length,1);
 const blocked=create({getItem(){throw Error('blocked')},setItem(){throw Error('full')},removeItem(){throw Error('blocked')}},origin,()=>true);
 assert.deepEqual(blocked.read(),[]);assert.equal(blocked.add(story()),false);assert.equal(blocked.clear(),false);
});

test('numeric news links keep reading tools and saved stories available',()=>{
 for(const desk of ['india','politics','world','hindi','maharashtra']){
  const url='/'+desk+'/617958005290';
  assert.equal(clean({title:'Numeric report',url},origin)?.url,url);
  const storage=memory(),list=create(storage,origin,()=>true);
  assert.equal(list.add({title:'Numeric report',url:url+'?revision=updated'}),true);
  assert.equal(create(storage,origin,()=>true).read()[0].url,url);
  assert.equal(list.add({title:'Same report',url}),true);
  assert.equal(list.read().length,1);
 }
});

test('numeric link support does not permit other routes or external origins',()=>{
 for(const url of ['/admin/617958005290','/india/not-a-number','/india/617958005290/extra','https://evil.example/india/617958005290','https://user:secret@www.politicshub.in/india/617958005290']){
  assert.equal(clean({title:'Rejected report',url},origin),null,url);
 }
});

test('saved headline search normalizes text, combines literal words and supports Marathi',()=>{
 const items=[{...story(1),title:'ＢＵＤＧＥＴ policy 2026'},
  {...story(2),title:'Budget review [final]'}, {...story(3),title:'महाराष्ट्र निवडणूक निकाल'}];
 assert.deepEqual(select(items,'  budget   POLICY ').map(x=>x.url),[items[0].url]);
 assert.deepEqual(select(items,'[final]').map(x=>x.url),[items[1].url]);
 assert.deepEqual(select(items,'महाराष्ट्र निकाल').map(x=>x.url),[items[2].url]);
 assert.deepEqual(select(items,'no matching words'),[]);
 assert.equal(select(items,' \t ').length,3);
});

test('saved sorting uses save time or natural headline order without mutating stored data',()=>{
 const storage=memory(),list=create(storage,origin,()=>true);
 for(const item of [{...story(1),title:'Report 10'}, {...story(2),title:'Report 2'}, {...story(3),title:'Alpha'}])list.add(item);
 const before=storage.getItem(KEY),items=list.read(),copy=JSON.stringify(items);
 assert.deepEqual(select(items,'','recent').map(x=>x.savedAt),[3,2,1]);
 assert.deepEqual(select(items,'','oldest').map(x=>x.savedAt),[1,2,3]);
 assert.deepEqual(select(items,'','title').map(x=>x.title),['Alpha','Report 2','Report 10']);
 assert.deepEqual(select(items,'report','title').map(x=>x.title),['Report 2','Report 10']);
 assert.deepEqual(select(items,'','unknown').map(x=>x.savedAt),[3,2,1]);
 assert.equal(JSON.stringify(items),copy);assert.equal(storage.getItem(KEY),before);
 assert.deepEqual(select([], 'anything', 'title'),[]);
});

test('bookmark export uses portable public links and escapes Unicode headlines as text',()=>{
 const {bookmarks}=require('../public/assets/reading-list.js');
 const rows=[{url:'/india/42?token=fixture-private',title:'Budget & policy <script>alert(1)</script>'},
  {url:'/#/article/17',title:'महाराष्ट्र निवडणूक निकाल'},
  {url:'/hindi/57',title:'हिन्दी समाचार'}];
 const file=bookmarks(rows,'https://preview.example');
 assert.equal(file.count,3);
 assert.match(file.html,/^<!DOCTYPE NETSCAPE-Bookmark-file-1>/);
 assert.match(file.html,/charset=UTF-8/);
 assert.match(file.html,/HREF="https:\/\/www\.politicshub\.in\/india\/42"/);
 assert.match(file.html,/HREF="https:\/\/www\.politicshub\.in\/#\/article\/17"/);
 assert.match(file.html,/Budget &amp; policy &lt;script&gt;/);
 assert.match(file.html,/महाराष्ट्र निवडणूक निकाल/);
 assert.doesNotMatch(file.html,/<script|fixture-private|preview\.example|ADD_DATE/i);
});

test('bookmark export rejects private/external routes and omits article/source/date data',()=>{
 const {bookmarks}=require('../public/assets/reading-list.js');
 const good={...story(),source:'private-source-marker',article:'article-body-marker',published_at:'publication-date-marker'};
 const rows=[good,...['javascript:alert(1)','/admin/','/newsletter/confirm?token=fixture',
  'https://evil.example/india/42','https://user:fixture@www.politicshub.in/india/42'].map(url=>({url,title:'Unsafe'}))];
 const before=JSON.stringify(rows),file=bookmarks(rows,origin);
 assert.equal(file.count,1);assert.equal(JSON.stringify(rows),before);
 assert.doesNotMatch(file.html,/private-source-marker|article-body-marker|publication-date-marker|Unsafe|evil\.example/);
 assert.deepEqual(bookmarks([],origin),{html:'',count:0});
 assert.deepEqual(bookmarks(null,origin),{html:'',count:0});
});

test('bookmark export is deduplicated and bounded without changing the reading list',()=>{
 const {bookmarks}=require('../public/assets/reading-list.js');
 const rows=[story(1),story(1),...Array.from({length:120},(_,i)=>story(i+2))];
 const original=JSON.stringify(rows),file=bookmarks(rows,origin);
 assert.equal(file.count,99);assert.equal((file.html.match(/<DT><A /g)||[]).length,99);
 assert.equal(JSON.stringify(rows),original);
 const storage=memory(),list=create(storage,origin,()=>false);storage.setItem(KEY,JSON.stringify(rows));
 assert.equal(bookmarks(list.read(),origin).count,0);assert.equal(storage.getItem(KEY),original);
});
