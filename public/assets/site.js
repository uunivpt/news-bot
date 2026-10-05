
const CATS=[['all','Home'],['india','India'],['politics','Politics'],['world','World'],['business','Business'],['technology','Technology'],['sports','Sports'],['entertainment','Entertainment']];
const TABS=[['all','All'],['politics','Politics'],['india','India'],...CATS.slice(3)];
const ENDPOINTS={api:'/api/news',snap:'news-data.json'};
const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ls={get:k=>{try{return localStorage.getItem(k)}catch(e){return null}},set:(k,v)=>{try{localStorage.setItem(k,v)}catch(e){}},del:k=>{try{localStorage.removeItem(k)}catch(e){}}};
const S={items:[],mode:'loading',api:'unknown',snap:'unknown',tried:0};
const fmt=d=>{const x=new Date(d);return isNaN(x)?'':x.toLocaleString('en-IN',{day:'numeric',month:'short',year:'numeric',hour:'numeric',minute:'2-digit'})};
const ago=d=>{const m=(Date.now()-new Date(d))/6e4;if(isNaN(m))return'';return m<60?Math.max(1,~~m)+'m ago':m<1440?~~(m/60)+'h ago':fmt(d).split(',')[0]};
function norm(a,i){const id=a.id??a.slug??a._id??'n'+i;const img=a.image||a.image_url||a.imageUrl||a.urlToImage||a.thumbnail||a.img||'';
 return{id:String(id),title:a.title||a.headline||'Untitled',summary:a.summary||a.description||a.excerpt||'',body:a.content||a.body||a.text||'',image:typeof img==='string'?img:'',category:String(a.category||a.section||'General'),source:(a.source&&a.source.name)||a.source||a.publisher||'',date:a.published_at||a.publishedAt||a.pubDate||a.date||a.created_at||'',url:a.url||a.link||''}}
const pick=j=>Array.isArray(j)?j:(j.articles||j.news||j.items||j.data||j.results||[]);
async function get(u){const r=await fetch(u,{cache:'no-store'});if(!r.ok)throw 0;const rows=pick(await r.json());return rows.map((x,i)=>{const img=x.image_url||x.image||x.imageUrl||x.urlToImage||x.thumbnail||x.img||'';const source=x.source_name||(x.source&&x.source.name)||x.source||x.publisher||'PoliticsHub';const date=x.published_at||x.published_at_site||x.publishedAt||x.pubDate||x.date||x.created_at||'';const body=x.article||x.bot_article||x.content||x.body||x.text||'';const summary=x.summary||x.bot_summary||x.description||x.excerpt||'';return {...x,id:String(x.id??x.slug??x._id??'n'+i),image:typeof img==='string'?img:'',source:String(source),date,body:String(body),summary:String(summary)};})}
async function load(){let a=null;
 try{a=await get(ENDPOINTS.api);S.api=a.length?'ok':'empty'}catch(e){S.api='bad'}
 let b=null;try{b=await get(ENDPOINTS.snap);S.snap=b.length?'ok':'empty'}catch(e){S.snap='bad'}
 const src=(a&&a.length)?a:(b&&b.length)?b:null;
 if(src){S.items=src.map(norm).sort((x,y)=>new Date(y.date)-new Date(x.date)||0);S.mode=(a&&a.length)?'api':'snapshot'}
 else{S.items=[];S.mode='empty'}}
