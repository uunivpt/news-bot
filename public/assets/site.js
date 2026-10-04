(function(){try{const t=localStorage.getItem("ph_theme");document.documentElement.dataset.theme=t==="dark"?"dark":"bright"}catch(e){document.documentElement.dataset.theme="bright"}})();

const PH={
  state:{
    category:new URLSearchParams(location.search).get("category")||"all",
    search:"",
    rows:[],
    loading:false,
    bound:false,
    request:0
  },
  $:(id)=>document.getElementById(id),
  esc:(v)=>String(v??"").replace(/[&<>"]/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[m])),
  validImage:(v)=>{
    const s=String(v||"").trim();
    return !!s&&!/placeholder|default[-_ ]?image|no[-_ ]?image|noimage|blank[-_ ]?image|black[-_ ]?image|dummy[-_ ]?image/i.test(s);
  },
  fmt:(v)=>{
    if(!v)return"";
    const s=String(v);
    if(/^[0-9]{1,2} [A-Za-z]{3} [0-9]{4}/.test(s))return s;
    const d=new Date(s);
    return Number.isNaN(d.getTime())?s:d.toLocaleString("en-IN",{day:"2-digit",month:"short",year:"numeric",hour:"2-digit",minute:"2-digit",hour12:false});
  },
  storage:{
    get(k){try{return localStorage.getItem(k)||""}catch(e){return""}},
    set(k,v){try{localStorage.setItem(k,v)}catch(e){}},
    remove(k){try{localStorage.removeItem(k)}catch(e){}}
  }
};

PH.fetchJSON=async function(url,ms=12000){
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),ms);
  try{
    const response=await fetch(url,{cache:"no-store",credentials:"same-origin",headers:{Accept:"application/json"},signal:controller.signal});
    if(!response.ok)throw Error("HTTP "+response.status);
    return await response.json();
  }finally{clearTimeout(timer)}
};

PH.rowsFrom=function(payload){
  if(Array.isArray(payload))return payload;
  if(payload&&Array.isArray(payload.news))return payload.news;
  if(payload&&Array.isArray(payload.items))return payload.items;
  if(payload&&Array.isArray(payload.data))return payload.data;
  return[];
};

PH.normalizeRows=function(rows){
  return rows.filter(x=>x&&typeof x==="object"&&x.title).map(n=>({
    ...n,
    category:String(n.category||"general").toLowerCase(),
    summary:n.summary||n.bot_summary||n.bot_article||n.article||"",
    published_at:n.published_at||n.published_at_site||n.created_at||""
  }));
};

PH.getNews=async function(){
  const category=this.state.category;
  const api="/api/news?"+new URLSearchParams({category,limit:"100"}).toString();
  const snapshot="/news-data.json?ts="+Date.now();
  try{
    const live=this.normalizeRows(this.rowsFrom(await this.fetchJSON(api,10000)));
    if(live.length)return live;
  }catch(e){}
  try{
    const snap=this.normalizeRows(this.rowsFrom(await this.fetchJSON(snapshot,10000)));
    return category==="all"?snap:snap.filter(n=>n.category===String(category).toLowerCase());
  }catch(e){return[]}
};

PH.filtered=function(){
  const q=this.state.search.trim().toLowerCase();
  return this.state.rows.filter(n=>!q||[n.title,n.summary,n.bot_summary,n.category,n.source_name].filter(Boolean).join(" ").toLowerCase().includes(q));
};

PH.image=function(n,hero=false){
  const attr=hero?'fetchpriority="high"':'loading="lazy"';
  return this.validImage(n.image_url)?'<img '+attr+' src="'+this.esc(n.image_url)+'" alt="" onerror="this.remove()">':"";
};

PH.card=function(n){
  const has=this.validImage(n.image_url);
  return '<a class="story-card '+(has?"":"no-image")+'" href="/article.html?id='+encodeURIComponent(n.id)+'">'+
    '<div><div class="story-kicker">'+this.esc(n.category||"News")+'</div>'+
    '<h3 class="story-title">'+this.esc(n.title||"Untitled story")+'</h3>'+
    '<p class="story-summary">'+this.esc(n.summary||"")+'</p>'+
    '<div class="story-meta">'+this.esc(this.fmt(n.published_at))+' · '+this.esc(n.source_name||"PoliticsHub")+'</div></div>'+
    (has?this.image(n):"")+'</a>';
};

PH.setActiveCategory=function(){
  document.querySelectorAll("[data-filter]").forEach(b=>b.classList.toggle("active",b.dataset.filter===this.state.category));
  document.querySelectorAll("[data-cat]").forEach(a=>{if(a.dataset.cat)a.classList.toggle("active",a.dataset.cat===this.state.category)});
};

