(()=>{"use strict";
const el=id=>document.getElementById(id);
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
let last=0,busy=false;const INTERVAL=20*60*1000;
function date(s){if(!s)return"दिनांक उपलब्ध नाही";const d=new Date(s);return isNaN(d)?"दिनांक उपलब्ध नाही":new Intl.DateTimeFormat("mr-IN",{timeZone:"Asia/Kolkata",day:"numeric",month:"short",year:"numeric",hour:"numeric",minute:"2-digit"}).format(d)}
function card(r){let u;try{u=new URL(r.url)}catch(_){return""}if(u.protocol!=="https:")return"";
return '<article class="mh-card"><div><div class="mh-card-meta"><span class="mh-card-source">'+esc(r.source_name||"वृत्तस्रोत")+'</span><time>'+esc(date(r.published_at))+'</time></div><h3>'+esc(r.title)+'</h3></div><div class="mh-card-actions"><a class="mh-card-link" href="'+esc(u.href)+'" target="_blank" rel="nofollow noopener noreferrer">मूळ बातमी वाचा ↗</a><button type="button" data-share-title="'+esc(r.title)+'" data-share-url="'+esc(u.href)+'" aria-haspopup="dialog">शेअर ↗</button></div></article>'}
async function fetchNews(force=false){if(busy)return;if(!force&&Date.now()-last<INTERVAL)return;busy=true;el("mhRefresh").disabled=true;el("mhFeed").setAttribute("aria-busy","true");
try{const response=await fetch("/api/maharashtra",{cache:"no-store",headers:{"Accept":"application/json"},signal:AbortSignal.timeout(18000)});if(!response.ok)throw Error("Feed unavailable");const data=await response.json();if(!Array.isArray(data.items))throw Error("Bad data");
const safe=data.items.filter(x=>x&&/[\u0900-\u097f]/.test(x.title||"")).slice(0,100);el("mhFeed").innerHTML=safe.length?safe.map(card).join(""):'<p class="mh-empty">या वेळी थेट मराठी RSS मधून नवीन बातम्या मिळाल्या नाहीत. खाली जुन्या निवडणूक नोंदी वेगळ्या दाखवल्या आहेत.</p>';
el("mhCount").textContent=new Intl.NumberFormat("mr-IN").format(safe.length)+" बातम्या";
const live=safe.length>0;el("mhSignal").className="mh-signal "+(live?"ok":"warn");el("mhStatus").textContent=live?"स्रोतांकडून बातम्या मिळाल्या":"वृत्तस्रोत सध्या उपलब्ध नाहीत";
el("mhChecked").textContent="शेवटची तपासणी: "+date(data.last_checked);
for(const [key,id] of [["TV9 Marathi","tv9Source"],["ABP माझा","abpSource"]])el(id).textContent=data.sources?.[key]?.available?"· सक्रिय":"· तपासणी अयशस्वी";last=Date.now();
}catch(e){el("mhSignal").className="mh-signal warn";el("mhStatus").textContent="आत्ता फीड मिळत नाही; पुन्हा प्रयत्न करता येईल";el("mhFeed").innerHTML='<p class="mh-empty">वृत्तस्रोतांची तपासणी अयशस्वी झाली. याचा अर्थ नवीन बातमी नाही असा नाही.</p>'}
finally{busy=false;el("mhRefresh").disabled=false;el("mhFeed").setAttribute("aria-busy","false")}}
async function archive(){try{const r=await fetch("/maharashtra-seed.json",{cache:"force-cache"});if(r.ok){const data=await r.json();el("mhArchive").innerHTML=data.map(card).join("")}}catch(_){}}
el("mhRefresh").addEventListener("click",()=>fetchNews(true));setInterval(()=>{if(!document.hidden)fetchNews()},INTERVAL);document.addEventListener("visibilitychange",()=>{if(!document.hidden)fetchNews()});addEventListener("online",()=>fetchNews(true));
archive();fetchNews(true);
})();