const inCat=(it,c)=>c==='all'||it.category.toLowerCase().includes(c);
const img=(it,cls='')=>it.image?`<img ${cls} src="${esc(it.image)}" alt="" loading="lazy" decoding="async" onerror="this.closest('.im,.cover')&&(this.parentElement.dataset.bad=1);this.remove()">`:'';
const ck=it=>{const l=it.category.toLowerCase();const m=CATS.find(c=>c[0]!=='all'&&l.includes(c[0]));return m?m[0]:'all'};
const hl=c=>'#/c/'+c;
function card(it,i){const has=it.image;const meta=`${esc(it.source)}${it.source&&it.date?' · ':''}${ago(it.date)}`;
 return`<a class="card rv ${has?'im':'tx'}" data-k="${ck(it)}" href="#/article/${encodeURIComponent(it.id)}" style="transition-delay:${(i%3)*60}ms">${has?img(it):''}<span class="wm" aria-hidden="true">${esc(it.category.charAt(0))}</span><span class="chip">${esc(it.category)}</span><span class="go" aria-hidden="true">↗</span><h3>${esc(it.title)}</h3>${it.summary?`<p>${esc(it.summary)}</p>`:''}<span class="m">${meta}</span></a>`}
function build(){const n=$('#nav');n.insertAdjacentHTML('afterbegin',CATS.map(([k,l])=>`<a href="${hl(k)}" data-c="${k}" data-k="${k}">${l}</a>`).join(''));$('#dl').innerHTML=[CATS[0],CATS[2],CATS[1],...CATS.slice(3)].map(([k,l])=>`<a class="l" href="${hl(k)}" data-c="${k}" data-k="${k}">${l}</a>`).join('')}
function setActive(c){document.body.dataset.k=c||'all';$$('[data-c]').forEach(a=>a.classList.toggle('on',a.dataset.c===c));$$('#nav a').forEach(a=>a.setAttribute('aria-current',a.dataset.c===c?'page':'false'));moveInd()}
function moveInd(){const a=$('#nav a.on'),i=$('#ind');if(!a){i.style.width=0;return}i.style.left=a.offsetLeft+'px';i.style.width=a.offsetWidth+'px'}
function ticker(){const t=$('#tick');if(!S.items.length||S.mode==='demo'){t.hidden=true;return}t.hidden=false;const h=S.items.slice(0,10).map(i=>`<a href="#/article/${encodeURIComponent(i.id)}">${esc(i.title)}</a>`).join('');$('#tk').innerHTML=`<div>${h}${h}</div>`}
function home(c){setActive(c);document.title=(c==='all'?'':CATS.find(x=>x[0]===c)?.[1]+' — ')+'PoliticsHub.in';
 const list=S.items.filter(i=>inCat(i,c));const f=list.find(i=>i.image)||list[0];const rest=list.filter(i=>i!==f);
 const tabs=`<div class="tabs" role="tablist" aria-label="Categories">${TABS.map(([k,l])=>`<a role="tab" href="${hl(k)}" data-c="${k}" data-k="${k}" class="${k===c?'on':''}" aria-selected="${k===c}">${l}</a>`).join('')}</div>`;
 if(!f){$('#app').innerHTML=tabs+`<div class="msg"><h3>No stories here yet</h3><p>Nothing in ${esc(c)} right now. Try another section or check back soon.</p></div>`;return}
 const ctn=CATS.find(x=>x[0]===c)[1],fk=ck(f),date=new Date().toLocaleDateString('en-IN',{weekday:'long',day:'numeric',month:'long'});
 const words=f.title.split(' ').slice(0,18).map((w,i)=>`<span class="w"><span style="--i:${i}">${esc(w)}</span></span>`).join(' ');
 const lt=rest.slice(0,3).map(i=>`<a class="li" data-k="${ck(i)}" href="#/article/${encodeURIComponent(i.id)}"><span>${esc(i.title)}</span><small>${ago(i.date)}</small></a>`).join('')||'<p class="msg" style="padding:20px 0">No other stories yet.</p>';
 const pl=CATS.slice(1).map(([k,l])=>`<a data-k="${k}" href="${hl(k)}">${l}<small>${S.items.filter(i=>inCat(i,k)).length}</small></a>`).join('');
 const hero=`<section class="bento"><div class="tile hl" data-k="${fk}"><span class="burst" aria-hidden="true">✺</span><span class="lbl"><i class="dot"></i>What matters, clearly. ${date}</span><h1>${words}</h1><p>${esc(f.summary)}</p><a class="btn" data-mag href="#/article/${encodeURIComponent(f.id)}">Read latest story <span aria-hidden="true">↗</span></a></div>
 <a class="tile cv ${f.image?'im':'tx'}" data-k="${fk}" style="--d:1" href="#/article/${encodeURIComponent(f.id)}" aria-label="${esc(f.title)}">${f.image?img(f):`<span class="big">${esc(f.category)}</span>`}<span class="chip stk">${esc(f.category)}</span><span class="cap">${esc(f.source)} ${ago(f.date)}</span></a>
 <div class="tile ct" style="--d:2"><span class="lbl">Today on PoliticsHub.in</span><b class="num" data-n="${list.length}">${list.length}</b><span>stories in ${esc(ctn)}</span></div>
 <div class="tile sc" style="--d:3"><span class="lbl">Jump to a desk</span><div class="pills">${pl}</div></div>
 <div class="tile lt" style="--d:4"><span class="lbl">Just in</span>${lt}</div></section>`;
 const bs=CATS.slice(1).map(([k,l])=>`<a data-k="${k}" href="${hl(k)}">${l}</a><i>✦</i>`).join(''),band=`<div class="band" aria-label="Browse sections"><div class="bt">${bs+bs+bs}</div></div>`;
 $('#app').innerHTML=hero+band+tabs+`<div class="sh"><h2>Latest stories</h2><span class="lbl">${list.length} stories</span></div><div class="grid">${rest.map(card).join('')||'<p class="msg" style="grid-column:1/-1">That is the only story in this section for now.</p>'}</div>`;fx()}
