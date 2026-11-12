(() => {
 'use strict';
 const $=s=>document.querySelector(s);
 const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 let storage;
 try{storage=window.localStorage}catch(_){storage={getItem:()=>null,setItem:()=>{throw Error('Unavailable')},removeItem:()=>{}}}
 const allowed=()=>{try{return storage.getItem('ph-consent-v1')==='preferences'}catch(_){return false}};
 const sizeKey='ph-reader-size-v1',sizes=['normal','large','larger'];
 function readingSize(){if(!allowed())return 'normal';try{const size=storage.getItem(sizeKey);return sizes.includes(size)?size:'normal'}catch(_){return 'normal'}}
 const list=window.PHReadingList.create(storage,location.origin,allowed);
 const storageError="Your browser couldn't update saved stories. Check browser storage settings.";
 let current=null,scheduled=false;
 function notice(text){let node=$('#readerNotice');if(!node){node=document.createElement('p');node.id='readerNotice';node.className='reader-notice';node.setAttribute('role','status');$('.reader-tools')?.append(node)}if(node)node.textContent=text}
 function referenceText(article){
  const line=value=>String(value||'').replace(/\s+/g,' ').trim();
  const title=line(article.querySelector('h1')?.textContent);
  const reading=window.PHReadingList.clean({url:location.href,title},location.origin);
  if(!reading)return '';
  const source=line(article.querySelector('.by > span:last-child')?.textContent)||'Source unavailable';
  const published=line(article.querySelector('.by .article-published')?.textContent)||'Publication date unavailable';
  const parts=[title,'Source: '+source,published,'Read on PoliticsHub: '+new URL(reading.url,location.origin).href];
  const original=[...article.querySelectorAll('.src a[href]')].find(link=>line(link.textContent)==='Read the original report');
  try{
   const value=original?.getAttribute('href')||'';
   if(/^https?:\/\//i.test(value)){
    const url=new URL(value);
    if(!url.username&&!url.password)parts.push('Original report: '+url.href);
   }
  }catch(_){}
  return parts.join('\n');
 }
 async function copyReference(button){
  const article=button.closest('article.art'),tools=button.closest('.reader-tools');
  if(!article||!tools||button.dataset.copying)return;
  const text=referenceText(article);if(!text)return;
  const active=()=>article.isConnected&&tools.isConnected&&$('article.art')===article;
  let status=tools.querySelector('[data-reference-status]');
  if(!status){status=document.createElement('p');status.dataset.referenceStatus='';status.className='reader-notice';status.setAttribute('role','status');tools.append(status)}
  tools.querySelector('[data-reference-text]')?.remove();
  button.dataset.copying='true';button.setAttribute('aria-busy','true');status.textContent='Copying reference…';
  try{
   if(!navigator.clipboard?.writeText)throw Error('Clipboard unavailable');
   await navigator.clipboard.writeText(text);
   if(active())status.textContent='Reference copied with source and publication details.';
  }catch(_){
   if(!active())return;
   status.textContent='Could not copy automatically. Select and copy the reference below:';
   const field=document.createElement('textarea');field.dataset.referenceText='';field.readOnly=true;
   field.setAttribute('aria-label','Article reference');field.rows=7;field.style.cssText='width:100%;color:var(--ink);background:var(--card);border:1px solid var(--line);padding:12px';field.value=text;
   tools.append(field);field.focus();field.select();
  }finally{delete button.dataset.copying;button.removeAttribute('aria-busy')}
 }
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
  tools.innerHTML='<span>'+Math.max(1,Math.ceil(words/220))+' min read</span><button type="button" data-reader-save aria-pressed="false">Save story</button><a href="/saved.html">Saved stories</a><label>Text size <select data-reader-size aria-label="Article text size"><option value="normal">Standard</option><option value="large">Large</option><option value="larger">Extra large</option></select></label><button type="button" data-reader-reference>Copy reference</button><button type="button" data-reader-print>Print</button>';
  (article.querySelector('.ah')||heading).insertAdjacentElement('afterend',tools);
  const size=readingSize();article.setAttribute('data-reader-size',size);tools.querySelector('[data-reader-size]').value=size;sync();
 }
 function renderSaved(){
  const root=$('#savedList');if(!root)return;
  const items=list.read(),query=$('#savedQuery')?.value||'';
  const rows=window.PHReadingList.select(items,query,$('#savedOrder')?.value||'recent');
  const count=$('#savedCount');if(count)count.textContent=(items.length&&query.trim()?rows.length+' of '+items.length:items.length)+' saved '+(items.length===1?'story':'stories');
  const filters=$('#savedFilters');if(filters)filters.hidden=!items.length;
  const choices=$('#savedConsent');if(choices)choices.hidden=allowed();
  const clear=$('[data-reader-clear]');if(clear)clear.disabled=!items.length;
  const exporter=$('[data-reader-export]');if(exporter)exporter.disabled=!items.length;
  root.innerHTML=rows.length?rows.map(row=>'<article class="saved-story"><div><h2><a href="'+esc(row.url)+'">'+esc(row.title)+'</a></h2><p>Saved '+esc(new Date(row.savedAt).toLocaleDateString('en-IN',{day:'numeric',month:'short',year:'numeric'}))+'</p></div><button type="button" data-reader-remove="'+esc(row.url)+'" aria-label="Remove '+esc(row.title)+' from saved stories">Remove</button></article>').join(''):items.length?'<div class="reader-empty"><h2>No matching saved stories.</h2><p>Try another headline word or reset the filters to see your full list.</p></div>':'<div class="reader-empty"><h2>Your next read belongs here.</h2><p>Open a report and choose Save story. Your list stays on this browser, with up to 100 stories.</p><a class="btn" href="/">Explore latest news ↗</a></div>';
 }
 $('#savedFilters')?.addEventListener('submit',event=>event.preventDefault());
 $('#savedQuery')?.addEventListener('input',renderSaved);
 $('#savedOrder')?.addEventListener('change',renderSaved);
 $('#savedReset')?.addEventListener('click',()=>{
  $('#savedQuery').value='';$('#savedOrder').value='recent';renderSaved();$('#savedQuery').focus();
 });
 document.addEventListener('click',event=>{
  if(event.target.closest('[data-reader-export]')){
   let url;
   try{
    const file=window.PHReadingList.bookmarks(list.read(),location.origin);
    if(!file.count){notice('Allow preferences and save a story before exporting bookmarks.');return}
    url=URL.createObjectURL(new Blob([file.html],{type:'text/html;charset=utf-8'}));
    const link=document.createElement('a');link.href=url;link.download='politicshub-saved-stories.html';
    document.body.append(link);link.click();link.remove();
    notice('Prepared '+file.count+' saved '+(file.count===1?'link':'links')+'. Import the file using your browser’s bookmarks manager.');
   }catch(_){notice('Your browser could not prepare the bookmark file. Try again.')}
   finally{if(url)setTimeout(()=>URL.revokeObjectURL(url),10000)}
  }
  const reference=event.target.closest('[data-reader-reference]');if(reference)copyReference(reference);
  if(event.target.closest('[data-reader-save]')){
   if(!allowed()){notice('Allow preferences in Settings to save stories on this device.');return}
   const saved=list.read().some(x=>x.url===current?.url);
   const ok=saved?list.remove(current.url):list.add(current);
   sync();notice(ok?(saved?'Removed from saved stories.':'Saved on this device.'):storageError);
  }
  const remove=event.target.closest('[data-reader-remove]');
  if(remove){const ok=list.remove(remove.dataset.readerRemove);if(ok){renderSaved();$('#savedCount')?.focus()}notice(ok?'Removed from saved stories.':storageError)}
  if(event.target.closest('[data-reader-clear]')){const ok=list.clear();if(ok){renderSaved();$('#savedCount')?.focus()}notice(ok?'Saved stories cleared.':storageError)}
  if(event.target.closest('[data-reader-print]'))window.print();
  if(event.target.closest('[data-reader-consent]')){
   try{storage.setItem('ph-consent-v1','preferences')}catch(_){notice("Your browser couldn't enable preferences. Check browser storage settings.");return}
   window.dispatchEvent(new Event('ph-preferences-changed'));
   renderSaved();sync();notice('Preferences enabled. You can now save stories on this device.');
  }
 });
 document.addEventListener('change',event=>{
  if(!event.target.matches('[data-reader-size]')||!sizes.includes(event.target.value))return;
  $('article.art')?.setAttribute('data-reader-size',event.target.value);
  if(allowed())try{storage.setItem(sizeKey,event.target.value)}catch(_){notice("Text size changed for this article, but your browser couldn't remember it.")}
 });
 const refresh=()=>{renderSaved();sync()};
 window.addEventListener('storage',refresh);window.addEventListener('ph-preferences-cleared',refresh);window.addEventListener('ph-preferences-changed',refresh);
 document.addEventListener('click',event=>{if(event.target.closest('[data-consent-choice]'))queueMicrotask(refresh)});
 const app=$('#app');if(app)new MutationObserver(()=>{if(!scheduled){scheduled=true;queueMicrotask(()=>{scheduled=false;enhanceArticle()})}}).observe(app,{childList:true,subtree:true});
 enhanceArticle();renderSaved();
})();
