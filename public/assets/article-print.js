/* The browser's Print and Save as PDF share one branded, paginated article edition. */
(() => {
  'use strict';
  const prepared=new WeakSet();
  let scheduled=false,position=null;
  function stylesheet(){
    if(document.querySelector('[data-article-print-style]'))return;
    const link=document.createElement('link');link.rel='stylesheet';link.media='print';link.href='/assets/article-print.css?v=1';
    link.dataset.articlePrintStyle='';link.dataset.dynamicPrintStyle='';document.head.append(link);
  }
  function header(article){
    let head=article.querySelector('.article-print-masthead');
    if(!head){
      head=document.createElement('div');head.className='article-print-masthead';head.hidden=true;head.setAttribute('aria-hidden','true');
      head.innerHTML='<div class="article-print-brand"><img src="/favicon.svg" alt="PoliticsHub" width="44" height="40"><strong>PoliticsHub.in</strong></div><div class="article-print-meta"><span data-print-time-label>Print edition · IST</span><time data-print-clock></time></div>';
      article.prepend(head);
    }
    if(!article.querySelector('.article-print-tagline')){
      const line=document.createElement('p');line.className='article-print-tagline';line.hidden=true;line.setAttribute('aria-hidden','true');
      line.textContent='What matters, clearly. · Source-linked news at politicshub.in';head.after(line);
    }
    if(!article.querySelector('.article-print-end')){
      const foot=document.createElement('div');foot.className='article-print-end';foot.hidden=true;foot.setAttribute('aria-hidden','true');
      const link=document.createElement('a');link.href=location.href;link.textContent=location.href;
      foot.append('Read this report online: ',link);article.append(foot);
    }
  }
  function clock(article){
    const now=new Date();
    const value=now.toLocaleString('en-IN',{day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit',hour12:true,timeZone:'Asia/Kolkata'})+' IST';
    article.querySelectorAll('[data-print-clock]').forEach(node=>{node.textContent=value;node.dateTime=now.toISOString()});
    article.querySelectorAll('[data-print-time-label]').forEach(node=>node.textContent='Printed / saved · IST');
    let style=document.querySelector('[data-print-page-clock]');
    if(!style){style=document.createElement('style');style.dataset.printPageClock='';document.head.append(style)}
    style.textContent='@media print{@page{@top-right{content:'+JSON.stringify(value)+';font:8pt Arial,sans-serif;color:#59615d}}@page:first{@top-right{content:""}}}';
  }
  function ensure(){
    const article=document.querySelector('article.art');
    if(!article?.querySelector('h1')){
      document.querySelector('[data-dynamic-print-style]')?.remove();document.querySelector('[data-print-page-clock]')?.remove();return;
    }
    if(prepared.has(article))return;
    prepared.add(article);stylesheet();header(article);clock(article);
  }
  function restore(){
    if(position?.marker.isConnected&&position.body.isConnected)position.marker.replaceWith(position.body);
    else position?.marker.remove();
    position=null;
  }
  window.addEventListener('beforeprint',()=>{
    ensure();const article=document.querySelector('article.art');if(!article)return;
    clock(article);restore();
    // Read the report immediately after the headline, before its image and figures.
    const body=article.querySelector('.body'),heading=article.querySelector('.ah');
    if(body&&heading){const marker=document.createComment('article body position');body.before(marker);heading.after(body);position={body,marker}}
  });
  window.addEventListener('afterprint',restore);
  const root=document.querySelector('#app');
  if(root)new MutationObserver(()=>{if(!scheduled){scheduled=true;queueMicrotask(()=>{scheduled=false;ensure()})}}).observe(root,{childList:true,subtree:true});
  ensure();
})();