async function article(id){setActive('');$('#app').innerHTML='<div class="art"><div class="sk"></div></div>';
 let it=S.items.find(i=>i.id===id);
 if(!it||(!it.body&&S.mode==='api')){try{const r=await fetch(ENDPOINTS.api+'/'+encodeURIComponent(id),{cache:'no-store'});if(r.ok){const j=await r.json();const raw=j.article||j.data||j;it=norm({...raw,image:raw.image_url||raw.image,source:raw.source_name||raw.source,date:raw.published_at||raw.published_at_site,body:raw.article||raw.bot_article||raw.content,summary:raw.summary||raw.bot_summary});it.id=id}}catch(e){}}
 if(!it){$('#app').innerHTML=`<div class="msg"><h3>We couldn't load this story</h3><p>It may have been removed, or the news service is unreachable.</p><p style="margin-top:20px"><a class="btn" href="#/">Back to latest</a></p></div>`;return}
 document.title=it.title+' — PoliticsHub.in';document.body.dataset.k=ck(it);
 const paras=(it.body||'').split(/\n+/).filter(Boolean).map(p=>`<p>${esc(p)}</p>`).join('')||(it.summary?`<p>${esc(it.summary)}</p>`:'');
 const rel=S.items.filter(i=>i.id!==it.id&&i.category===it.category).concat(S.items.filter(i=>i.id!==it.id&&i.category!==it.category)).slice(0,3);
 $('#app').innerHTML=`<article class="art" data-k="${ck(it)}"><div class="ah"><a class="chip" href="${hl(CATS.find(c=>it.category.toLowerCase().includes(c[0]))?.[0]||'all')}">${esc(it.category)}</a><h1>${esc(it.title)}</h1>${it.summary&&it.body?`<p class="dek">${esc(it.summary)}</p>`:''}<div class="by"><span>${esc(it.source)}</span><span>${fmt(it.date)}</span></div></div>${it.image?`<div class="ahero"><div class="im">${img(it)}</div></div>`:''}<div class="body">${paras}</div>${it.url?`<div class="src">Source: ${esc(it.source||'original report')}. <a href="${esc(it.url)}" target="_blank" rel="noopener noreferrer">Read the original report</a></div>`:''}<div class="article-share"><span>SHARE</span><a target="_blank" rel="noopener noreferrer" href="https://wa.me/?text=${encodeURIComponent(it.title+' '+location.href)}">WhatsApp</a><a target="_blank" rel="noopener noreferrer" href="https://t.me/share/url?url=${encodeURIComponent(location.href)}&text=${encodeURIComponent(it.title)}">Telegram</a><a target="_blank" rel="noopener noreferrer" href="https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(location.href)}">Facebook</a><a target="_blank" rel="noopener noreferrer" href="https://twitter.com/intent/tweet?text=${encodeURIComponent(it.title)}&url=${encodeURIComponent(location.href)}">X</a></div></article><section class="rel"><div class="sh"><h2>Related stories</h2></div><div class="grid">${rel.map(card).join('')}</div></section>`;fx()}
