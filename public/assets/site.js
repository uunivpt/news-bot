
const CATS=[['all','Home'],['maharashtra','Maharashtra'],['india','India'],['politics','Politics'],['world','World'],['hindi','Hindi']];
const TABS=[['all','All'],['maharashtra','Maharashtra'],['politics','Politics'],['india','India'],['world','World'],['hindi','Hindi']];
const ENDPOINTS={api:'/api/news?category=all&limit=120',item:'/api/news/',search:'/api/search',snap:'/news-data.json',hindi:'/api/hindi-feed'};
// Editorially verified one-off story stays visible even during a DB quota outage.
const MUSK_STARLINK={id:'202610090923',title:'Elon Musk targets Mukesh Ambani over Starlink India launch delay',category:'india',source:'PoliticsHub News Desk / Reuters',source_name:'PoliticsHub News Desk',date:'2026-10-09T23:23:00+05:30',published_at_site:'2026-10-09T23:23:00+05:30',summary:'In a sarcastic X post, Elon Musk called Mukesh Ambani “Prime Minister Ambani” and alleged obstacles to Starlink. India denies favouritism, citing mandatory security and spectrum approvals.',image:'',url:'https://www.reuters.com/business/media-telecom/india-rejects-monopoly-claim-after-musk-accuses-ambani-blocking-starlink-launch-2026-10-09/',editorial_pick:true};
const NANA_TRIBUTE={id:'nana-tribute',title:'Nana Patekar dies at 75 in Goa, leaving a lasting cinema legacy',category:'india',source:'Reuters / AP',source_name:'Reuters',date:'2026-10-08T06:00:00+05:30',published_at_site:'2026-10-08T06:00:00+05:30',summary:'Veteran actor Nana Patekar died in Goa on 8 October 2026, aged 75. His celebrated films included Parinda, Krantiveer, Ab Tak Chhappan and Natsamrat.',image:'',url:'https://www.reuters.com/business/media-telecom/bollywood-actor-nana-patekar-dies-75-2026-10-08/',is_breaking:true};

const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ls={get:k=>{try{return localStorage.getItem(k)}catch(e){return null}},set:(k,v)=>{try{localStorage.setItem(k,v)}catch(e){}},del:k=>{try{localStorage.removeItem(k)}catch(e){}}};
const CONSENT_KEY='ph-consent-v1';
function consentMode(){return ls.get(CONSENT_KEY)||''}
function preferencesAllowed(){return consentMode()==='preferences'}
function clearOptionalStorage(){[CACHE_KEY,...LEGACY_CACHE_KEYS,'ph-theme','ph-cookie','ph-ls','ph-reading-list-v1'].forEach(ls.del);window.dispatchEvent(new Event('ph-preferences-cleared'))}
function setConsent(mode){
 const value=mode==='preferences'?'preferences':'essential';
 ls.set(CONSENT_KEY,value);
 if(value!=='preferences')clearOptionalStorage();
 document.querySelector('#privacyConsent')?.remove();
 if(document.documentElement.dataset.theme==='dark'&&!preferencesAllowed())theme('light');
 if(location.hash.startsWith('#/settings'))settings('prefs');
}
function showConsentBanner(force=false){
 if(!force&&consentMode())return;
 document.querySelector('#privacyConsent')?.remove();
 const box=document.createElement('section');box.id='privacyConsent';box.className='privacy-consent';box.setAttribute('role','dialog');box.setAttribute('aria-label','Privacy choices');
 box.innerHTML='<div><strong>Privacy choices</strong><p>PoliticsHub.in uses essential storage for your privacy choice. Optional browser storage can remember theme and cache recent stories. Google AdSense is used on news pages. These buttons control site preferences; see the Cookie Policy for advertising choices.</p><a href="/cookies.html">Cookie Policy</a> · <a href="/privacy.html">Privacy Policy</a></div><div class="privacy-actions"><button type="button" class="btn secondary" data-consent-choice="essential">Essential only</button><button type="button" class="btn" data-consent-choice="preferences">Allow preferences</button></div>';
 document.body.append(box);
}
document.addEventListener('click',e=>{const b=e.target.closest('[data-consent-choice]');if(b)setConsent(b.dataset.consentChoice);if(e.target.closest('[data-open-consent]')){e.preventDefault();showConsentBanner(true)}});

const S={items:[],mode:'loading',api:'unknown',snap:'unknown',tried:0};
const dt=d=>{const raw=String(d||'').trim().replace(/\s*[·•]\s*/g,' ').replace(/\s+/g,' ');const x=new Date(raw);return isNaN(x)?null:x};
const ts=d=>dt(d)?.getTime()||0;
const fmt=d=>{const x=dt(d);return !x?'':x.toLocaleString('en-IN',{day:'numeric',month:'short',year:'numeric',hour:'numeric',minute:'2-digit'})};
const ago=d=>{const x=dt(d);if(!x)return'';const m=(Date.now()-x)/6e4;if(m<0)return fmt(d);return m<60?Math.max(1,Math.floor(m))+'m ago':m<1440?Math.floor(m/60)+'h ago':fmt(d).split(',')[0]};
function newsCategory(category,title,summary){
 const raw=String(category||'india').trim().toLowerCase();
 const text=String(title||'')+' '+String(summary||'');
 if(/\bnana\s+patekar\b/i.test(text))return'india';
 if(['entertainment','business','technology','sports','science','health'].includes(raw)){
  if(/\b(?:elections?|vot(?:e|es|ing)|polling|ballot|politic(?:s|al|ian)|parliament|lok sabha|rajya sabha|assembly|bjp|congress|cabinet|coalition|prime minister|chief minister|minister|opposition|manifesto)\b|चुनाव|राजनीति|संसद|विधानसभा|प्रधानमंत्री|मुख्यमंत्री/i.test(text))return'politics';
  if(/\b(?:hollywood|oscars?|grammys?|k[- ]?pop|korea|china|japan|united states|usa|american|british|united kingdom|london|europe|russia|ukraine|israel|gaza|iran|france|germany|canada|australia|international|global|world)\b|अमेरिका|ब्रिटेन|चीन|रूस|यूक्रेन|दुनिया|विदेश/i.test(text)
     && !/\b(?:india|indian|bollywood|marathi|maharashtra|hindi cinema|indian cinema|telugu cinema|tamil cinema|malayalam cinema|bengali cinema|padma shri|padma bhushan|deepika|ranveer)\b|भारत|भारतीय|महाराष्ट्र|बॉलीवुड|मुंबई|दिल्ली/i.test(text))return'world';
  return'india';
 }
 return raw||'india';
}
function norm(a,i){const id=a.id??a.slug??a._id??'n'+i;const img=a.image||a.image_url||a.imageUrl||a.urlToImage||a.thumbnail||a.img||'';
 return{...a,id:String(id),title:a.title||a.headline||'Untitled',summary:a.summary||a.description||a.excerpt||'',body:a.article||a.bot_article||a.content||a.body||a.text||'',image:typeof img==='string'?img:'',category:newsCategory(a.category||a.section||'General',a.title||a.headline,a.summary||a.description||a.excerpt),source:(a.source&&a.source.name)||a.source||a.publisher||'',date:a.published_at_iso||a.publishedAt||a.pubDate||a.date||a.published_at||a.created_at||'',url:a.url||a.link||'',author:a.author||a.author_name||'PoliticsHub Editorial Desk'}}
