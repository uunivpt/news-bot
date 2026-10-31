(() => {
 const cards=[...document.querySelectorAll('[data-source-type]')];
 const filters=[...document.querySelectorAll('[data-source-kind]')];
 const search=document.getElementById('sourceSearch');
 const reset=document.getElementById('sourceReset');
 const tools=document.getElementById('sourceSearchTools');
 const normalize=value=>String(value||'').normalize('NFKC').toLocaleLowerCase('en-IN');
 const searchable=new Map(cards.map(card=>[card,normalize(card.textContent)]));
 let kind='all';
 function update(){
  const words=normalize(search?.value).trim().split(/\s+/).filter(Boolean);
  filters.forEach(filter=>filter.setAttribute('aria-pressed',String(filter.dataset.sourceKind===kind)));
  cards.forEach(card=>{card.hidden=(kind!=='all'&&card.dataset.sourceType!==kind)||!words.every(word=>searchable.get(card).includes(word))});
  const count=cards.filter(card=>!card.hidden).length;
  document.getElementById('sourceCount').textContent=count+' '+(kind==='all'?'references':kind==='official'?'official references':'news publishers')+(words.length?' matching your search':'');
  const empty=document.getElementById('sourceEmpty');if(empty)empty.hidden=count!==0;
 }
 filters.forEach(button=>button.addEventListener('click',()=>{kind=button.dataset.sourceKind;update()}));
 search?.addEventListener('input',update);
 reset?.addEventListener('click',()=>{kind='all';search.value='';update();search.focus()});
 if(tools)tools.hidden=false;
 update();
})();
