(() => {
  const boot = () => {
    const $ = (id) => document.getElementById(id);
    const esc = (v) => String(v ?? "").replace(/[&<>"]/g, m => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;" }[m]));
    const imageOK = (v) => { const s=String(v||"").trim(); return !!s && !/placeholder|default[-_ ]?image|no[-_ ]?image|noimage|blank[-_ ]?image|black[-_ ]?image|dummy[-_ ]?image/i.test(s); };
    const fmt = (v) => { if(!v) return ""; const s=String(v); const d=new Date(s); return Number.isNaN(d.getTime()) ? s : d.toLocaleString("en-IN",{day:"2-digit",month:"short",year:"numeric",hour:"2-digit",minute:"2-digit",hour12:false}); };
    const rowsFrom = (d) => Array.isArray(d) ? d : (Array.isArray(d?.news) ? d.news : (Array.isArray(d?.items) ? d.items : []));
    const fetchJSON = async (url) => {
      const r = await fetch(url,{cache:"no-store",headers:{"Accept":"application/json"}});
      if(!r.ok) throw Error("HTTP "+r.status);
      return r.json();
    };
    const render = (rows) => {
      const q = ($("search")?.value || "").trim().toLowerCase();
      const category = new URLSearchParams(location.search).get("category") || "all";
      let view = category==="all" ? rows : rows.filter(n => String(n.category||"general").toLowerCase()===category.toLowerCase());
      if(q) view=view.filter(n => [n.title,n.summary,n.bot_summary,n.category,n.source_name].filter(Boolean).join(" ").toLowerCase().includes(q));
      const card = (n) => {
        const has=imageOK(n.image_url);
        return '<a class="story-card '+(has?"":"no-image")+'" href="/article.html?id='+encodeURIComponent(n.id)+'"><div><div class="story-kicker">'+esc(n.category||"News")+'</div><h3 class="story-title">'+esc(n.title||"Untitled story")+'</h3><p class="story-summary">'+esc(n.summary||n.bot_summary||n.article||"")+'</p><div class="story-meta">'+esc(fmt(n.published_at||n.published_at_site))+' · '+esc(n.source_name||"PoliticsHub")+'</div></div>'+(has?'<img class="story-image" loading="lazy" src="'+esc(n.image_url)+'" alt="" onerror="this.remove()">':"")+'</a>';
      };
      $("news").innerHTML=view.length?view.map(card).join(""):'<div class="empty">No published stories match this view.</div>';
      $("count").textContent=view.length+" stories";
      const n=view[0];
      if(n){
        const has=imageOK(n.image_url);
        $("heroMedia").className="lead-media"+(has?"":" empty");
        $("heroMedia").innerHTML=has?'<img fetchpriority="high" src="'+esc(n.image_url)+'" alt="">':"";
        $("heroCopy").innerHTML='<div class="kicker">'+esc(n.category||"Latest")+' · JUST IN</div><h1>'+esc(n.title||"Untitled story")+'</h1><p class="lead-dek">'+esc(n.summary||n.bot_summary||n.article||"")+'</p><div class="meta">'+esc(fmt(n.published_at||n.published_at_site))+' · '+esc(n.source_name||"PoliticsHub")+'</div><a class="read" href="/article.html?id='+encodeURIComponent(n.id)+'">Read full story</a>';
        $("ticker").textContent=n.title||"Latest update";
      } else {
        $("heroMedia").className="lead-media empty"; $("heroMedia").innerHTML="";
        $("heroCopy").innerHTML='<div class="kicker">PoliticsHub</div><h1>No published news</h1><p class="lead-dek">There are currently no published stories in this section.</p>';
        $("ticker").textContent="No published updates";
      }
      document.querySelectorAll(".nav-link").forEach(a=>a.classList.toggle("active",a.dataset.cat===category));
    };
    const load = async () => {
      $("news").innerHTML='<div class="skeleton"></div><div class="skeleton"></div>';
      try {
        let rows=[];
        try { rows=rowsFrom(await fetchJSON("/news-data.json")); } catch(e) {}
        if(!rows.length) rows=rowsFrom(await fetchJSON("/api/news?category=all&limit=100"));
        render(rows);
      } catch(e) {
        $("news").innerHTML='<div class="empty">News is temporarily unavailable. Please refresh shortly.</div>';
      }
    };
    document.querySelectorAll("[data-filter]").forEach(b=>b.addEventListener("click",()=>{ const u=new URL(location.href); u.searchParams.set("category",b.dataset.filter); history.replaceState(null,"",u.pathname+u.search); load(); }));
    $("search")?.addEventListener("input",load);
    load();
    setInterval(()=>{if(!document.hidden)load()},60000);
  };
  if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",boot,{once:true}); else boot();
})();