function settings(sub){setActive('');document.title='Settings — PoliticsHub.in';const th=document.documentElement.dataset.theme;
 const st=(v,t)=>`<span class="${v}">${t}</span>`;const last=S.items.find(i=>i.date)?.date;
 const s2=k=>ls.get(k)!=='0';
 $('#app').innerHTML=`<div class="set"><span class="lbl red">Preferences</span><h1>Settings</h1>
 <section><h2>Appearance</h2><div class="themes"><button class="tc" data-th="light" aria-pressed="${th==='light'}"><div class="pv" style="background:#f4f1ec;color:#121212"><i></i><i></i><i></i></div><b>Bright</b></button><button class="tc" data-th="dark" aria-pressed="${th==='dark'}"><div class="pv" style="background:#0c0c0d;color:#f1ede5"><i></i><i></i><i></i></div><b>Dark</b></button></div></section>
 <section id="prefs"><h2>Browser preferences</h2>
 <div class="row"><span>Allow cookies<br><small class="lbl">Remember your choices</small></span><button class="sw" role="switch" data-k="ph-cookie" aria-checked="${s2('ph-cookie')}" aria-label="Cookie preference"></button></div>
 <div class="row"><span>Allow local storage<br><small class="lbl">Save theme on this device</small></span><button class="sw" role="switch" data-k="ph-ls" aria-checked="${s2('ph-ls')}" aria-label="Local storage preference"></button></div>
 <div class="row"><span>Reset local preferences</span><button class="btn" id="rst">Reset</button></div></section>
 <section id="status"><h2>System status</h2>
 <div class="row"><span>News API</span>${S.api==='ok'?st('ok','Operational'):S.api==='empty'?st('unk','No stories returned'):st('bad','Unreachable')}</div>
 <div class="row"><span>Database</span>${S.api==='ok'?st('ok','Serving stories'):st('unk','Cannot be verified from browser')}</div>
 <div class="row"><span>News snapshot</span>${S.snap==='ok'?st('ok','Available'):S.snap==='empty'?st('unk','Empty'):st('bad','Not found')}</div>
 <div class="row"><span>Frontend</span>${st('ok','Running')}</div>
 <div class="row"><span>Last update</span><span>${last?fmt(last):'Unknown'}</span></div></section></div>`;
 if(sub)$('#'+sub)?.scrollIntoView()}
function render(){const p=location.hash.slice(1).split('/').filter(Boolean);closeAll();window.scrollTo(0,0);
 const m=$('#app');m.style.animation='none';void m.offsetWidth;m.style.animation='';
 if(p[0]==='article')article(decodeURIComponent(p[1]||''));else if(p[0]==='settings')settings(p[1]);
 else{const c=p[0]==='c'&&CATS.some(x=>x[0]===p[1])?p[1]:'all';home(c)}
 prog()}
