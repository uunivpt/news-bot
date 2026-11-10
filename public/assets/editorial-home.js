(function(){
 function phTs(v){var raw=String(v||'').trim();if(!raw)return 0;raw=raw.split('·').join(' ').split('•').join(' ');var t=Date.parse(raw);return Number.isFinite(t)?t:0}
 function phSorted(items){return Array.from(items).sort(function(a,b){return Number(!!b.editorial_featured)-Number(!!a.editorial_featured)||phTs(b.editorial_featured_at)-phTs(a.editorial_featured_at)||phTs(b.date)-phTs(a.date)||Number(b.id||0)-Number(a.id||0)})}
 function reportType(i){return i.report_type || (String(i.body||'').trim().split(/\s+/).length>=500?'Detailed report':'Short brief')}
 function sourceActions(item){
  var reports=item.related_reports||[];
  var valid=url=>/^https?:\/\//i.test(url||'');
  if(reports.length>1){
   return '<details class="ph14-sources"><summary>'+reports.length+' reports</summary><ul>'+reports.filter(r=>valid(r.url)).map(r=>'<li><a href="'+esc(r.url)+'">'+esc(r.title)+'</a> · '+esc(r.source_name)+' · '+esc(fmt(r.published_at))+'</li>').join('')+'</ul></details>';
  }
  return valid(item.url)?'<a class="ph14-source-link" href="'+esc(item.url)+'">Original source ↗</a>':'';
 }
 function phMeta(i){return '<span class="meta"><b>'+esc(i.category||'News')+' · '+reportType(i)+'</b><span>'+esc(ago(i.date)||fmt(i.date))+'</span><span>'+esc(i.source||'PoliticsHub')+'</span></span>'}
 function phMedia(i,lead){var graphic=lead&&!i.image&&/^\d+$/.test(String(i.id||''));if(!i.image&&!graphic)return'';var src=graphic?'/api/og/'+encodeURIComponent(String(i.id)):i.image;return '<div class="'+(lead?'ph14-media':'ph14-thumb')+'"><img src="'+esc(src)+'" alt="'+(graphic?'PoliticsHub editorial graphic, not a news photograph':'')+'" loading="'+(lead?'eager':'lazy')+'" decoding="async">'+(graphic?'<small class="ph14-graphic-label">PoliticsHub headline graphic · Not a news photograph</small>':'')+'</div>'}
 home=function(c){
  document.documentElement.lang=c==='hindi'?'hi':'en';
  setActive(c);document.title=(c==='all'?'':(CATS.find(function(x){return x[0]===c})||['',''])[1]+' — ')+'PoliticsHub.in';
  var list=phSorted(S.items.filter(function(i){return inCat(i,c)})),lead=list[0],briefs=list.slice(1,4),rows=list.slice(4,24),remaining=list.slice(24);
  var found=CATS.find(function(x){return x[0]===c}),label=found?found[1]:'Home',day=new Date().toLocaleDateString('en-IN',{weekday:'long',day:'numeric',month:'long',year:'numeric',timeZone:'Asia/Kolkata'});
  var ui=window.PHNewsroomUI;
  var cats=NAV_CATS.map(function(x){return '<a href="'+hl(x[0])+'" class="'+(x[0]===c?'on':'')+'"'+(x[0]===c?' aria-current="page"':'')+'>'+esc(x[1])+'</a>'}).join('');
  var start='<div class="ph14-home ph-ui-home"><div class="ph14-datebar"><strong>PoliticsHub News Desk</strong><span>'+esc(day)+' · '+esc(label)+'</span></div><nav class="ph14-cats" aria-label="News desks">'+cats+'</nav>';
  if(!lead&&c==='all'&&document.querySelector('#news-home-title'))return;
  if(!lead){$('#app').innerHTML=start+'<div class="msg"><h1>No reports in this desk yet</h1><p>Browse another desk or return when more stories are published.</p><p><a class="btn secondary" href="/archive/">Browse the archive</a></p></div>'+'</div>';if(ui)ui.bind($('#app .ph-ui-home'));return}
  var leadPublished=phTs(lead.date);
  var leadPublishedMarkup=leadPublished>0 && leadPublished<Date.now()+86400000
    ? '<time class="ph14-published-date" datetime="'+new Date(leadPublished).toISOString()+'">Published: '+esc(new Date(leadPublished).toLocaleString('en-IN',{day:'numeric',month:'short',year:'numeric',hour:'numeric',minute:'2-digit',timeZone:'Asia/Kolkata'}))+' IST</time>'
    : '';
  var leadHtml='<a class="ph14-lead ph-ui-card" href="'+esc(articleHref(lead))+'"><div class="ph14-copy"><span class="ph14-kicker"><i aria-hidden="true"></i>'+(lead.is_breaking?'Breaking · ':'')+esc(lead.category||'Top story')+'</span><h1>'+esc(lead.title)+'</h1><p>'+esc(lead.summary||'')+'</p><small class="ph14-source-label">Source: '+esc(lead.source||'Original publisher')+'</small>'+leadPublishedMarkup+'<span class="ph14-read">'+(reportType(lead)==='Short brief'?'Read source-linked brief':'Read detailed report')+' <b aria-hidden="true">↗</b></span></div>'+phMedia(lead,true)+'</a>';
  leadHtml='<div>'+leadHtml+sourceActions(lead)+'</div>';
  var briefHtml=briefs.map(function(i){return '<div><a class="ph14-brief ph-ui-card" href="'+esc(articleHref(i))+'">'+phMeta(i)+'<h3>'+esc(i.title)+'</h3>'+(i.summary?'<p>'+esc(i.summary)+'</p>':'')+'</a>'+sourceActions(i)+'</div>'}).join('');
  function phRow(i){return '<div><a class="ph14-row ph-ui-card ph-ui-reveal" href="'+esc(articleHref(i))+'"><div>'+phMeta(i)+'<h3>'+esc(i.title)+'</h3>'+(i.summary?'<p>'+esc(i.summary)+'</p>':'')+'</div>'+phMedia(i,false)+'</a>'+sourceActions(i)+'</div>'}
  var rowHtml=rows.map(phRow).join('');
  var subscribeHtml='<section class="ph14-newsletter" aria-labelledby="ph14NlTitle"><div><span class="ph14-newsletter-eyebrow">THE POLITICSHUB BRIEF</span><h2 id="ph14NlTitle">One important story.<br>Delivered daily.</h2><p>A clear, source-linked news briefing delivered to your email. Free, opt-in, and easy to unsubscribe.</p></div><form id="homeNl"><label for="homeNlEmail" class="ph14-newsletter-label">Your email address</label><div class="ph14-newsletter-fields"><input id="homeNlEmail" type="email" placeholder="you@example.com" autocomplete="email" required><button class="btn" type="submit">Subscribe free →</button></div><label class="ph14-newsletter-check"><input name="privacy" type="checkbox" required> I agree to receive daily emails and the <a href="/privacy.html">Privacy Policy</a>.</label><label class="ph14-newsletter-check"><input name="adult" type="checkbox" required> I confirm I am 18 or older.</label><p id="homeNlMsg" class="ph14-newsletter-message" role="status" aria-live="polite"></p><p class="ph14-newsletter-hint">We email you a confirmation link first. Unsubscribe anytime.</p></form></section>';
  var intro='<div class="ph-ui-intro"><div><span class="ph-ui-eyebrow">INDEPENDENT READING. INFORMED PERSPECTIVES.</span><h2>What matters, clearly.</h2><p>India, the world and the stories in between. Always with the source.</p></div><div class="ph-ui-intro-actions"><button type="button" class="btn secondary ph-ui-shortcut" data-news-search>'+(ui?ui.icon('search'):'')+'<span>Find a story</span><kbd aria-hidden="true">Ctrl / ⌘ K</kbd></button><a class="btn" href="/briefing/">Quick briefing <span aria-hidden="true">↗</span></a></div></div>';
  var density='<div class="ph-ui-density" role="group" aria-label="Story list spacing"><button type="button" data-news-density="comfortable" aria-pressed="true">Comfortable</button><button type="button" data-news-density="compact" aria-pressed="false">Compact</button></div>';
  $('#app').innerHTML=start+intro+'<section class="ph14-hero" aria-label="Top stories">'+leadHtml+'<aside class="ph14-side"><div class="ph14-side-head"><h2>On the radar</h2><span>From this feed</span></div>'+briefHtml+'</aside></section>'+'<div class="ph14-section-head"><div><span class="ph-ui-eyebrow">THE NEWS STREAM</span><h2>Latest stories</h2></div>'+density+'</div><section class="ph14-feed" aria-label="Latest reports" data-density="comfortable"><div>'+rowHtml+'</div></section>'+subscribeHtml+'</div>';
  if(remaining.length){
   var listEl=$('#app .ph14-feed > div:first-child');
   if(listEl){
    var button=document.createElement('button'),offset=0;
    button.type='button';button.className='btn secondary ph14-more';
    button.textContent='Load more stories';
    button.addEventListener('click',function(){
     var batch=remaining.slice(offset,offset+20);
     var restoreFocus=document.activeElement===button;
     button.insertAdjacentHTML('beforebegin',batch.map(phRow).join(''));
     var inserted=button.previousElementSibling;
     for(var n=1;n<batch.length;n++)inserted=inserted.previousElementSibling;
     offset+=batch.length;
     if(offset>=remaining.length)button.remove();
     else button.textContent='Load more stories';
     if(ui)ui.observe($('#app .ph-ui-home'));
     if(restoreFocus&&inserted){inserted.classList.add('is-visible');(inserted.querySelector('a')||inserted).focus()}
    });
    listEl.append(button);
   }
  }
  fx();
  if(typeof bindNewsletter==='function')bindNewsletter();
  if(ui)ui.bind($('#app .ph-ui-home'));
 };
 if(S&&S.items&&S.items.length)render();
})();
