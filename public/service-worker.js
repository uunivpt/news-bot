const CACHE="politicshub-shell-v18";
const MAX_ENTRIES=80;
const SHELL=["/","/offline.html","/saved.html","/manifest.webmanifest","/assets/site.css?v=phui22","/assets/site.js?v=phui30","/assets/editorial-home.js?v=phui30","/assets/editorial.css?v=phui19","/assets/polish.css?v=phui30","/assets/ui.js?v=phui30","/assets/reading-list.js?v=ph30","/assets/reader.js?v=ph30","/favicon.svg"];
async function remember(req,response){
 const cache=await caches.open(CACHE);await cache.put(req,response);
 const keys=await cache.keys();
 const removable=keys.filter(key=>!SHELL.includes(new URL(key.url).pathname+new URL(key.url).search));
 const excess=keys.length-MAX_ENTRIES;
 if(excess>0)await Promise.all(removable.slice(0,excess).map(key=>cache.delete(key)));
}
self.addEventListener("install",event=>{
 event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(SHELL)).then(()=>self.skipWaiting()));
});
self.addEventListener("activate",event=>{
 event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>key.startsWith("politicshub-shell-")&&key!==CACHE).map(key=>caches.delete(key)))).then(()=>self.clients.claim()));
});
self.addEventListener("fetch",event=>{
 const req=event.request,url=new URL(req.url);
 if(req.method!=="GET"||url.origin!==self.location.origin||url.pathname.startsWith("/api/")||url.pathname.startsWith("/admin")||url.pathname.startsWith("/newsroom-console")||url.pathname.startsWith("/newsletter/")||url.pathname==="/debug.html"||url.searchParams.has('token')||url.pathname==="/news-data.json"||url.pathname==="/hindi-news.json")return;
 event.respondWith(fetch(req).then(response=>{
  if(response.ok&&!response.redirected&&!/no-store|private/i.test(response.headers.get('Cache-Control')||'')&&(req.mode==="navigate"||url.pathname.startsWith("/assets/")||url.pathname==="/favicon.svg"||url.pathname==="/manifest.webmanifest")){
   event.waitUntil(remember(req,response.clone()).catch(()=>{}));
  }
  return response;
 }).catch(async()=>{
  const cached=await caches.match(req);
  if(cached)return cached;
  if(req.mode==="navigate")return await caches.match("/offline.html")||Response.error();
  return Response.error();
 }));
});
self.addEventListener("message",event=>{if(event.data==="SKIP_WAITING")self.skipWaiting()});