const pick=j=>Array.isArray(j)?j:(j.articles||j.news||j.items||j.data||j.results||[]);
async function get(u,options={}){const deadline=AbortSignal.timeout(10000);const signal=options.signal?AbortSignal.any([options.signal,deadline]):deadline;const r=await fetch(u,{signal,cache:'default',headers:{'Accept':'application/json'}});if(!r.ok)throw Error('News request failed');if(u===ENDPOINTS.api)S.apiMode=r.headers.get('X-News-Mode')||'live';const rows=pick(await r.json());if(!Array.isArray(rows))throw Error('Invalid news response');return rows.filter(x=>x&&typeof x==='object'&&!Array.isArray(x)).map((x,i)=>{const img=x.image_url||x.image||x.imageUrl||x.urlToImage||x.thumbnail||x.img||'';const source=x.source_name||(x.source&&x.source.name)||x.source||x.publisher||'PoliticsHub';const date=x.published_at_iso||x.published_at_site||x.publishedAt||x.pubDate||x.date||x.published_at||x.created_at||'';const body=x.article||x.bot_article||x.content||x.body||x.text||'';const summary=x.summary||x.bot_summary||x.description||x.excerpt||'';return {...x,title:String(x.title||x.headline||'Untitled'),category:newsCategory(x.category||x.section||'india',x.title||x.headline,summary),id:String(x.id??x.slug??x._id??'n'+i),image:typeof img==='string'?img:'',source:String(source),date,body:String(body),summary:String(summary)};})}
const CACHE_KEY='ph-news-cache';
const LEGACY_CACHE_KEYS=['ph-news-cache-v6','ph-news-cache-v5','ph-news-cache-v4'];
function cacheSave(items){if(!preferencesAllowed())return;try{localStorage.setItem(CACHE_KEY,JSON.stringify({ts:Date.now(),items}));}catch(e){}}
function cacheLoad(){
 if(!preferencesAllowed())return null;
 try{
  const keys=[CACHE_KEY,...LEGACY_CACHE_KEYS];
  for(const key of keys){
   const x=JSON.parse(localStorage.getItem(key)||'null');
   if(x&&Array.isArray(x.items)&&x.items.length){
    if(key!==CACHE_KEY)cacheSave(x.items);
    return x;
   }
  }
 }catch(e){}
 return null
}
function slugify(value){
 return String(value||'').toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-+|-+$/g,'').slice(0,110)||'story';
}
function ck(item){
 const raw=typeof item==='string'?item:(item?.category||item?.section||'all');
 const key=String(raw).toLowerCase().trim();
 if(key.includes('maharashtra'))return'maharashtra';
 if(key.includes('politic'))return'politics';
 if(key.includes('india'))return'india';
 if(key.includes('world')||key.includes('international'))return'world';
 if(key.includes('business')||key.includes('econom'))return'business';
 if(key.includes('tech'))return'technology';
 if(key.includes('sport'))return'sports';
 if(key.includes('entertain'))return'india';
 if(key.includes('science'))return'science';
 if(key.includes('health'))return'health';
 if(key.includes('hindi'))return'hindi';
 return'all';
}
function inCat(item,cat){return cat==='all'||ck(item)===cat}
function hl(cat){return cat&&cat!=='all'?'/'+encodeURIComponent(cat)+'/':'/'}
function articleHref(item){
 if(String(item?.id??'')==='202610090923')return '/elon-musk-ambani-starlink.html';
 if(String(item?.id??'')==='nana-tribute')return '/nana-patekar-tribute.html';
 const id=String(item?.id??'').trim();
 if(!/^[0-9]+$/.test(id))return '/#/article/'+encodeURIComponent(id);
 const category=ck(item);
 return '/'+(['all','maharashtra'].includes(category)?'india':category)+'/'+id+'-'+slugify(item?.title||'story');
}
function safeSourceUrl(value){try{const url=new URL(value,location.origin);return /^https?:$/.test(url.protocol)?url.href:'#'}catch(_){return '#'}}
function img(item){
 const src=String(item?.image||'').trim();
 if(!src)return'';
 const safe=src.startsWith('/')||src.startsWith('http://')||src.startsWith('https://');
 if(!safe)return'';
 return '<img src="'+esc(src)+'" alt="" loading="lazy" decoding="async">';
}
function card(item){
 const k=ck(item),title=String(item?.title||'Untitled'),summary=String(item?.summary||'').trim();
 return '<a class="card '+(item?.image?'im':'tx')+' rv" data-k="'+k+'" href="'+esc(articleHref(item))+'" aria-label="'+esc(title)+'">'+
 (item?.image?img(item):'')+
 '<span class="chip stk">'+esc(item?.category||k)+'</span>'+
 '<span class="go" aria-hidden="true">↗</span>'+
 '<h3>'+esc(title)+'</h3>'+
 (summary?'<p>'+esc(summary)+'</p>':'')+
 '<span class="m">'+esc(item?.source||'PoliticsHub')+' · '+esc(ago(item?.date))+'</span></a>';
}
function setActive(cat){
 const key=cat||'all';
 $$('nav.main a').forEach(a=>a.classList.toggle('on',a.dataset.k===key));
 $$('#dl a.l').forEach(a=>a.classList.toggle('on',a.dataset.k===key));
 moveInd();
}
function moveInd(){
 const nav=$('nav.main'),ind=$('#ind');
 if(!nav||!ind)return;
 const active=$('nav.main a.on');
 if(!active){ind.style.width='0';return}
 const nr=nav.getBoundingClientRect(),ar=active.getBoundingClientRect();
 ind.style.left=(ar.left-nr.left)+'px';
 ind.style.width=ar.width+'px';
 ind.style.background='var(--k)';
}
function build(){
 const nav=$('nav.main'),drawer=$('#dl');
 if(nav)nav.innerHTML='<span id="ind" aria-hidden="true"></span>'+CATS.map(([k,l])=>'<a href="'+hl(k)+'" data-k="'+k+'">'+l+'</a>').join('');
 if(drawer)drawer.innerHTML=CATS.map(([k,l])=>'<a class="l" href="'+hl(k)+'" data-k="'+k+'">'+l+'</a>').join('')+'<a class="l" href="/sources.html">Sources & references</a><a class="l" href="/saved.html">Saved stories</a><a class="l" href="/archive/">Full archive</a>';
 const y=$('#yr');if(y)y.textContent=new Date().getFullYear();
}
function ticker(){
 const box=$('#tk'),tickEl=$('#tick');
 if(!box||!tickEl)return;
 const rows=S.items.filter(i=>i.title).slice(0,12);
 if(!rows.length){tickEl.hidden=true;return}
 const links=rows.map(i=>'<a href="'+esc(articleHref(i))+'"><b>'+esc(i.category||'NEWS')+'</b>'+esc(i.title)+'</a>').join('');
 box.innerHTML='<div>'+links+links+'</div>';const primaryLive=S.mode==='api'&&S.apiMode!=='snapshot';
 const cachedOnly=S.mode==='cached'||S.mode==='cache'||S.mode==='empty';
 tickEl.classList.toggle('saved',!primaryLive);
 const tag=tickEl.querySelector('.tag');
 if(tag)tag.innerHTML='<span class="dot"></span>'+(primaryLive?'LIVE':cachedOnly?'OFFLINE':'SOURCE FEED');
 tickEl.hidden=false;
}
function hydrateCache(){const x=cacheLoad();if(!x||!x.items.length)return false;S.items=x.items.map(norm).sort((a,b)=>ts(b.date)-ts(a.date)||0);S.mode='cache';S.api='stale';return true}
function mergeFeeds(a,b){
 const all=[...(a||[]),...(b||[])].map(norm);
 const seen=new Map();
 for(const item of all){
  const key=String(item.id||item.url||item.title).trim().toLowerCase();
  if(!key)continue;
  const prev=seen.get(key);
  if(!prev||ts(item.date)>ts(prev.date)||(!prev.body&&item.body)||(!prev.image&&item.image))seen.set(key,item);
 }
 return [...seen.values()].sort((x,y)=>ts(y.date)-ts(x.date)||0)
}
async function load(opts={}){
 let a=[],b=[],h=[],painted=false,apiOK=false;
 const early=!!opts.early;
 const paintFirst=(rows,mode)=>{
  if(!early||painted||S.items.length||!rows?.length)return;
  painted=true;S.items=rows.map(norm).sort((x,y)=>ts(y.date)-ts(x.date)||0);S.mode=mode;cacheSave(S.items);ticker();render();
 };
 // The API is authoritative. Download the full saved snapshot only when the
 // API fails, rather than transferring it alongside every healthy refresh.
 const apiP=get(ENDPOINTS.api).then(rows=>{a=rows;apiOK=true;S.api=a.length?'ok':'empty';S.snap='standby';paintFirst(a,S.apiMode==='snapshot'?'snapshot':'api')}).catch(async()=>{S.api='bad';try{b=await get(ENDPOINTS.snap);S.snap=b.length?'ok':'empty';paintFirst(b,'snapshot')}catch(_){S.snap='bad'}});
 const hindiP=get(ENDPOINTS.hindi).then(rows=>{h=rows}).catch(()=>{});
 await Promise.allSettled([apiP,hindiP]);
 const existing=S.items.slice();
 // Prefer today's published snapshot to stale browser storage when the database
 // is unavailable; cached stories may have URLs that no longer resolve.
 const hasServerFeed=apiOK||b.length>0||h.length>0;
 S.items=mergeFeeds(apiOK?a:(b.length?b:existing),h);
 if(S.items.length){
  S.mode=apiOK?(S.apiMode==='snapshot'?'snapshot':'api'):(b.length||h.length?'snapshot':'cached');
  if(hasServerFeed)cacheSave(S.items);
 } else {S.mode='empty'}
 updateFeedStatus();
}
function home(c){document.documentElement.lang=c==='hindi'?'hi':'en';setActive(c);document.title=(c==='all'?'':CATS.find(x=>x[0]===c)?.[1]+' — ')+'PoliticsHub.in';
 const list=S.items.filter(i=>inCat(i,c));const f=list[0];const rest=list.filter(i=>i!==f);
 const tabs=`<div class="tabs" role="tablist" aria-label="Categories">${TABS.map(([k,l])=>`<a role="tab" href="${hl(k)}" data-c="${k}" data-k="${k}" class="${k===c?'on':''}" aria-selected="${k===c}">${l}</a>`).join('')}</div>`;
 if(!f){$('#app').innerHTML=tabs+`<div class="msg"><h3>No stories here yet</h3><p>Nothing in ${esc(c)} right now. Try another section or check back soon.</p></div>`;return}
 const ctn=CATS.find(x=>x[0]===c)[1],fk=ck(f),date=new Date().toLocaleDateString('en-IN',{weekday:'long',day:'numeric',month:'long'});
 const words=f.title.split(' ').map((w,i)=>`<span class="w"><span style="--i:${i}">${esc(w)}</span></span>`).join(' ');
 const lt=rest.slice(0,3).map(i=>`<a class="li" data-k="${ck(i)}" href="${articleHref(i)}"><span>${esc(i.title)}</span><small>${ago(i.date)}</small></a>`).join('')||'<p class="msg" style="padding:20px 0">No other stories yet.</p>';
 const pl=CATS.slice(1).map(([k,l])=>`<a data-k="${k}" href="${hl(k)}">${l}<small>${S.items.filter(i=>inCat(i,k)).length}</small></a>`).join('');
 const cover=f.image?`<a class="tile cv im" data-k="${fk}" style="--d:1" href="${articleHref(f)}" aria-label="${esc(f.title)}">${img(f)}<span class="chip stk">${esc(f.category)}</span><span class="cap">${esc(f.source)} ${ago(f.date)}</span></a>`:'';
 const hero=`<section class="bento"><div class="tile hl" data-k="${fk}"><span class="burst" aria-hidden="true">✺</span><span class="lbl"><i class="dot"></i>What matters, clearly. ${date}</span><h1>${words}</h1><p>${esc(f.summary)}</p><a class="btn" data-mag href="${articleHref(f)}">Read latest story <span aria-hidden="true">↗</span></a></div>
 ${cover}
 <div class="tile ct" style="--d:2"><span class="lbl">Today on PoliticsHub.in</span><b class="num" data-n="${list.length}">${list.length}</b><span>stories in ${esc(ctn)}</span></div>
 <div class="tile sc" style="--d:3"><span class="lbl">Jump to a desk</span><div class="pills">${pl}</div></div>
 <div class="tile lt" style="--d:4"><span class="lbl">Just in</span>${lt}</div></section>`;
 const bs=CATS.slice(1).map(([k,l])=>`<a data-k="${k}" href="${hl(k)}">${l}</a><i>✦</i>`).join(''),band=`<div class="band" aria-label="Browse sections"><div class="bt">${bs}<span class="bt-dup" aria-hidden="true" data-nosnippet>${bs+bs}</span></div></div>`;
 $('#app').innerHTML=hero+band+tabs+`<div class="sh"><h2>Latest stories</h2><span class="lbl">${list.length} stories</span></div><div class="grid">${rest.map(card).join('')||'<p class="msg" style="grid-column:1/-1">That is the only story in this section for now.</p>'}</div><section class="newsletter-card"><span class="lbl red">PoliticsHub Brief</span><h2>Important stories. No noise.</h2><p>Get a concise newsroom update in your inbox.</p><form id="homeNl"><input type="email" required placeholder="you@example.com" aria-label="Email address"><label class="consent-check"><input name="privacy" type="checkbox" required> I agree to receive the newsletter and to the <a href="/privacy.html">Privacy Policy</a>.</label><label class="consent-check"><input name="adult" type="checkbox" required> I confirm I am 18 or older.</label><button class="btn">Subscribe</button></form><small id="homeNlMsg"></small></section>`;fx();enhanceHome(c);bindNewsletter()}
