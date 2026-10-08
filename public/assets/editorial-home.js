(function(){
 function phTs(v){var raw=String(v||'').trim();if(!raw)return 0;raw=raw.split('·').join(' ').split('•').join(' ');var t=Date.parse(raw);return Number.isFinite(t)?t:0}
 function phSorted(items){return Array.from(items).sort(function(a,b){return phTs(b.date)-phTs(a.date)||Number(b.id||0)-Number(a.id||0)})}
 function phMeta(i){return '<span class="meta"><b>'+esc(i.category||'News')+'</b><span>'+esc(ago(i.date)||fmt(i.date))+'</span><span>'+esc(i.source||'PoliticsHub')+'</span></span>'}
 function phMedia(i,lead){if(!i.image)return'';return '<div class="'+(lead?'ph14-media':'ph14-thumb')+'"><img src="'+esc(i.image)+'" alt="" loading="'+(lead?'eager':'lazy')+'" decoding="async"></div>'}
 home=function(c){
  setActive(c);document.title=(c==='all'?'':(CATS.find(function(x){return x[0]===c})||['',''])[1]+' — ')+'PoliticsHub.in';
  var list=phSorted(S.items.filter(function(i){return inCat(i,c)})),lead=list[0],briefs=list.slice(1,4),rows=list.slice(4,24),remaining=list.slice(24);
  var found=CATS.find(function(x){return x[0]===c}),label=found?found[1]:'Home',day=new Date().toLocaleDateString('en-IN',{weekday:'long',day:'numeric',month:'long',year:'numeric'});
  var cats=CATS.map(function(x){return '<a href="'+hl(x[0])+'" class="'+(x[0]===c?'on':'')+'">'+esc(x[1])+'</a>'}).join('');
  if(!lead){$('#app').innerHTML='<div class="ph14-home"><div class="msg"><h3>No stories yet</h3><p>Fresh reports will appear here automatically.</p></div></div>';return}
  var leadHtml='<a class="ph14-lead" href="'+esc(articleHref(lead))+'"><div class="ph14-copy"><span class="ph14-kicker"><i></i>'+(lead.is_breaking?'Breaking · ':'')+esc(lead.category||'Top story')+'</span><h1>'+esc(lead.title)+'</h1><p>'+esc(lead.summary||'')+'</p><span class="ph14-read">Read full report <b>↗</b></span></div>'+phMedia(lead,true)+'</a>';
  var briefHtml=briefs.map(function(i){return '<a class="ph14-brief" href="'+esc(articleHref(i))+'">'+phMeta(i)+'<h3>'+esc(i.title)+'</h3>'+(i.summary?'<p>'+esc(i.summary)+'</p>':'')+'</a>'}).join('');
  function phRow(i){return '<a class="ph14-row" href="'+esc(articleHref(i))+'"><div>'+phMeta(i)+'<h3>'+esc(i.title)+'</h3>'+(i.summary?'<p>'+esc(i.summary)+'</p>':'')+'</div>'+phMedia(i,false)+'</a>'}
  var rowHtml=rows.map(phRow).join('');
  var desks=CATS.slice(1).map(function(x){return '<a href="'+hl(x[0])+'">'+esc(x[1])+'</a>'}).join('');
  $('#app').innerHTML='<div class="ph14-home"><div class="ph14-datebar"><strong>PoliticsHub News Desk</strong><span>'+esc(day)+' · '+esc(label)+'</span></div><div class="ph14-cats">'+cats+'</div><section class="ph14-hero">'+leadHtml+'<aside class="ph14-side"><div class="ph14-side-head"><h2>Just in</h2><span>Latest updates</span></div>'+briefHtml+'</aside></section><div class="ph14-section-head"><h2>Latest stories</h2><span>'+list.length+' reports</span></div><section class="ph14-feed"><div>'+rowHtml+'</div><aside class="ph14-rail"><div class="ph14-rail-card"><h3>Browse desks</h3><p>Follow the stories shaping India and the world.</p><div class="ph14-desk">'+desks+'</div></div><div class="ph14-rail-card"><h3>Live newsroom</h3><div class="ph14-status '+(S.mode==='api'||S.mode==='snapshot'?'':'offline')+'"><i></i><span>'+(S.mode==='api'?'News feed refreshes automatically':S.mode==='snapshot'?'Source feed checks for news automatically':'Offline · showing previously loaded stories')+'</span></div></div><div class="ph14-rail-card"><h3>PoliticsHub Brief</h3><p>Important stories, clearly presented. No clutter.</p></div></aside></section></div>';
  if(remaining.length){
   var listEl=$('#app .ph14-feed > div:first-child');
   if(listEl){
    var button=document.createElement('button'),offset=0;
    button.type='button';button.className='btn secondary ph14-more';
    button.textContent='Load more stories ('+remaining.length+' remaining)';
    button.addEventListener('click',function(){
     var batch=remaining.slice(offset,offset+20);
     button.insertAdjacentHTML('beforebegin',batch.map(phRow).join(''));
     offset+=batch.length;
     if(offset>=remaining.length)button.remove();
     else button.textContent='Load more stories ('+(remaining.length-offset)+' remaining)';
    });
    listEl.append(button);
   }
  }
  fx()
 };
 if(S&&S.items&&S.items.length)render();
})();
