/* Private, read-only public-feed QA panel. No credentials or drafts in the DOM. */
(function(){
'use strict';
const $=id=>document.getElementById(id);
const shell=$('shell'),summary=$('qualitySnapshotMetrics'),issues=$('qualitySnapshotIssues'),
 exams=$('qualitySnapshotExams'),status=$('qualitySnapshotStatus'),refresh=$('qualitySnapshotRefresh');
if(!shell||!summary||!issues||!exams||!status||!refresh)return;
let sequence=0;
function clear(){
 sequence++;summary.replaceChildren();issues.replaceChildren();exams.replaceChildren();
 status.textContent='';refresh.disabled=false;
}
function line(container,title,detail){
 const item=document.createElement('div');item.className='source-health-row';
 const heading=document.createElement('strong');heading.textContent=title;
 const copy=document.createElement('p');copy.className='muted';copy.textContent=detail;
 item.append(heading,copy);container.append(item);
}
function card(label,value,detail){
 const el=document.createElement('div');el.className='card metric';
 const small=document.createElement('small');small.textContent=label;
 const strong=document.createElement('strong');strong.textContent=String(value??'—');
 const info=document.createElement('span');info.textContent=detail;
 el.append(small,strong,info);summary.append(el)
}
function render(data){
 const n=data.news||{},e=data.exams||{};
 summary.replaceChildren();issues.replaceChildren();exams.replaceChildren();
 card('Source-linked briefs',n.source_briefs,'Not independently verified long-form articles');
 card('500+ word articles',n.longform_500_plus,'Current public-feed sample only');
 card('Rights-cleared images',n.with_image,String(n.total??0)+' current news reports');
 card('Source-link review',n.unsafe_or_missing_source_link,'Missing or invalid HTTPS URLs');
 card('Exam sources checked',e.available,String(e.authorities??0)+' configured authorities');
 card('Exam sources needing review',e.needs_manual_review,'Unreachable or stale collection evidence');
 const problems=Array.isArray(data.sample_issues)?data.sample_issues:[];
 for(const item of problems.slice(0,8)){
   line(issues,String(item.title||'Untitled report'),(Array.isArray(item.flags)?item.flags:[]).join(' · '))
 }
 if(!problems.length)line(issues,'No flagged sample stories','This does not verify facts or originality.');
 const flagged=Array.isArray(e.issues)?e.issues:[];
 for(const item of flagged.slice(0,11))line(exams,String(item.name||'Authority'),String(item.status||'unknown')+' · Last success: '+String(item.last_success_at||'not recorded'));
 if(!flagged.length)line(exams,'No stale or unavailable source listed','Check individual notices at the original authority.');
 status.textContent=String(data.scope||'Current public data')+' · Checked '+(data.checked_at?new Date(data.checked_at).toLocaleString('en-IN',{timeZone:'Asia/Kolkata'}):'now')+'.';
}
async function load(){
 if(shell.classList.contains('hidden')||refresh.disabled)return;
 const current=++sequence;refresh.disabled=true;status.textContent='Checking currently published sources…';
 try{
  const data=await api('/api/admin/content-quality');
  if(current!==sequence||shell.classList.contains('hidden'))return;
  render(data);
 }catch(error){
  if(current===sequence&&!shell.classList.contains('hidden'))status.textContent='Quality checks unavailable: '+String(error?.message||'retry');
 }finally{if(current===sequence)refresh.disabled=false}
}
refresh.addEventListener('click',load);
new MutationObserver(()=>{if(shell.classList.contains('hidden'))clear();else load()}).observe(shell,{attributes:true,attributeFilter:['class']});
if(!shell.classList.contains('hidden'))load();
})();
