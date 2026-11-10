const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const read=path=>fs.readFileSync(path,'utf8');
test('private QA dashboard is wired only into the authenticated admin room',()=>{
 const admin=read('public/admin/index.html'),home=read('public/index.html');
 const code=read('public/assets/admin-quality.js');
 const server=read('api/index.py');
 assert.match(admin,/id="qualitySnapshotPanel"/);
 assert.match(admin,/\/assets\/admin-quality\.js\?v=quality1/);
 assert.doesNotMatch(home,/qualitySnapshotPanel|admin-quality\.js/);
 assert.match(code,/\/api\/admin\/content-quality/);
 assert.match(code,/shell\.classList\.contains\('hidden'\)/);
 assert.doesNotMatch(code,/localStorage|sessionStorage|innerHTML\s*=/);
 assert.match(server,/@app\.get\("\/api\/admin\/content-quality"\)/);
 assert.match(server,/def admin_content_quality\(\):\n err=require_admin\(\)/);
 new vm.Script(code);
});
