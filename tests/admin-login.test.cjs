const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const source=fs.readFileSync('public/admin.js','utf8');
const prefix=source.slice(0,source.indexOf('function action('));

function harness(response) {
  const requests=[];
  const ctx=vm.createContext({AbortSignal,DOMException,setTimeout,clearTimeout,fetch:async(url,options)=>{
    requests.push({url,options}); return response;
  }});
  vm.runInContext(prefix,ctx);
  return {ctx,requests};
}
test('admin API rejects successful tunnel HTML instead of treating it as login success',async()=>{
  const {ctx}=harness({ok:true,status:200,json:async()=>{throw new Error('HTML')}});
  await assert.rejects(vm.runInContext("api('/api/admin/login',{method:'POST'})",ctx),/invalid response/);
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