let articleRequest=0,articleController;
async function article(id){setActive('');
 const requestId=++articleRequest;articleController?.abort();articleController=new AbortController();
 let it=S.items.find(i=>i.id===id);
 if(!it||!it.body){if(!it)$('#app').innerHTML='<div class="art" role="status">Loading this story…</div>';try{const r=await fetch(ENDPOINTS.item+encodeURIComponent(id),{signal:AbortSignal.any([articleController.signal,AbortSignal.timeout(10000)]),headers:{Accept:'application/json'}});if(r.ok){const j=await r.json();const raw=j.article&&typeof j.article==='object'?j.article:(j.data||j);it=norm(raw);it.id=id}}catch(e){}}
 if(requestId!==articleRequest)return;
 if(!it){$('#app').innerHTML=`<div class="msg"><h3>We couldn't load this story</h3><p>It may have been removed, or the news service is unreachable.</p><p style="margin-top:20px"><a class="btn" href="#/">Back to latest</a></p></div>`;return}
 document.title=it.title+' — PoliticsHub.in';document.body.dataset.k=ck(it);
 const paras=(it.body||'').split(/\n+/).filter(Boolean).map(p=>`<p>${esc(p)}</p>`).join('')||(it.summary?`<p>${esc(it.summary)}</p>`:'');
 const rel=S.items.filter(i=>i.id!==it.id&&i.category===it.category).concat(S.items.filter(i=>i.id!==it.id&&i.category!==it.category)).slice(0,3);
 $('#app').innerHTML=`<article class="art" data-k="${ck(it)}"><div class="ah"><a class="chip" href="${hl(CATS.find(c=>it.category.toLowerCase().includes(c[0]))?.[0]||'all')}">${esc(it.category)}</a><h1>${esc(it.title)}</h1>${it.summary&&it.body?`<p class="dek">${esc(it.summary)}</p>`:''}<div class="by"><span>By <a href="/author/politicshub-news-desk">PoliticsHub Editorial Desk</a></span><span>${fmt(it.date)}</span><span>${esc(it.source)}</span></div></div>${it.image?`<div class="ahero"><div class="im">${img(it)}</div></div>`:''}<div class="body">${paras}</div>${it.url?`<div class="src">Source: ${esc(it.source||'original report')}. <a href="${esc(safeSourceUrl(it.url))}" target="_blank" rel="noopener noreferrer">Read the original report</a></div>`:''}<button class="article-share" type="button" data-share-title="${esc(it.title)}" aria-haspopup="dialog" aria-label="Share this story"><span aria-hidden="true">↗</span><b>Share</b></button></article><section class="rel"><div class="sh"><h2>Related stories</h2></div><div class="grid">${rel.map(card).join('')}</div></section>`;fx();return it.id}