let rt;function route(){clearTimeout(rt);closeAll();const f=!window.__r;window.__r=1;if(f||matchMedia('(prefers-reduced-motion:reduce)').matches){render();return}const c=$('#cv');c.classList.remove('go');void c.offsetWidth;c.classList.add('go');rt=setTimeout(render,360)}
/* effects */
let io;function fx(){io?.disconnect();$$('.num').forEach(n=>{const T=+n.dataset.n;if(matchMedia('(prefers-reduced-motion:reduce)').matches)return;let s=null;const st=ts=>{s??=ts;const p=Math.min(1,(ts-s)/900);n.textContent=Math.round(T*(1-Math.pow(1-p,3)));if(p<1)requestAnimationFrame(st)};requestAnimationFrame(st)});io=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){e.target.classList.add('in');io.unobserve(e.target)}}),{rootMargin:'0px 0px -6% 0px'});$$('.rv').forEach(e=>io.observe(e));
 if(matchMedia('(hover:hover) and (pointer:fine)').matches&&!matchMedia('(prefers-reduced-motion:reduce)').matches){
  $$('.card,.cv').forEach(h=>{const k=h.classList.contains('cv')?6:3;h.onpointermove=e=>{const r=h.getBoundingClientRect(),x=(e.clientX-r.left)/r.width-.5,y=(e.clientY-r.top)/r.height-.5;h.style.setProperty('--ry',x*k+'deg');h.style.setProperty('--rx',-y*k+'deg')};h.onpointerleave=()=>{h.style.setProperty('--ry','0deg');h.style.setProperty('--rx','0deg')}});
  $$('[data-mag]').forEach(b=>{b.onpointermove=e=>{const r=b.getBoundingClientRect();b.style.transform=`translate(${(e.clientX-r.left-r.width/2)*.18}px,${(e.clientY-r.top-r.height/2)*.25}px)`};b.onpointerleave=()=>b.style.transform=''})}}
let tk=0;function prog(){if(tk)return;tk=requestAnimationFrame(()=>{tk=0;const y=scrollY,d=document.documentElement.scrollHeight-innerHeight;const a=$('.art');$('#prog').style.transform=`scaleX(${a&&d>0?Math.min(1,y/d):0})`;$('#hd').classList.toggle('sc',y>20);const bt=$('.bt');if(bt){const w=bt.scrollWidth/3;bt.style.transform=`translateX(${-((y*.8)%w)}px)`}const ah=$('.ahero img');if(ah&&!matchMedia('(prefers-reduced-motion:reduce)').matches)ah.style.transform=`translateY(${Math.min(y*.06,30)}px) scale(1.08)`})}
addEventListener('scroll',prog,{passive:true});addEventListener('resize',moveInd);
$('#hd').addEventListener('pointermove',e=>{if(!matchMedia('(hover:hover)').matches)return;const r=$('#lg').getBoundingClientRect(),x=(e.clientX-r.left-r.width/2)/innerWidth,y=(e.clientY-r.top-r.height/2)/200;$('#lg').style.transform=`translate(${x*14}px,${y*2}px) rotateY(${x*14}deg) rotateX(${-y*4}deg)`});
$('#hd').addEventListener('pointerleave',()=>$('#lg').style.transform='');
/* drawer, search */
const dr=$('#dr');let last;
function openD(){last=document.activeElement;document.body.classList.add('dro');dr.setAttribute('aria-hidden','false');$('#bg').setAttribute('aria-expanded','true');$('#dx').focus()}
function closeD(){if(!document.body.classList.contains('dro'))return;document.body.classList.remove('dro');dr.setAttribute('aria-hidden','true');$('#bg').setAttribute('aria-expanded','false');last?.focus?.()}
function openS(){$('#sp').classList.add('open');$('#sp').setAttribute('aria-hidden','false');setTimeout(()=>$('#si').focus(),50);doS()}
function closeS(){$('#sp').classList.remove('open');$('#sp').setAttribute('aria-hidden','true')}
function closeAll(){closeD();closeS()}
function doS(){const q=$('#si').value.trim().toLowerCase();if(!q){$('#sc').textContent='Type to search all stories';$('#sres').innerHTML='';return}
 const r=S.items.filter(i=>[i.title,i.summary,i.source,i.category].join(' ').toLowerCase().includes(q));
 $('#sc').textContent=r.length?`${r.length} ${r.length===1?'story':'stories'} found`:'No stories match your search.';
 $('#sres').innerHTML=r.slice(0,30).map(i=>`<a class="sr" href="#/article/${encodeURIComponent(i.id)}">${i.image?`<img src="${esc(i.image)}" alt="" loading="lazy" onerror="this.remove()">`:''}<div><span class="lbl red">${esc(i.category)}</span><h3>${esc(i.title)}</h3><small>${esc(i.source)} ${ago(i.date)}</small></div></a>`).join('')}
