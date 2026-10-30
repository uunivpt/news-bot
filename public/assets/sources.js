(() => {
 const cards=[...document.querySelectorAll('[data-source-type]')];
 const filters=[...document.querySelectorAll('[data-source-kind]')];
 filters.forEach(button=>button.addEventListener('click',()=>{
  const kind=button.dataset.sourceKind;
  filters.forEach(filter=>filter.setAttribute('aria-pressed',String(filter===button)));
  cards.forEach(card=>{card.hidden=kind!=='all'&&card.dataset.sourceType!==kind});
  document.getElementById('sourceCount').textContent=cards.filter(card=>!card.hidden).length+' '+(kind==='all'?'references':kind==='official'?'official references':'news publishers');
 }));
})();