function settings(sub){setActive('');document.title='Settings — PoliticsHub.in';const th=document.documentElement.dataset.theme;
 const st=(v,t)=>`<span class="${v}">${t}</span>`;const last=S.items.find(i=>i.date)?.date;
 const privacy=preferencesAllowed()?'Preferences allowed':'Essential only';
 $('#app').innerHTML=`<div class="set"><span class="lbl red">Preferences</span><h1>Settings</h1>
 <section><h2>Appearance</h2><div class="themes"><button class="tc" data-th="light" aria-pressed="${th==='light'}"><div class="pv" style="background:#f4f1ec;color:#121212"><i></i><i></i><i></i></div><b>Bright</b></button><button class="tc" data-th="dark" aria-pressed="${th==='dark'}"><div class="pv" style="background:#0c0c0d;color:#f1ede5"><i></i><i></i><i></i></div><b>Dark</b></button></div><small class="lbl">Theme is remembered only when optional preferences are allowed.</small></section>
 <section id="prefs"><h2>Privacy choices</h2>
 <div class="row"><span>Optional browser storage<br><small class="lbl">Theme and recent-story cache</small></span><strong>${privacy}</strong></div>
 <div class="legal-actions"><button class="btn" data-consent-choice="preferences">Allow preferences</button><button class="btn secondary" data-consent-choice="essential">Essential only</button><a class="btn secondary" href="/cookies.html">Cookie Policy</a></div>
 <div class="row"><span>Reset local preferences</span><button class="btn" id="rst">Reset</button></div></section>
 <section id="status"><h2>System status</h2>
 <div class="row"><span>News API</span>${S.api==='ok'&&S.apiMode!=='snapshot'?st('ok','Operational'):S.apiMode==='snapshot'?st('unk','Saved feed only'):S.api==='empty'?st('unk','No stories returned'):st('bad','Unreachable')}</div>
 <div class="row"><span>Database</span>${S.api==='ok'&&S.apiMode!=='snapshot'?st('ok','Serving stories'):S.apiMode==='snapshot'?st('bad','Live database unavailable'):st('unk','Cannot be verified from browser')}</div>
 <div class="row"><span>News snapshot</span>${S.snap==='ok'?st('ok','Available'):S.snap==='standby'?st('unk','Standby — live API available'):S.snap==='empty'?st('unk','Empty'):st('bad','Not found')}</div>
 <div class="row"><span>Frontend</span>${st('ok','Running')}</div>
 <div class="row"><span>Last update</span><span>${last?fmt(last):'Unknown'}</span></div></section></div>`;
 if(sub)$('#'+sub)?.scrollIntoView()}
