(()=>{
const list=document.getElementById('examNotices'),status=document.getElementById('examStatus'),sourcesBox=document.getElementById('examSources'),retry=document.getElementById('examRetry');let payload=null,loading=false;
function link(url,text,hosts){try{const u=new URL(url);if(u.protocol!=='https:'||!hosts.some(h=>u.hostname===h||u.hostname.endsWith('.'+h)))return document.createTextNode(text);const a=document.createElement('a');a.href=u.href;a.textContent=text;a.target='_blank';a.rel='noopener noreferrer';return a}catch{return document.createTextNode(text)}}
function render(){if(!payload)return;const q=document.getElementById('examQuery').value.trim().toLowerCase(),region=document.getElementById('examRegion').value;const tokens=q.split(/\s+/).filter(Boolean);const rows=payload.items.filter(r=>(region==='all'||r.exam_region===region)&&tokens.every(t=>(r.title+' '+r.source_name+' '+r.summary).toLowerCase().includes(t)));list.replaceChildren();for(const r of rows){const source=payload.sources.find(s=>s.id===r.exam_authority);if(!source)continue;const article=document.createElement('article');article.className='source-reference';const title=document.createElement('h2');title.append(link(r.url,r.title,source.allowed_hosts));const p=document.createElement('p');p.textContent=r.source_name+' · '+(r.published_at?'Official notice date: '+new Date(r.published_at).toLocaleDateString('en-IN'):'Publication date not provided on the source listing');const n=document.createElement('small');n.textContent='News No. '+r.news_number+' · Original official notice';article.append(title,p,n);list.append(article)}status.textContent=rows.length+' official notices match. Collection checked '+new Date(payload.checked_at).toLocaleString('en-IN')+'. Check the original document for current deadlines.';if(!rows.length){const p=document.createElement('p');p.textContent='No collected notices match. Check the official authority links below; a source may be unavailable to the collector.';list.append(p)}}
function renderSources(){sourcesBox.replaceChildren();for(const s of payload.sources){const card=document.createElement('article');card.className='source-reference';const h=document.createElement('h3');h.append(link(s.url,s.name,s.allowed_hosts));const p=document.createElement('p');p.textContent=s.scope;const state=document.createElement('p');state.textContent=s.status==='available'?'Official listing checked; '+s.notice_count+' notice links collected.':s.status==='no_extractable_notices'?'Official site reachable, but no usable notice links could be extracted. Open the official website.':'Collection unavailable; use the official website. Saved notices, if any, are retained.';const date=document.createElement('small');date.textContent='Last successful collection: '+(s.last_success_at?new Date(s.last_success_at).toLocaleString('en-IN'):'Not recorded');card.append(h,p,state,date);sourcesBox.append(card)}}
document.getElementById('examFilters').onsubmit=e=>{e.preventDefault();render()};document.getElementById('examRegion').onchange=render;document.getElementById('examQuery').oninput=render;
async function load(){
 if(loading)return;
 const restoreFocus=document.activeElement===retry;
 loading=true;retry.hidden=true;retry.disabled=true;list.setAttribute('aria-busy','true');status.textContent='Loading official notices…';
 try{
  const response=await fetch('/api/exams',{signal:AbortSignal.timeout(15000)});if(!response.ok)throw Error();
  const data=await response.json();
  if(!data||!Array.isArray(data.items)||!Array.isArray(data.sources)||typeof data.checked_at!=='string'||!Number.isFinite(Date.parse(data.checked_at)))throw Error();
  payload=data;render();renderSources();
 }catch{
  payload=null;list.replaceChildren();
  status.textContent='Official notices are temporarily unavailable. Retry or use the official authority links below.';retry.hidden=false;
 }finally{
  loading=false;retry.disabled=false;list.setAttribute('aria-busy','false');
  if(restoreFocus&&document.activeElement===document.body)(retry.hidden?status:retry).focus();
 }
}
retry.addEventListener('click',load);load();
})();
