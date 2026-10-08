(() => {
 const box=document.getElementById('checks'),button=document.getElementById('run');
 async function check(){
  button.disabled=true;box.replaceChildren();
  const checks=[['Live newsroom','/api/health'],['Published stories','/api/news?limit=1'],['Saved fallback','/news-data.json']];
  await Promise.all(checks.map(async([name,url])=>{
   const line=document.createElement('p');line.textContent=name+': checking…';box.append(line);
   try{
    const response=await fetch(url,{cache:'no-store',signal:AbortSignal.timeout(12000)});
    const data=await response.json();
    if(url==='/api/health'){
     line.textContent=name+': '+(data.ok?'available':'temporarily unavailable')+(data.latest_published_at?' · Newest story '+new Date(data.latest_published_at).toLocaleString('en-IN'):'');
    }else if(response.ok){
     line.textContent=name+': '+(response.headers.get('X-News-Mode')==='snapshot'?'serving saved stories':Array.isArray(data)&&!data.length?'no stories yet':'available');
    }else{throw Error('unavailable')}
   }catch(error){line.textContent=name+': could not connect. Try again shortly.'}
  }));
  button.disabled=false;
 }
 button.addEventListener('click',check);check();
})();
