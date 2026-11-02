const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const source=fs.readFileSync('public/admin.js','utf8');
const prefix=source.slice(0,source.indexOf('function action('));

function harness(response) {
  const requests=[];
  const ctx=vm.createContext({AbortSignal,DOMException,setTimeout,clearTimeout,fetch:async(url,options)=>{
    requests.push({url,options}); return typeof response==='function'?response(requests.length):response;
  }});
  vm.runInContext(prefix,ctx);
  return {ctx,requests};
}
test('admin API rejects successful tunnel HTML instead of treating it as login success',async()=>{
  const {ctx}=harness({ok:true,status:200,json:async()=>{throw new Error('HTML')}});
  await assert.rejects(vm.runInContext("api('/api/admin/login',{method:'POST'})",ctx),/invalid response/);
});
test('transient admin reads retry once while mutation and permission failures never retry',async()=>{
  let h=harness(number=>({ok:number===2,status:number===2?200:503,json:async()=>number===2?{ok:true}:{error:'Temporary phone failure'}}));
  assert.equal((await vm.runInContext("api('/api/admin/workspace')",h.ctx)).ok,true);
  assert.equal(h.requests.length,2);
  h=harness({ok:false,status:503,json:async()=>({error:'Temporary phone failure'})});
  await assert.rejects(vm.runInContext("api('/api/news/44/approve',{method:'POST'})",h.ctx),/Temporary/);
  assert.equal(h.requests.length,1);
  for (const status of [403,429]) {
    h=harness({ok:false,status,json:async()=>({error:'Access blocked'})});
    await assert.rejects(vm.runInContext("api('/api/admin/workspace')",h.ctx),/Access blocked/);
    assert.equal(h.requests.length,1);
  }
});
test('a cancelled admin read cannot retry',async()=>{
  const h=harness(()=>{throw new DOMException('Aborted','AbortError');});
  await assert.rejects(vm.runInContext("api('/api/admin/workspace')",h.ctx),/Aborted/);
  assert.equal(h.requests.length,1);
});
test('a network read failure has one bounded retry',async()=>{
  const h=harness(number=>{
    if (number===1) throw new TypeError('Failed to fetch');
    return {ok:true,status:200,json:async()=>({ok:true})};
  });
  assert.equal((await vm.runInContext("api('/api/admin/workspace')",h.ctx)).ok,true);
  assert.equal(h.requests.length,2);
});
test('admin API rejects null success and preserves actionable gateway errors',async()=>{
  let {ctx}=harness({ok:true,status:200,json:async()=>null});
  await assert.rejects(vm.runInContext("api('/api/admin/me')",ctx),/invalid response/);
  ({ctx}=harness({ok:false,status:503,json:async()=>({error:'Update and restart the Termux admin service'})}));
  await assert.rejects(vm.runInContext("api('/api/admin/login',{method:'POST'})",ctx),/Termux/);
});
test('login API always sends the same-origin cookie credentials',async()=>{
  const {ctx,requests}=harness({ok:true,status:200,json:async()=>({ok:true})});
  await vm.runInContext("api('/api/admin/login',{method:'POST'})",ctx);
  assert.equal(requests[0].options.credentials,'same-origin');
  assert.equal(requests[0].options.cache,'no-store');
});
test('array-valued activity history remains a valid admin read response',async()=>{
  const {ctx}=harness({ok:true,status:200,json:async()=>[{action:'news.edit'}]});
  const result=await vm.runInContext("api('/api/admin/activity')",ctx);
  assert.equal(result[0].action,'news.edit');
});
test('password acceptance cannot open the workspace when the session cookie is absent',async()=>{
  const signedIn=source.slice(source.indexOf('async function signedIn('),source.indexOf('function manualPayload('));
  let checks=0;
  const ctx=vm.createContext({api:async()=>{checks++;return {authenticated:false};},
    $:()=>{throw new Error('Workspace opened before authentication');}});
  vm.runInContext(signedIn,ctx);
  await assert.rejects(vm.runInContext('signedIn({ok:true,csrf_token:"login-token"})',ctx),/session could not be saved/);
  assert.equal(checks,1);
});
