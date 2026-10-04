const PH={
  state:{
    category:new URLSearchParams(location.search).get("category")||"all",
    search:"",
    rows:[],
    loading:false,
    bound:false
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
  }
};

PH.fetchJSON=async function(url,ms=12000){
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),ms);
  try{
    const response=await fetch(url,{cache:"no-store",credentials:"same-origin",signal:controller.signal});
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

  // The live API is the primary source. The checked-in snapshot is a
  // deterministic fallback so the homepage can still render if the API is slow.
  try{
    const live=this.normalizeRows(this.rowsFrom(await this.fetchJSON(api,12000)));
    if(live.length)return live;
  }catch(e){}

  try{
    const snap=this.normalizeRows(this.rowsFrom(await this.fetchJSON(snapshot,12000)));
    if(category==="all")return snap;
    return snap.filter(n=>n.category===String(category).toLowerCase());
  }catch(e){
    return[];
  }
};

PH.filtered=function(){
  const q=this.state.search.trim().toLowerCase();
  return this.state.rows.filter(n=>!q||[
    n.title,n.summary,n.bot_summary,n.category,n.source_name
  ].filter(Boolean).join(" ").toLowerCase().includes(q));
};

PH.image=function(n,hero=false){
  const attr=hero?'fetchpriority="high"':'loading="lazy"';
  return this.validImage(n.image_url)
    ? '<img '+attr+' src="'+this.esc(n.image_url)+'" alt="" onerror="this.remove()">'
    : "";
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
  document.querySelectorAll("[data-filter]").forEach(b=>{
    b.classList.toggle("active",b.dataset.filter===this.state.category);
  });
  document.querySelectorAll("[data-cat]").forEach(a=>{
    if(a.dataset.cat)a.classList.toggle("active",a.dataset.cat===this.state.category);
  });
};

PH.renderHome=function(){
  const rows=this.filtered(),$=this.$;
  $("news").innerHTML=rows.length
    ?rows.map(this.card.bind(this)).join("")
    :'<div class="empty">No published stories match this view.</div>';
  $("count").textContent=rows.length+" stories";

  if(rows[0]){
    const n=rows[0],has=this.validImage(n.image_url);
    $("heroMedia").className="lead-media"+(has?"":" empty");
    $("heroMedia").innerHTML=has?this.image(n,true):"";
    $("heroCopy").innerHTML=
      '<div class="kicker">'+this.esc(n.category||"Latest")+' · JUST IN</div>'+
      '<h1>'+this.esc(n.title)+'</h1>'+
      '<p class="lead-dek">'+this.esc(n.summary||"")+'</p>'+
      '<div class="meta">'+this.esc(this.fmt(n.published_at))+' · '+this.esc(n.source_name||"PoliticsHub")+'</div>'+
      '<a class="read" href="/article.html?id='+encodeURIComponent(n.id)+'">Read full story</a>';
    $("ticker").textContent=n.title;
  }else{
    $("heroMedia").className="lead-media empty";
    $("heroMedia").innerHTML="";
    $("heroCopy").innerHTML='<div class="kicker">PoliticsHub</div><h1>No published news</h1><p class="lead-dek">There are currently no published stories in this section.</p>';
    $("ticker").textContent="No published updates";
  }
  this.setActiveCategory();
};

PH.loadHome=async function(){
  if(this.state.loading)return;
  this.state.loading=true;
  const news=this.$("news");
  if(news&&!this.state.rows.length)news.innerHTML='<div class="skeleton"></div><div class="skeleton"></div>';
  try{
    this.state.rows=await this.getNews();
    this.renderHome();
  }catch(e){
    this.state.rows=[];
    if(news)news.innerHTML='<div class="empty">News is temporarily unavailable. Please refresh shortly.</div>';
  }finally{this.state.loading=false}
};

PH.updateUrl=function(){
  const category=this.state.category;
  const url=category==="all"?"/":"/?category="+encodeURIComponent(category);
  history.replaceState(null,"",url);
};