function render(background=false){
 articleRequest++;articleController?.abort();
 const path=location.pathname.split('/').filter(Boolean); const hash=location.hash.slice(1).split('/').filter(Boolean); const p=path.length>=2&&/^\d+-/.test(path[1])?['article',path[1].split('-')[0]]:(path.length===1&&CATS.some(x=>x[0]===path[0])?['c',path[0]]:hash); if(!background){closeAll();window.scrollTo(0,0)}
 const m=$('#app');m.style.animation='';
 if(p[0]==='article'){let id=p[1]||'';try{id=decodeURIComponent(id)}catch(_){}article(id)}else if(p[0]==='settings')settings(p[1]);
 else{const c=p[0]==='c'&&CATS.some(x=>x[0]===p[1])?p[1]:'all';home(c);if(p[0]==='search')openS()}
 prog()}
let rt;function route(){clearTimeout(rt);closeAll();window.__r=1;render()}
/* effects */
let io;function fx(){io?.disconnect();$$('.num').forEach(n=>{const T=+n.dataset.n;if(matchMedia('(prefers-reduced-motion:reduce)').matches)return;let s=null;const st=ts=>{s??=ts;const p=Math.min(1,(ts-s)/900);n.textContent=Math.round(T*(1-Math.pow(1-p,3)));if(p<1)requestAnimationFrame(st)};requestAnimationFrame(st)});io=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){e.target.classList.add('in');io.unobserve(e.target)}}),{rootMargin:'0px 0px -6% 0px'});$$('.rv').forEach(e=>io.observe(e));
 if(matchMedia('(hover:hover) and (pointer:fine)').matches&&!matchMedia('(prefers-reduced-motion:reduce)').matches){
  $$('.card,.cv').forEach(h=>{const k=h.classList.contains('cv')?6:3;h.onpointermove=e=>{const r=h.getBoundingClientRect(),x=(e.clientX-r.left)/r.width-.5,y=(e.clientY-r.top)/r.height-.5;h.style.setProperty('--ry',x*k+'deg');h.style.setProperty('--rx',-y*k+'deg')};h.onpointerleave=()=>{h.style.setProperty('--ry','0deg');h.style.setProperty('--rx','0deg')}});
  $$('[data-mag]').forEach(b=>{b.onpointermove=e=>{const r=b.getBoundingClientRect();b.style.transform=`translate(${(e.clientX-r.left-r.width/2)*.18}px,${(e.clientY-r.top-r.height/2)*.25}px)`};b.onpointerleave=()=>b.style.transform=''})}}
