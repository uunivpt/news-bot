// Standalone article pages do not contain the home application's controls.
(() => {
  const menu=document.getElementById('bg');
  if(menu)menu.addEventListener('click',()=>{location.href='/'});
  document.addEventListener('error',event=>{
    if(event.target instanceof HTMLImageElement){
      const hero=event.target.closest('.ahero');
      if(hero)hero.remove();else event.target.remove();
    }
  },true);
})();