PH.bindHome=function(){
  if(this.state.bound)return;
  this.state.bound=true;

  const $=this.$,search=$("search"),menu=$("menu"),backdrop=$("drawerBackdrop");
  this.setActiveCategory();

  document.querySelectorAll("[data-cat]").forEach(a=>{
    a.addEventListener("click",e=>{
      const cat=a.dataset.cat;
      if(!cat)return;
      e.preventDefault();
      if(cat===this.state.category)return;
      this.state.category=cat;
      this.state.search="";
      if(search)search.value="";
      this.updateUrl();
      this.loadHome();
    });
  });

  document.querySelectorAll("[data-filter]").forEach(b=>{
    b.addEventListener("click",()=>{
      this.state.category=b.dataset.filter||"all";
      this.state.search="";
      if(search)search.value="";
      this.updateUrl();
      this.setActiveCategory();
      this.loadHome();
      b.scrollIntoView({behavior:"smooth",block:"nearest",inline:"center"});
    });
  });

  if(search){
    search.addEventListener("input",()=>{
      this.state.search=search.value;
      this.renderHome();
    });
  }

  if(menu&&backdrop)menu.addEventListener("click",()=>backdrop.classList.add("open"));
  $("drawerClose")?.addEventListener("click",()=>backdrop?.classList.remove("open"));
  backdrop?.addEventListener("click",e=>{
    if(e.target===backdrop)backdrop.classList.remove("open");
  });
  document.querySelectorAll(".mobile-drawer a").forEach(a=>{
    a.addEventListener("click",()=>backdrop?.classList.remove("open"));
  });

  $("searchTrigger")?.addEventListener("click",()=>{
    if(!search)return;
    search.focus();
    search.scrollIntoView({behavior:"smooth",block:"center"});
  });

  $("accept")?.addEventListener("click",()=>{
    localStorage.setItem("ph_cookie_consent","accepted");
    $("cookie")?.classList.remove("show");
  });
  if(!localStorage.getItem("ph_cookie_consent"))$("cookie")?.classList.add("show");

  this.loadHome();
  setInterval(()=>{if(!document.hidden)this.loadHome()},60000);
};

PH.loadArticle=async function(){
  const id=new URLSearchParams(location.search).get("id"),page=this.$("articlePage");
  if(!id)return this.articleError("Story not found");
  try{
    let n;
    try{
      n=await this.fetchJSON("/api/news/"+encodeURIComponent(id),12000);
    }catch(e){
      const rows=this.rowsFrom(await this.fetchJSON("/news-data.json?ts="+Date.now(),12000));
      n=rows.find(x=>String(x.id)===String(id));
    }
    if(!n||n.error)throw Error();
    const has=this.validImage(n.image_url);
    document.title=(n.title||"Article")+" — PoliticsHub.in";
    page.innerHTML=
      '<a class="back" href="/">← Back to news</a>'+
      '<div class="article-kicker">'+this.esc(n.category||"News")+'</div>'+
      '<h1 class="article-title">'+this.esc(n.title||"Untitled story")+'</h1>'+
      '<p class="article-dek">'+this.esc(n.summary||n.bot_summary||n.article||"")+'</p>'+
      '<div class="article-meta">'+this.esc(this.fmt(n.published_at||n.published_at_site))+' · '+this.esc(n.source_name||"PoliticsHub")+'</div>'+
      (has?this.image(n,true).replace('<img ','<img class="article-hero" '):"")+
      '<div class="article-body">'+this.esc(n.article||n.bot_article||n.summary||n.bot_summary||"")+'</div>'+
      (n.source_name?'<div class="article-source">Source: '+(n.url?'<a href="'+this.esc(n.url)+'" target="_blank" rel="noopener noreferrer">'+this.esc(n.source_name)+'</a>':this.esc(n.source_name))+'</div>':"");
  }catch(e){this.articleError("Article unavailable","The requested story could not be loaded.")};
};

PH.articleError=function(title,msg="Please return to the newsroom and try another story."){
  this.$("articlePage").innerHTML='<a class="back" href="/">← Back to news</a><div class="error-state"><h1>'+this.esc(title)+'</h1><p>'+this.esc(msg)+'</p></div>';
};

PH.bindChrome=function(){
  const backdrop=document.getElementById("drawerBackdrop");
  const menu=document.getElementById("menu");
  const close=document.getElementById("drawerClose");
  if(menu&&backdrop&&!menu.dataset.bound){
    menu.dataset.bound="1";
    menu.addEventListener("click",()=>backdrop.classList.add("open"));
  }
  if(close&&backdrop&&!close.dataset.bound){
    close.dataset.bound="1";
    close.addEventListener("click",()=>backdrop.classList.remove("open"));
  }
  if(backdrop&&!backdrop.dataset.bound){
    backdrop.dataset.bound="1";
    backdrop.addEventListener("click",e=>{if(e.target===backdrop)backdrop.classList.remove("open")});
  }
  document.querySelectorAll(".mobile-drawer a").forEach(a=>{
    if(!a.dataset.bound){
      a.dataset.bound="1";
      a.addEventListener("click",()=>backdrop?.classList.remove("open"));
    }
  });
  const search=document.getElementById("search");
  const trigger=document.getElementById("searchTrigger");
  if(trigger&&search&&!trigger.dataset.bound){
    trigger.dataset.bound="1";
    trigger.addEventListener("click",()=>{
      search.focus();
      search.scrollIntoView({behavior:"smooth",block:"center"});
    });
  }
};