let tk=0;function prog(){if(tk)return;tk=requestAnimationFrame(()=>{tk=0;const y=scrollY,d=document.documentElement.scrollHeight-innerHeight;const a=$('.art');$('#prog').style.transform=`scaleX(${a&&d>0?Math.min(1,y/d):0})`;$('#hd').classList.toggle('is-scrolled',y>20);const bt=$('.bt');if(bt){const w=bt.scrollWidth/3;bt.style.transform=`translateX(${-((y*.8)%w)}px)`}const ah=$('.ahero img');if(ah&&!matchMedia('(prefers-reduced-motion:reduce)').matches)ah.style.transform=`translateY(${Math.min(y*.06,30)}px) scale(1.08)`})}
addEventListener('scroll',prog,{passive:true});addEventListener('resize',moveInd);
$('#hd').addEventListener('pointermove',e=>{if(!matchMedia('(hover:hover)').matches||matchMedia('(prefers-reduced-motion:reduce)').matches)return;const r=$('#lg').getBoundingClientRect(),x=(e.clientX-r.left-r.width/2)/innerWidth,y=(e.clientY-r.top-r.height/2)/200;$('#lg').style.transform=`translate(${x*14}px,${y*2}px) rotateY(${x*14}deg) rotateX(${-y*4}deg)`});
$('#hd').addEventListener('pointerleave',()=>$('#lg').style.transform='');
/* drawer, search */
const dr=$('#dr');let last,searchLast;
function openD(){closeS();last=document.activeElement;document.body.classList.add('dro');dr.setAttribute('aria-hidden','false');$('#bg').setAttribute('aria-expanded','true');$('#dx').focus()}
function closeD(){if(!document.body.classList.contains('dro'))return;document.body.classList.remove('dro');dr.setAttribute('aria-hidden','true');$('#bg').setAttribute('aria-expanded','false');last?.focus?.()}
function openS(){closeD();searchLast=document.activeElement;document.body.classList.add('search-open');$('#sp').classList.add('open');$('#sp').setAttribute('aria-hidden','false');setTimeout(()=>$('#si').focus(),50);doS()}
function closeS(){const opened=$('#sp').classList.contains('open');$('#sp').classList.remove('open');$('#sp').setAttribute('aria-hidden','true');document.body.classList.remove('search-open');searchController?.abort();if(opened)searchLast?.focus?.()}
function closeAll(){closeD();closeS()}
async function doS(){const q=$('#si').value.trim();if(!q){$('#sc').textContent='Type to search the full archive';$('#sres').innerHTML='';return}
 let r=[];try{r=await get(ENDPOINTS.search+'?q='+encodeURIComponent(q)+'&limit=50')}catch(e){r=S.items.filter(i=>[i.title,i.summary,i.source,i.category].join(' ').toLowerCase().includes(q.toLowerCase())).slice(0,50)}
 $('#sc').textContent=r.length?(r.length+' '+(r.length===1?'story':'stories')+' found in the archive'):'No stories match your search.';
 $('#sres').innerHTML=r.slice(0,50).map(i=>`<a class="sr" href="${articleHref(i)}">${i.image?`<img src="${esc(i.image)}" alt="" loading="lazy" onerror="this.remove()">`:''}<div><span class="lbl red">${esc(i.category)}</span><h3>${esc(i.title)}</h3><small>${esc(i.source)} ${ago(i.date)}</small></div></a>`).join('')}
$('#bg').onclick=openD;$('#dx').onclick=closeD;$('#bd').onclick=closeD;$('#sbtn').onclick=openS;$('#sx').onclick=closeS;$('#si').oninput=()=>{searchRequest++;searchController?.abort();clearTimeout(searchTimer);searchTimer=setTimeout(()=>doS(),250)};$('#sf').onsubmit=e=>e.preventDefault();
$('#sres').onclick=e=>{if(e.target.closest('a'))closeS()};
addEventListener('keydown',e=>{if(e.key==='Escape')closeAll();if(e.key==='/'&&!e.ctrlKey&&!e.metaKey&&!e.altKey&&!/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)&&!document.activeElement.isContentEditable){e.preventDefault();openS()}});
$('#pz').onclick=e=>{const p=$('#tk').classList.toggle('pz');e.currentTarget.setAttribute('aria-pressed',p);e.currentTarget.setAttribute('aria-label',p?'Play ticker':'Pause ticker')};
/* theme + prefs */
function theme(t,save){t=t==='dark'?'dark':'light';document.documentElement.dataset.theme=t;if(save&&preferencesAllowed()&&ls.get('ph-ls')!=='0')ls.set('ph-theme',t)}
theme(preferencesAllowed()&&ls.get('ph-theme')==='dark'?'dark':'light');
document.addEventListener('click',e=>{const t=e.target.closest('[data-th]');if(t){theme(t.dataset.th,1);$$('[data-th]').forEach(b=>b.setAttribute('aria-pressed',b===t))}
 const s=e.target.closest('.sw');if(s){const on=s.getAttribute('aria-checked')!=='true';s.setAttribute('aria-checked',on);ls.set(s.dataset.k,on?'1':'0');if(s.dataset.k==='ph-ls'&&!on)ls.del('ph-theme')}
 if(e.target.closest('#rst')){clearOptionalStorage();ls.del(CONSENT_KEY);theme('light');settings();showConsentBanner(true)}});
const fine=matchMedia('(hover:hover) and (pointer:fine)').matches&&!matchMedia('(prefers-reduced-motion:reduce)').matches;
addEventListener('pointerdown',e=>{const s=document.documentElement.style;s.setProperty('--cx',e.clientX+'px');s.setProperty('--cy',e.clientY+'px')});
if(fine){const cr=document.createElement('div');cr.id='cr';cr.innerHTML='<span>Read</span>';document.body.append(cr);let mx=0,my=0,cx=0,cy=0,on=0;
 const tick=()=>{cx+=(mx-cx)*.22;cy+=(my-cy)*.22;cr.style.transform=`translate(${cx}px,${cy}px) translate(-50%,-50%)`;const b=document.body.style;b.setProperty('--mx',mx+'px');b.setProperty('--my',my+'px');on=Math.abs(mx-cx)+Math.abs(my-cy)>.5?requestAnimationFrame(tick):0};
 addEventListener('pointermove',e=>{mx=e.clientX;my=e.clientY;cr.style.opacity=1;const t=e.target;cr.className=t.closest('.card,.cv')?'r':t.closest('a,button')?'h':'';if(!on)on=requestAnimationFrame(tick)})}
