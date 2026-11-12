/* Local-only reading list. No account, tracking request or third-party service. */
(function(root,factory){
 const api=factory();
 if(typeof module==='object'&&module.exports)module.exports=api;
 else root.PHReadingList=api;
})(typeof window==='undefined'?globalThis:window,function(){
 'use strict';
 const KEY='ph-reading-list-v1',MAX_ITEMS=100;
 function clean(item,origin){
  if(!item||typeof item.title!=='string'||!item.title.trim())return null;
  try{
   const url=new URL(item.url,origin);
   if(url.origin!==origin||url.username||url.password)return null;
   const article=/^\/(?:india|politics|world|hindi|maharashtra)\/\d+(?:-[^/]+)?\/?$/.test(url.pathname);
   const legacy=url.pathname==='/'&&/^#\/article\/\d+$/.test(url.hash);
   const special=['/elon-musk-ambani-starlink.html','/nana-patekar-tribute.html'].includes(url.pathname);
   if(!article&&!legacy&&!special)return null;
   return {url:url.pathname+(legacy?url.hash:''),title:item.title.trim().slice(0,300),
    source:String(item.source||'').slice(0,120),savedAt:Number.isFinite(item.savedAt)?item.savedAt:Date.now()};
  }catch(_){return null}
 }
 function create(storage,origin,allowed){
  function read(){
   if(!allowed())return [];
   try{const data=JSON.parse(storage.getItem(KEY)||'[]');if(!Array.isArray(data))return [];
    const seen=new Set();return data.slice(0,MAX_ITEMS).map(x=>clean(x,origin)).filter(x=>{if(!x||seen.has(x.url))return false;seen.add(x.url);return true});
   }catch(_){return []}
  }
  function write(items){if(!allowed())return false;try{storage.setItem(KEY,JSON.stringify(items.slice(0,MAX_ITEMS)));return true}catch(_){return false}}
  return {read,
   add(item){const safe=clean(item,origin);return !!safe&&write([safe,...read().filter(x=>x.url!==safe.url)])},
   remove(url){return write(read().filter(x=>x.url!==url))},
   clear(){try{storage.removeItem(KEY);return true}catch(_){return false}}
  };
 }
 function select(items,query='',order='recent'){
  const normalize=value=>String(value||'').normalize('NFKC').toLocaleLowerCase('en-IN');
  const words=normalize(query).trim().split(/\s+/).filter(Boolean);
  const rows=items.filter(row=>words.every(word=>normalize(row.title).includes(word)));
  if(order==='title')rows.sort((a,b)=>a.title.localeCompare(b.title,'en-IN',{sensitivity:'base',numeric:true}));
  else rows.sort((a,b)=>order==='oldest'?a.savedAt-b.savedAt:b.savedAt-a.savedAt);
  return rows;
 }
 function bookmarks(items,origin){
  const esc=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const seen=new Set(),links=[];
  for(const item of (Array.isArray(items)?items:[]).slice(0,MAX_ITEMS)){
   const safe=clean(item,origin);if(!safe||seen.has(safe.url))continue;
   seen.add(safe.url);
   // Backups point to the public site even when tested on a preview. Dates
   // are deliberately omitted: a saved time is not an article publication date.
   links.push('<DT><A HREF="'+esc(new URL(safe.url,'https://www.politicshub.in').href)+'">'+esc(safe.title)+'</A>');
  }
  if(!links.length)return {html:'',count:0};
  return {count:links.length,html:['<!DOCTYPE NETSCAPE-Bookmark-file-1>',
   '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">',
   '<META HTTP-EQUIV="Content-Security-Policy" CONTENT="default-src \'none\'">',
   '<TITLE>PoliticsHub saved stories</TITLE>','<H1>PoliticsHub saved stories</H1>',
   '<DL><p>','<DT><H3>PoliticsHub saved stories</H3>','<DL><p>',...links,'</DL><p>','</DL><p>'].join('\n')};
 }
 return {KEY,MAX_ITEMS,clean,create,select,bookmarks};
});