PH.renderHome=function(){
  const rows=this.filtered(),news=this.$("news");
  if(!news)return;
  news.innerHTML=rows.length?rows.map(this.card.bind(this)).join(""):'<div class="empty">No published stories match this view.</div>';
  const count=this.$("count");if(count)count.textContent=rows.length+" stories";
  const heroMedia=this.$("heroMedia"),heroCopy=this.$("heroCopy"),ticker=this.$("ticker");
  if(!heroMedia||!heroCopy)return;
  if(rows[0]){
    const n=rows[0],has=this.validImage(n.image_url);
    heroMedia.className="lead-media"+(has?"":" empty");
    heroMedia.innerHTML=has?this.image(n,true):"";
    heroCopy.innerHTML='<div class="kicker">'+this.esc(n.category||"Latest")+' · JUST IN</div>'+
      '<h1>'+this.esc(n.title)+'</h1><p class="lead-dek">'+this.esc(n.summary||"")+'</p>'+
      '<div class="meta">'+this.esc(this.fmt(n.published_at))+' · '+this.esc(n.source_name||"PoliticsHub")+'</div>'+
      '<a class="read" href="/article.html?id='+encodeURIComponent(n.id)+'">Read full story →</a>';
    if(ticker)ticker.textContent=n.title;
  }else{
    heroMedia.className="lead-media empty";heroMedia.innerHTML="";
    heroCopy.innerHTML='<div class="kicker">PoliticsHub</div><h1>No published news</h1><p class="lead-dek">There are currently no published stories in this section.</p>';
    if(ticker)ticker.textContent="No published updates";
  }
  this.setActiveCategory();
};

PH.loadHome=async function(){
  if(this.state.loading)return;
  this.state.loading=true;
  const request=++this.state.request;
  const news=this.$("news");
  if(news&&!this.state.rows.length)news.innerHTML='<div class="skeleton"></div><div class="skeleton"></div>';
  try{
    const rows=await this.getNews();
    if(request!==this.state.request)return;
    this.state.rows=rows;
    this.renderHome();
  }catch(e){
    if(request===this.state.request){
      this.state.rows=[];
      if(news)news.innerHTML='<div class="empty">News is temporarily unavailable. Please refresh shortly.</div>';
    }
  }finally{if(request===this.state.request)this.state.loading=false}
};

PH.updateUrl=function(){
  const category=this.state.category;
  history.replaceState(null,"",category==="all"?"/":"/?category="+encodeURIComponent(category));
};

PH.openSearch=function(){
  const toolbar=document.querySelector(".toolbar"),search=this.$("search");
  if(!toolbar||!search){location.href="/#search";return}
  toolbar.classList.add("search-open");
  search.focus();
  search.scrollIntoView({behavior:"smooth",block:"center"});
};

PH.bindHome=function(){
  if(this.state.bound)return;
  this.state.bound=true;
  const $=this.$,search=$("search"),menu=$("menu"),backdrop=$("drawerBackdrop");
  this.setActiveCategory();

  document.querySelectorAll("[data-cat]").forEach(a=>{
    a.addEventListener("click",e=>{
      const cat=a.dataset.cat;if(!cat)return;
      e.preventDefault();
      if(cat===this.state.category)return;
      this.state.category=cat;this.state.search="";if(search)search.value="";
      this.updateUrl();this.loadHome();
    });
  });

  document.querySelectorAll("[data-filter]").forEach(b=>{
    b.addEventListener("click",()=>{
      const cat=b.dataset.filter||"all";
      if(cat===this.state.category){this.setActiveCategory();return}
      this.state.category=cat;this.state.search="";if(search)search.value="";
      this.updateUrl();this.setActiveCategory();this.loadHome();
      b.scrollIntoView({behavior:"smooth",block:"nearest",inline:"center"});
    });
  });

  if(search)search.addEventListener("input",()=>{this.state.search=search.value;this.renderHome()});
  if(menu&&backdrop)menu.addEventListener("click",()=>backdrop.classList.add("open"));
  $("drawerClose")?.addEventListener("click",()=>backdrop?.classList.remove("open"));
  backdrop?.addEventListener("click",e=>{if(e.target===backdrop)backdrop.classList.remove("open")});
  document.querySelectorAll(".mobile-drawer a").forEach(a=>a.addEventListener("click",()=>backdrop?.classList.remove("open")));

  $("searchTrigger")?.addEventListener("click",()=>this.openSearch());

  $("accept")?.addEventListener("click",()=>{
    this.storage.set("ph_cookie_consent","accepted");
    $("cookie")?.classList.remove("show");
  });
  if(!this.storage.get("ph_cookie_consent"))$("cookie")?.classList.add("show");

  if(location.hash==="#search")setTimeout(()=>this.openSearch(),50);
  this.loadHome();
  setInterval(()=>{if(!document.hidden)this.loadHome()},60000);
};