let liveRefreshBusy=true,lastRefreshAt=0;
function onStoryListRoute(){
 const path=location.pathname.split('/').filter(Boolean),hash=location.hash.slice(1);
 if(path.length>=2&&/^\d+-/.test(path[1]))return false;
 return !hash.startsWith('/article/')&&!hash.startsWith('/settings');
}
function activeFeedCategory(){
 const path=location.pathname.split('/').filter(Boolean);
 if(path.length===1&&CATS.some(x=>x[0]===path[0]))return path[0];
 const hash=location.hash.slice(1).split('/').filter(Boolean);
 return hash[0]==='c'&&CATS.some(x=>x[0]===hash[1])?hash[1]:'all';
}
function feedSignature(items,category){
 return (items||[]).filter(i=>inCat(i,category)).slice(0,30).map(i=>String(i.id)+':'+String(i.date||'')+':'+String(i.title||'')+':'+String(i.summary||'').slice(0,80)).join('|');
}
let pendingHomeRefresh=false;
async function refreshLatest(force=false){
 if(liveRefreshBusy)return;
 if(!force&&Date.now()-lastRefreshAt<15000)return;
 liveRefreshBusy=true;
 const category=activeFeedCategory(),before=feedSignature(S.items,category);
 try{
  await load();
  const after=feedSignature(S.items,category);
  ticker();
  if(after!==before&&onStoryListRoute()){
   if(window.scrollY>80)pendingHomeRefresh=true;
   else render(true);
  }
  updateFeedStatus();
 }finally{liveRefreshBusy=false;lastRefreshAt=Date.now()}
}
addEventListener('scroll',()=>{
 if(pendingHomeRefresh&&window.scrollY<32&&onStoryListRoute()){
  pendingHomeRefresh=false;
  render(true);
 }
},{passive:true});
setInterval(()=>{if(!document.hidden)refreshLatest()},90000);
addEventListener('online',()=>refreshLatest(true));
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshLatest(true)});
addEventListener('focus',()=>refreshLatest());
if('serviceWorker' in navigator) addEventListener('load',()=>navigator.serviceWorker.register('/service-worker.js').catch(()=>{}));
addEventListener('load',()=>showConsentBanner(false));

async function enhanceHome(category){
 const rail=$('#app .ph14-rail'),target=rail||$('#app .grid'); if(!target||S.mode!=='api')return;
 try{
  const r=await get('/api/trending?limit=5');
  const filtered=r.filter(i=>inCat(i,category)&&Number(i.view_count)>0);
  if(!filtered.length||!target.isConnected)return;
  const section=document.createElement('section');section.className=rail?'ph14-rail-card':'trend-section';
  section.innerHTML='<h3>Most read</h3><ol class="most-read">'+filtered.map(i=>'<li><a href="'+esc(articleHref(i))+'">'+esc(i.title)+'</a><small>'+Number(i.view_count).toLocaleString('en-IN')+' page views</small></li>').join('')+'</ol>';
  if(rail)rail.append(section);else target.parentNode.insertBefore(section,target.nextSibling);
 }catch(e){}
}
function trackView(id){try{navigator.sendBeacon('/api/news/'+encodeURIComponent(id)+'/view',new Blob(['{}'],{type:'application/json'}))}catch(e){}}
function ensureSearchFilters(){
 const sb=$('.sb'); if(!sb||$('#searchFilters'))return;
 const box=document.createElement('div'); box.id='searchFilters'; box.className='search-filters';
 box.innerHTML=CATS.map(x=>'<button type="button" data-search-cat="'+x[0]+'" class="'+((window.searchCat||'all')===x[0]?'on':'')+'" aria-pressed="'+((window.searchCat||'all')===x[0])+'">'+(x[0]==='all'?'All':esc(x[1]))+'</button>').join('');
 sb.insertBefore(box,$('#sc'));
 box.onclick=e=>{const b=e.target.closest('[data-search-cat]');if(!b)return;window.searchCat=b.dataset.searchCat;$$('[data-search-cat]',box).forEach(x=>{x.classList.toggle('on',x===b);x.setAttribute('aria-pressed',String(x===b))});doS()};
 const sources=[...new Set(S.items.map(i=>i.source).filter(Boolean))].sort((a,b)=>a.localeCompare(b));
 const options=document.createElement('div');options.className='search-options';
 options.innerHTML='<label>Publisher<select id="searchSource"><option value="">All publishers</option>'+sources.map(s=>'<option value="'+esc(s)+'">'+esc(s)+'</option>').join('')+'</select></label><label>Published<select id="searchPeriod"><option value="all">Any time</option><option value="day">Past 24 hours</option><option value="week">Past 7 days</option><option value="month">Past 30 days</option></select></label>';
 sb.insertBefore(options,$('#sc'));options.addEventListener('change',()=>doS());
}
const __openS=openS; openS=function(){__openS();ensureSearchFilters()};
let searchRequest=0,searchTimer,searchOffset=0,searchResults=[],searchController;
const __doS=doS; doS=async function(append=false){
 const requestId=++searchRequest;
 searchController?.abort();searchController=new AbortController();
 const q=$('#si')?.value.trim()||'',cat=window.searchCat||'all';
 const source=$('#searchSource')?.value||'',period=$('#searchPeriod')?.value||'all';
 if(!append){searchOffset=0;searchResults=[]}
 const offset=searchOffset;
 if(q.length<2){$('#sc').textContent='Enter at least 2 characters to search the archive';$('#sres').innerHTML='';return}
 $('#sc').textContent='Searching…';
 let r=[],localFallback=false;
 try{
  r=await get(ENDPOINTS.search+'?q='+encodeURIComponent(q)+'&limit=50&offset='+offset+'&category='+encodeURIComponent(cat)+'&source='+encodeURIComponent(source)+'&period='+encodeURIComponent(period),{signal:searchController.signal});
 }catch(e){
  if(requestId!==searchRequest||searchController.signal.aborted)return;
  localFallback=true;
  const cutoff=period==='all'?0:Date.now()-({day:1,week:7,month:30}[period]||0)*86400000;
  r=S.items.filter(i=>(cat==='all'||inCat(i,cat))&&(!source||i.source===source)&&(!cutoff||ts(i.date)>=cutoff)&&[i.title,i.summary,i.source,i.category].join(' ').toLowerCase().includes(q.toLowerCase())).slice(offset,offset+50);
 }
 if(requestId!==searchRequest)return;
 const hasMore=r.length===50;searchOffset=offset+r.length;
 const seen=new Set(searchResults.map(i=>i.id));
 searchResults=searchResults.concat(r.map(norm).filter(i=>{if((cat!=='all'&&!inCat(i,cat))||seen.has(i.id))return false;seen.add(i.id);return true}));
 r=searchResults;
 $('#sc').textContent=(r.length?(r.length+' '+(r.length===1?'story':'stories')+' found'):'No stories match your search.')+(localFallback?' Archive unavailable; searching loaded stories only.':'');
 $('#sres').innerHTML=r.map(i=>'<a class="sr" href="'+esc(articleHref(i))+'">'+(i.image?'<img src="'+esc(i.image)+'" alt="" loading="lazy">':'')+'<div><span class="lbl red">'+esc(i.category)+'</span><h3>'+esc(i.title)+'</h3><small>'+esc(i.source)+' '+ago(i.date)+'</small></div></a>').join('')+(hasMore?'<button type="button" class="btn" id="searchMore">Load more stories</button>':'');
 const more=$('#searchMore');if(more)more.onclick=()=>{more.disabled=true;doS(true)};
};
const __article=article; article=async function(id){const loaded=await __article(id);if(loaded===id&&/^\d+$/.test(id))trackView(id)};

