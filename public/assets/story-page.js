/* Approximate article page views, without cookies or a reader identifier. */
(() => {
 const match=location.pathname.match(/^\/(?:india|world|politics|hindi)\/(\d+)-/);
 if(!match)return;
 let sent=false;
 const track=()=>{
  if(sent||document.hidden)return;sent=true;
  try{navigator.sendBeacon('/api/news/'+match[1]+'/view',new Blob(['{}'],{type:'application/json'}))}catch(_){}
 };
 if(document.hidden)document.addEventListener('visibilitychange',track);else track();
})();