$('#bg').onclick=openD;$('#dx').onclick=closeD;$('#bd').onclick=closeD;$('#sbtn').onclick=openS;$('#sx').onclick=closeS;$('#si').oninput=doS;$('#sf').onsubmit=e=>e.preventDefault();
$('#sres').onclick=e=>{if(e.target.closest('a'))closeS()};
addEventListener('keydown',e=>{if(e.key==='Escape')closeAll();if(e.key==='/'&&!/INPUT|TEXTAREA/.test(document.activeElement.tagName)){e.preventDefault();openS()}});
$('#pz').onclick=e=>{const p=$('#tk').classList.toggle('pz');e.currentTarget.setAttribute('aria-pressed',p);e.currentTarget.setAttribute('aria-label',p?'Play ticker':'Pause ticker')};
/* theme + prefs */
function theme(t,save){document.documentElement.dataset.theme=t;if(save&&ls.get('ph-ls')!=='0')ls.set('ph-theme',t)}
theme(ls.get('ph-theme')||'light');
document.addEventListener('click',e=>{const t=e.target.closest('[data-th]');if(t){theme(t.dataset.th,1);$$('[data-th]').forEach(b=>b.setAttribute('aria-pressed',b===t))}
 const s=e.target.closest('.sw');if(s){const on=s.getAttribute('aria-checked')!=='true';s.setAttribute('aria-checked',on);ls.set(s.dataset.k,on?'1':'0');if(s.dataset.k==='ph-ls'&&!on)ls.del('ph-theme')}
 if(e.target.closest('#rst')){['ph-theme','ph-cookie','ph-ls'].forEach(ls.del);theme('light');settings()}});
const fine=matchMedia('(hover:hover) and (pointer:fine)').matches&&!matchMedia('(prefers-reduced-motion:reduce)').matches;
addEventListener('pointerdown',e=>{const s=document.documentElement.style;s.setProperty('--cx',e.clientX+'px');s.setProperty('--cy',e.clientY+'px')});
if(fine){const cr=document.createElement('div');cr.id='cr';cr.innerHTML='<span>Read</span>';document.body.append(cr);let mx=0,my=0,cx=0,cy=0,on=0;
 const tick=()=>{cx+=(mx-cx)*.22;cy+=(my-cy)*.22;cr.style.transform=`translate(${cx}px,${cy}px) translate(-50%,-50%)`;const b=document.body.style;b.setProperty('--mx',mx+'px');b.setProperty('--my',my+'px');on=Math.abs(mx-cx)+Math.abs(my-cy)>.5?requestAnimationFrame(tick):0};
 addEventListener('pointermove',e=>{mx=e.clientX;my=e.clientY;cr.style.opacity=1;const t=e.target;cr.className=t.closest('.card,.cv')?'r':t.closest('a,button')?'h':'';if(!on)on=requestAnimationFrame(tick)})}
/* boot */
$('#yr').textContent=new Date().getFullYear();build();
document.fonts?.ready.then(moveInd);
addEventListener('hashchange',route);
const qcat=new URLSearchParams(location.search).get('category');if(!location.hash&&qcat&&CATS.some(x=>x[0]===qcat))location.hash='#/c/'+qcat;
const legacyId=new URLSearchParams(location.search).get('id');if(!location.hash&&/\/article\.html$/.test(location.pathname)&&legacyId)location.hash='#/article/'+encodeURIComponent(legacyId);
$('#app').innerHTML='<div class="sk" style="margin:48px 0"></div><div class="sk" style="margin:24px 0;height:160px"></div>';setActive('all');
load().then(()=>{ticker();route()});
