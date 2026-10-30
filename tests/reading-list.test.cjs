const {test}=require('node:test');
const assert=require('node:assert/strict');
const {KEY,MAX_ITEMS,clean,create}=require('../public/assets/reading-list.js');
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