function bindNewsletter(){
 const f=$('#homeNl');if(!f)return;
 const message=$('#homeNlMsg'),submit=f.querySelector('button[type="submit"],button:not([type])');
 let pending=false;
 f.onsubmit=async e=>{
  e.preventDefault();if(pending||submit.disabled)return;pending=true;submit.disabled=true;f.setAttribute('aria-busy','true');message.textContent='Sending…';
  const email=f.querySelector('input[type="email"]'),privacy=f.querySelector('[name="privacy"]'),adult=f.querySelector('[name="adult"]');
  try{
   const r=await fetch('/api/newsletter',{method:'POST',headers:{'Content-Type':'application/json'},signal:AbortSignal.timeout(15000),body:JSON.stringify({email:email?.value||'',consent:!!privacy?.checked,adult:!!adult?.checked})});
   const j=await r.json();message.textContent=j.message||j.error||'Unable to subscribe.';
   if(r.ok)f.reset();
  }catch(_){message.textContent='Could not subscribe right now.'}
  finally{pending=false;submit.disabled=false;f.removeAttribute('aria-busy')}
 };
 fetch('/api/newsletter',{cache:'default'}).then(r=>r.json()).then(status=>{
  if(!f.isConnected)return;
  if(status.available===false){submit.disabled=true;submit.textContent=status.delivery_configured?'Temporarily unavailable':'Coming soon';message.textContent=status.message||'Subscription is temporarily unavailable. Please try again later.'}
 }).catch(()=>{});
}

function updateFeedStatus(){
 let box=document.getElementById('feedStatus');
 if(!box){box=document.createElement('div');box.id='feedStatus';box.className='feed-status wrap';box.setAttribute('role','status');const main=document.querySelector('main');if(main?.id==='app')main.before(box);else main?.prepend(box)}
 const mode=S.mode;
 const newest=S.items.reduce((best,item)=>Math.max(best,ts(item.date)),0);
 const newestLabel=newest?' Newest report: '+ago(new Date(newest).toISOString())+'.':'';
 box.replaceChildren();
 const label=document.createElement('span');
 if(mode==='api')label.textContent='Latest news connected. Updates refresh automatically.'+newestLabel;
 else if(mode==='snapshot')label.textContent='News source feed is active. New source reports are checked automatically (around every 30 minutes).'+newestLabel;
 else if(mode==='cached'||mode==='cache')label.textContent='Connection unavailable. Showing previously loaded stories.'+newestLabel;
 else label.textContent='News is temporarily unavailable. Please retry.';
 box.append(label);
 const retry=document.createElement('button');retry.type='button';retry.className='btn secondary';retry.textContent='Refresh news';retry.onclick=async()=>{retry.disabled=true;retry.textContent='Refreshing…';try{await refreshLatest(true)}finally{retry.disabled=false;retry.textContent='Refresh news'}};box.append(retry);
}
document.addEventListener('error',event=>{
 const image=event.target;if(!(image instanceof HTMLImageElement))return;
 const card=image.closest('.card');if(card){card.classList.remove('im');card.classList.add('tx')}
 const wrapper=image.closest('.ahero,.tile.cv,.ph14-media,.ph14-thumb');if(wrapper)wrapper.remove();else image.remove();
},true);

 document.addEventListener('keydown',event=>{
  if(event.key!=='Tab')return;
  const root=document.querySelector('#sp.open')||(document.body.classList.contains('dro')?document.querySelector('#dr'):null);
  if(!root)return;
  const nodes=[...root.querySelectorAll('a[href],button,input')].filter(el=>!el.disabled&&el.getClientRects().length);
  const first=nodes[0],last=nodes[nodes.length-1];if(!first)return;
  if(event.shiftKey&&(document.activeElement===first||!root.contains(document.activeElement))){event.preventDefault();last.focus()}
  else if(!event.shiftKey&&(document.activeElement===last||!root.contains(document.activeElement))){event.preventDefault();first.focus()}
 });

/* Start after every controller and renderer is initialized, including cached routes. */
function boot(){
$('#yr').textContent=new Date().getFullYear();build();
document.fonts?.ready.then(moveInd);
addEventListener('hashchange',route);
const qcat=new URLSearchParams(location.search).get('category');if(!location.hash&&qcat&&CATS.some(x=>x[0]===qcat))location.hash='#/c/'+qcat;

setActive('all');
const hadCache=hydrateCache();
if(hadCache){ticker();render();}
load({early:!hadCache}).then(()=>{ticker();render();updateFeedStatus()}).finally(()=>{liveRefreshBusy=false;lastRefreshAt=Date.now()});
}
boot();
