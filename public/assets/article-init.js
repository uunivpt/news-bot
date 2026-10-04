(() => {
  const boot = async () => {
    const page = document.getElementById("articlePage");
    const id = new URLSearchParams(location.search).get("id");
    const esc = (v) => String(v ?? "").replace(/[&<>"]/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[m]));
    const imageOK = (v) => { const s=String(v||"").trim(); return !!s && !/placeholder|default[-_ ]?image|no[-_ ]?image|noimage|blank[-_ ]?image|black[-_ ]?image|dummy[-_ ]?image/i.test(s); };
    const fmt = (v) => { if(!v)return ""; const d=new Date(String(v)); return Number.isNaN(d.getTime())?String(v):d.toLocaleString("en-IN",{day:"2-digit",month:"short",year:"numeric",hour:"2-digit",minute:"2-digit",hour12:false}); };
    const rowsFrom = (d) => Array.isArray(d)?d:(Array.isArray(d?.news)?d.news:(Array.isArray(d?.items)?d.items:[]));
    const getJSON = async (url) => { const r=await fetch(url,{cache:"no-store",headers:{"Accept":"application/json"}}); if(!r.ok)throw Error("HTTP "+r.status); return r.json(); };
    const showError = (title,msg) => { page.innerHTML='<a class="back" href="/">← Back to news</a><div class="error-state"><h1>'+esc(title)+'</h1><p>'+esc(msg)+'</p></div>'; };
    if(!id){showError("Story not found","No article id was provided.");return;}
    try {
      let n=null;
      try { n=await getJSON("/api/news/"+encodeURIComponent(id)); } catch(e) {}
      if(!n || n.error){
        try { n=rowsFrom(await getJSON("/news-data.json")).find(x=>String(x.id)===String(id)) || null; } catch(e) {}
      }
      if(!n){showError("Article unavailable","This story could not be loaded right now.");return;}
      const title=n.title||"Untitled story";
      const summary=n.summary||n.bot_summary||n.article||"";
      const article=n.article||n.bot_article||summary||"";
      const has=imageOK(n.image_url);
      document.title=title+" — PoliticsHub.in";
      page.innerHTML='<a class="back" href="/">← Back to news</a><div class="article-kicker">'+esc(n.category||"News")+'</div><h1 class="article-title">'+esc(title)+'</h1><p class="article-dek">'+esc(summary)+'</p><div class="article-meta">'+esc(fmt(n.published_at||n.published_at_site))+' · '+esc(n.source_name||"PoliticsHub")+'</div>'+(has?'<img class="article-hero" src="'+esc(n.image_url)+'" alt="" onerror="this.remove()">':"")+'<div class="article-body">'+esc(article)+'</div>'+(n.source_name?'<div class="article-source">Source: '+(n.url?'<a href="'+esc(n.url)+'" target="_blank" rel="noopener noreferrer">'+esc(n.source_name)+'</a>':esc(n.source_name))+'</div>':"");
    } catch(e) { showError("Article unavailable","The article loader encountered an error. Please try again."); }
  };
  if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",boot,{once:true}); else boot();
})();