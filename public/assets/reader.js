(() => {
 'use strict';
 const $=s=>document.querySelector(s);
 const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 let storage;
 try{storage=window.localStorage}catch(_){storage={getItem:()=>null,setItem:()=>{throw Error('Unavailable')},removeItem:()=>{}}}
 const allowed=()=>{try{return storage.getItem('ph-consent-v1')==='preferences'}catch(_){return false}};
 const list=window.PHReadingList.create(storage,location.origin,allowed);
 let current=null,scheduled=false;
 function notice(text){let node=$('#readerNotice');if(!node){node=document.createElement('p');node.id='readerNotice';node.className='reader-notice';node.setAttribute('role','status');$('.reader-tools')?.append(node)}if(node)node.textContent=text}
 function sync(){
  const button=$('[data-reader-save]');if(!button||!current)return;
  const saved=list.read().some(x=>x.url===current.url);
  button.textContent=saved?'Saved ✓':'Save story';button.setAttribute('aria-pressed',String(saved));
 }
 function enhanceArticle(){
  const article=$('article.art'),heading=article?.querySelector('h1');if(!heading)return;
  const url=location.href;
  current=window.PHReadingList.clean({url,title:heading.textContent,source:article.querySelector('.by')?.textContent||''},location.origin);
  if(!current||article.querySelector('.reader-tools'))return;
  const words=(article.querySelector('.body')?.textContent||'').trim().split(/\s+/).filter(Boolean).length;
  const tools=document.createElement('div');tools.className='reader-tools';tools.setAttribute('aria-label','Reading tools');
  tools.innerHTML='<span>'+Math.max(1,Math.ceil(words/220))+' min read</span><button type="button" data-reader-save aria-pressed="false">Save story</button><a href="/saved.html">Saved stories</a><label>Text size <select data-reader-size aria-label="Article text size"><option value="normal">Standard</option><option value="large">Large</option><option value="larger">Extra large</option></select></label><button type="button" data-reader-print>Print</button>';
  (article.querySelector('.ah')||heading).insertAdjacentElement('afterend',tools);sync();
 }
 function renderSaved(){
  const root=$('#savedList');if(!root)return;
  const rows=list.read(),count=$('#savedCount');if(count)count.textContent=rows.length+' saved '+(rows.length===1?'story':'stories');
  const choices=$('#savedConsent');if(choices)choices.hidden=allowed();
  const clear=$('[data-reader-clear]');if(clear)clear.disabled=!rows.length;
  root.innerHTML=rows.length?rows.map(row=>'<article class="saved-story"><div><h2><a href="'+esc(row.url)+'">'+esc(row.title)+'</a></h2><p>Saved '+esc(new Date(row.savedAt).toLocaleDateString('en-IN',{day:'numeric',month:'short',year:'numeric'}))+'</p></div><button type="button" data-reader-remove="'+esc(row.url)+'" aria-label="Remove '+esc(row.title)+' from saved stories">Remove</button></article>').join(''):'<div class="reader-empty"><h2>Your next read belongs here.</h2><p>Open a report and choose Save story. Your list stays on this browser, with up to 100 stories.</p><a class="btn" href="/">Explore latest news ↗</a></div>';
 }
 document.addEventListener('click',event=>{
  if(event.target.closest('[data-reader-save]')){
   if(!allowed()){notice('Allow preferences in Settings to save stories on this device.');return}
   const saved=list.read().some(x=>x.url===current?.url);
   const ok=saved?list.remove(current.url):list.add(current);
   sync();notice(ok?(saved?'Removed from saved stories.':'Saved on this device.'):"Your browser couldn't save this story. Check available storage.");
  }
  const remove=event.target.closest('[data-reader-remove]');
  if(remove){list.remove(remove.dataset.readerRemove);renderSaved();$('#savedCount')?.focus()}
  if(event.target.closest('[data-reader-clear]')){list.clear();renderSaved()}
  if(event.target.closest('[data-reader-print]'))window.print();
  if(event.target.closest('[data-reader-consent]')){
   try{storage.setItem('ph-consent-v1','preferences')}catch(_){return}
   renderSaved();sync();
  }
 });
 document.addEventListener('change',event=>{if(event.target.matches('[data-reader-size]'))$('article.art')?.setAttribute('data-reader-size',event.target.value)});
 const refresh=()=>{renderSaved();sync()};
 window.addEventListener('storage',refresh);window.addEventListener('ph-preferences-cleared',refresh);
 document.addEventListener('click',event=>{if(event.target.closest('[data-consent-choice]'))queueMicrotask(refresh)});
 const app=$('#app');if(app)new MutationObserver(()=>{if(!scheduled){scheduled=true;queueMicrotask(()=>{scheduled=false;enhanceArticle()})}}).observe(app,{childList:true,subtree:true});
 enhanceArticle();renderSaved();
})();
