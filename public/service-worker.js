const CACHE="politicshub-shell-v9";
const SHELL=["/","/manifest.webmanifest","/assets/site.css?v=phui17","/assets/site.js?v=phui17","/assets/editorial-home.js?v=phui17","/favicon.svg"];
self.addEventListener("install",event=>{
 event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(SHELL)).then(()=>self.skipWaiting()));
});
self.addEventListener("activate",event=>{
 event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>key.startsWith("politicshub-shell-")&&key!==CACHE).map(key=>caches.delete(key)))).then(()=>self.clients.claim()));
});
self.addEventListener("fetch",event=>{
 const req=event.request,url=new URL(req.url);
 if(req.method!=="GET"||url.origin!==self.location.origin||url.pathname.startsWith("/api/")||url.pathname==="/news-data.json")return;
 event.respondWith(fetch(req).then(response=>{
  if(response.ok&&(req.mode==="navigate"||url.pathname.startsWith("/assets/")||url.pathname==="/favicon.svg"||url.pathname==="/manifest.webmanifest")){
   const copy=response.clone();event.waitUntil(caches.open(CACHE).then(cache=>cache.put(req,copy)));
  }
  return response;
 }).catch(async()=>{
  const cached=await caches.match(req);
  if(cached)return cached;
  if(req.mode==="navigate")return await caches.match("/")||Response.error();
  return Response.error();
 }));
});
self.addEventListener("message",event=>{if(event.data==="SKIP_WAITING")self.skipWaiting()});
