const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

test('reset filters cancels a pending search so it cannot clear a later bulk selection',()=>{
  const lines=fs.readFileSync('public/admin.js','utf8').split('\n');
  const handlers=lines.filter(line=>line.startsWith("$('search').oninput =")||line.startsWith("$('resetFilters').onclick =")).join('\n');
  const elements=Object.fromEntries(['search','resetFilters','category','source','status','review','sort'].map(id=>[id,{value:'filtered'}]));
  const timers=new Map(), selected=new Set();
  let loads=0;
  const context=vm.createContext({
    $:id=>elements[id],newsSequence:0,newsController:null,newsTimer:null,queue:'filtered',
    document:{querySelectorAll:()=>[]},
    setTimeout:callback=>{timers.set(42,callback);return 42},
    clearTimeout:id=>timers.delete(id),
    loadNews:()=>{loads++;selected.clear()}
  });
  vm.runInContext(handlers,context);
  elements.search.oninput();
  assert.equal(timers.size,1);
  elements.resetFilters.onclick();
  assert.equal(elements.search.value,'');
  assert.equal(loads,1);
  selected.add(123);
  for(const callback of timers.values())callback();
  assert.equal(loads,1,'a delayed search must not refresh the reset list again');
  assert.deepEqual([...selected],[123],'the reader’s new selection must remain intact');
});
