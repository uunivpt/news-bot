(()=>{
'use strict';
const list=document.getElementById('examNotices'),status=document.getElementById('examStatus'),
 sourcesBox=document.getElementById('examSources'),retry=document.getElementById('examRetry'),
 tracker=document.getElementById('deadlineTrackerList'),trackerStatus=document.getElementById('deadlineTrackerStatus');
let payload=null,loading=false;
const STAGES={application:/registration|application|apply|inviting|admission|अर्ज|नोंदणी|आवेदन/i,
 admit:/admit\s*cards?|hall\s*tickets?|प्रवेशपत्र/i,
 result:/results?|scores?|merit\s*list|निकाल|परिणाम/i,
 schedule:/timetables?|schedules?|exam(?:ination)?\s*dates?|वेळापत्रक/i,
 deadline:/last\s*date|closing\s*date|deadline|extension\s*of\s*date|अंतिम\s*तिथि|अंतिम\s*दिनांक|मुदतवाढ/i};
function stage(row){const title=String(row.title||'');for(const [type,re] of Object.entries(STAGES))if(re.test(title))return type;return 'notice'}
function stageMatches(row,value){return value==='all'||(STAGES[value]||/$^/).test(String(row.title||''))}
function permitted(url,hosts){try{const u=new URL(String(url));return u.protocol==='https:'&&Array.isArray(hosts)&&hosts.some(h=>u.hostname===h||u.hostname.endsWith('.'+h))}catch{return false}}
function link(url,text,hosts){if(!permitted(url,hosts))return document.createTextNode(String(text||''));const a=document.createElement('a');a.href=url;a.textContent=text;a.target='_blank';a.rel='noopener noreferrer';return a}
function fmt(value){if(!value)return '';const dt=new Date(value);return Number.isFinite(dt.getTime())?dt.toLocaleDateString('en-IN',{day:'numeric',month:'short',year:'numeric',timeZone:'Asia/Kolkata'}):''}
function officialDeadline(row,source){const raw=String(row.deadline_at||'');const evidence=String(row.deadline_source_url||'');if(!/^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}.*)?$/.test(raw)||!permitted(evidence,source?.allowed_hosts))return null;const dt=new Date(raw);return Number.isFinite(dt.getTime())?dt:null}
function renderTracker(){
 tracker.replaceChildren();if(!payload)return;
 const deadlineRows=payload.items.filter(r=>stageMatches(r,'deadline')).sort((a,b)=>Date.parse(b.published_at||0)-Date.parse(a.published_at||0)).slice(0,8);
 const verified=payload.items.filter(r=>{const src=payload.sources.find(s=>s.id===r.exam_authority);return officialDeadline(r,src)&&officialDeadline(r,src).getTime()>=Date.now()});
 trackerStatus.textContent=verified.length?verified.length+' upcoming dates have explicit official-source evidence; other notices need PDF verification.':'No upcoming deadlines have verified date metadata. These notices may contain important changes—check the official documents.';
 for(const r of (verified.length?verified.slice(0,8):deadlineRows)){
  const src=payload.sources.find(s=>s.id===r.exam_authority);if(!src)continue;
  const li=document.createElement('li'),date=officialDeadline(r,src);
  const label=document.createElement('strong');label.textContent=date?'Official deadline: '+fmt(date):'Deadline date: check original notice';
  li.append(label,document.createTextNode(' · '),link(r.url,r.title,src.allowed_hosts));tracker.append(li);
 }
 if(!tracker.childElementCount){const li=document.createElement('li');li.textContent='No matching closing-date notices were collected. Use the official authority links below.';tracker.append(li)}
}
function render(){
 if(!payload)return;
 const q=document.getElementById('examQuery').value.trim().toLowerCase(),region=document.getElementById('examRegion').value,
  kind=document.getElementById('examStage').value,onlyVerified=document.getElementById('examVerifiedOnly').checked;
 const tokens=q.split(/\s+/).filter(Boolean);
 const rows=payload.items.filter(r=>{
  const src=payload.sources.find(s=>s.id===r.exam_authority);
  return src&&(region==='all'||r.exam_region===region)&&stageMatches(r,kind)&&(!onlyVerified||!!officialDeadline(r,src))&&
   tokens.every(t=>(String(r.title||'')+' '+String(r.source_name||'')+' '+String(r.summary||'')).toLowerCase().includes(t))
 });
 list.replaceChildren();
 for(const r of rows){
  const source=payload.sources.find(s=>s.id===r.exam_authority);if(!source)continue;
  const card=document.createElement('article');card.className='source-reference';
  const title=document.createElement('h2');title.append(link(r.url,r.title,source.allowed_hosts));
  const type=document.createElement('span');type.className='exam-stage';type.textContent=stage(r).toUpperCase();
  const p=document.createElement('p');p.textContent=r.source_name+' · '+(fmt(r.published_at)?'Official notice date: '+fmt(r.published_at):'Publication date not provided on source listing');
  const deadline=officialDeadline(r,source);const info=document.createElement('small');
  info.textContent=deadline?'Official deadline: '+fmt(deadline):'Deadline not independently confirmed in this listing · Open official notice';
  card.append(type,title,p,info);list.append(card)
 }
 const stale=payload.sources.filter(s=>s.status!=='available').length;
 status.textContent=rows.length+' official notices match. Collection checked '+fmt(payload.checked_at)+'. '+stale+' authorities currently need manual source checks. Always verify dates in the original document.';
 if(!rows.length){const p=document.createElement('p');p.textContent=onlyVerified?'No verified deadline dates are available in the collected metadata. Disable the filter or consult official notices.':'No collected notices match. Check the authority links below.';list.append(p)}
}
function renderSources(){
 sourcesBox.replaceChildren();
 for(const s of payload.sources){
  const card=document.createElement('article');card.className='source-reference';
  const h=document.createElement('h3');h.append(link(s.url,s.name,s.allowed_hosts));
  const p=document.createElement('p');p.textContent=s.scope;
  const state=document.createElement('p');
  state.textContent=s.status==='available'?'Official listing checked; '+s.notice_count+' notice links collected.':s.status==='no_extractable_notices'?'Official site reachable, but notice links could not be verified. Open the official website.':'Source collection unavailable; use the official website. Previously saved notices may be shown.';
  const last=document.createElement('small');last.textContent='Last successful collection: '+(s.last_success_at?fmt(s.last_success_at):'Not recorded');
  card.append(h,p,state,last);sourcesBox.append(card)
 }
}
document.getElementById('examFilters').onsubmit=e=>{e.preventDefault();render()};
for(const id of ['examRegion','examStage','examVerifiedOnly'])document.getElementById(id).onchange=render;
document.getElementById('examQuery').oninput=render;
async function load(){
 if(loading)return;
 const restoreFocus=document.activeElement===retry;loading=true;retry.hidden=true;retry.disabled=true;
 list.setAttribute('aria-busy','true');status.textContent='Loading official notices…';
 try{
  const response=await fetch('/api/exams',{signal:AbortSignal.timeout(15000)});if(!response.ok)throw Error('unavailable');
  const data=await response.json();
  if(!data||!Array.isArray(data.items)||!Array.isArray(data.sources)||typeof data.checked_at!=='string'||!Number.isFinite(Date.parse(data.checked_at)))throw Error('invalid');
  payload=data;render();renderSources();renderTracker()
 }catch{
  payload=null;list.replaceChildren();tracker.replaceChildren();
  status.textContent='Official notices are temporarily unavailable. Retry or use the official authority links below.';
  trackerStatus.textContent='Live deadline notices are unavailable. Verify dates on the official authority websites.';retry.hidden=false
 }finally{loading=false;retry.disabled=false;list.setAttribute('aria-busy','false');if(restoreFocus&&document.activeElement===document.body)(retry.hidden?status:retry).focus()}
}
retry.addEventListener('click',load);load();
})();