PH.loadArticle=async function(){
  const id=new URLSearchParams(location.search).get("id"),page=this.$("articlePage");
  if(!id)return this.articleError("Story not found");
  try{
    let n;
    try{n=await this.fetchJSON("/api/news/"+encodeURIComponent(id),12000)}
    catch(e){const rows=this.rowsFrom(await this.fetchJSON("/news-data.json?ts="+Date.now(),12000));n=rows.find(x=>String(x.id)===String(id))}
    if(!n||n.error)throw Error();
    const has=this.validImage(n.image_url);
    document.title=(n.title||"Article")+" — PoliticsHub.in";
    page.innerHTML='<a class="back" href="/">← Back to news</a><div class="article-kicker">'+this.esc(n.category||"News")+'</div>'+
      '<h1 class="article-title">'+this.esc(n.title||"Untitled story")+'</h1>'+
      '<p class="article-dek">'+this.esc(n.summary||n.bot_summary||n.article||"")+'</p>'+
      '<div class="article-meta">'+this.esc(this.fmt(n.published_at||n.published_at_site))+' · '+this.esc(n.source_name||"PoliticsHub")+'</div>'+
      (has?this.image(n,true).replace("<img ","<img class=\"article-hero\" "):"")+
      '<div class="article-body">'+this.esc(n.article||n.bot_article||n.summary||n.bot_summary||"")+'</div>'+
      '<div class="article-share"><span>SHARE</span><a target="_blank" rel="noopener noreferrer" href="https://wa.me/?text='+encodeURIComponent((n.title||"PoliticsHub story")+" "+location.href)+'">WhatsApp</a><a target="_blank" rel="noopener noreferrer" href="https://t.me/share/url?url='+encodeURIComponent(location.href)+'&text='+encodeURIComponent(n.title||"PoliticsHub story")+'">Telegram</a><a target="_blank" rel="noopener noreferrer" href="https://www.facebook.com/sharer/sharer.php?u='+encodeURIComponent(location.href)+'">Facebook</a><a target="_blank" rel="noopener noreferrer" href="https://twitter.com/intent/tweet?text='+encodeURIComponent(n.title||"PoliticsHub story")+'&url='+encodeURIComponent(location.href)+'">X</a></div>'+
      (n.source_name?'<div class="article-source">Source: '+(n.url?'<a href="'+this.esc(n.url)+'" target="_blank" rel="noopener noreferrer">'+this.esc(n.source_name)+'</a>':this.esc(n.source_name))+'</div>':"");
  }catch(e){this.articleError("Article unavailable","The requested story could not be loaded.")}
};

PH.articleError=function(title,msg="Please return to the newsroom and try another story."){
  const page=this.$("articlePage");if(page)page.innerHTML='<a class="back" href="/">← Back to news</a><div class="error-state"><h1>'+this.esc(title)+'</h1><p>'+this.esc(msg)+'</p></div>';
};

PH.bindChrome=function(){
  const backdrop=document.getElementById("drawerBackdrop"),menu=document.getElementById("menu"),close=document.getElementById("drawerClose");
  if(menu&&backdrop&&!menu.dataset.bound){menu.dataset.bound="1";menu.addEventListener("click",()=>backdrop.classList.add("open"))}
  if(close&&backdrop&&!close.dataset.bound){close.dataset.bound="1";close.addEventListener("click",()=>backdrop.classList.remove("open"))}
  if(backdrop&&!backdrop.dataset.bound){backdrop.dataset.bound="1";backdrop.addEventListener("click",e=>{if(e.target===backdrop)backdrop.classList.remove("open")})}
  document.querySelectorAll(".mobile-drawer a").forEach(a=>{if(!a.dataset.bound){a.dataset.bound="1";a.addEventListener("click",()=>backdrop?.classList.remove("open"))}});
  const trigger=document.getElementById("searchTrigger");
  if(trigger&&!trigger.dataset.bound){trigger.dataset.bound="1";trigger.addEventListener("click",()=>this.openSearch())}
};

PH.setArticleMeta=function(n){const desc=String(n.summary||n.bot_summary||n.article||"").slice(0,300);const set=(name,content)=>{let m=document.querySelector('meta[name="'+name+'"]');if(!m){m=document.createElement("meta");m.name=name;document.head.appendChild(m)}m.content=content};const prop=(name,content)=>{let m=document.querySelector('meta[property="'+name+'"]');if(!m){m=document.createElement("meta");m.setAttribute("property",name);document.head.appendChild(m)}m.content=content};set("description",desc);prop("og:title",n.title||"PoliticsHub.in");prop("og:description",desc);prop("og:type","article");prop("og:url",location.href);if(n.image_url)prop("og:image",n.image_url);let canonical=document.querySelector('link[rel="canonical"]');if(!canonical){canonical=document.createElement("link");canonical.rel="canonical";document.head.appendChild(canonical)}canonical.href=location.href};
