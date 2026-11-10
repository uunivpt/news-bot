const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
test('official exam deadline tracker never invents a deadline from a notice headline',()=>{
 const js=fs.readFileSync('public/assets/exams.js','utf8');
 const html=fs.readFileSync('public/exams/index.html','utf8');
 assert.match(html,/id="examDeadlineTracker"/);
 assert.match(html,/id="examStage"/);
 assert.match(html,/id="examVerifiedOnly"/);
 assert.match(js,/row\.deadline_at/);
 assert.match(js,/row\.deadline_source_url/);
 assert.match(js,/permitted\(evidence,source\?\.allowed_hosts\)/);
 assert.match(js,/No upcoming deadlines have verified date metadata/);
 assert.doesNotMatch(js,/innerHTML\s*=/);
});
