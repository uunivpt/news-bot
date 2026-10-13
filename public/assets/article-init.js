/* Legacy links use the maintained article renderer, including snapshot fallback. */
(() => {
  const id = new URLSearchParams(location.search).get('id');
  if (id && /^\d+$/.test(id)) location.replace('/#/article/' + encodeURIComponent(id));
  else {
    const page = document.getElementById('articlePage');
    if (page) page.innerHTML = '<article class="art"><div class="ah"><h1>Story not found</h1><p class="dek">This link does not include a valid story ID.</p><a class="btn" href="/">Browse latest news</a></div></article>';
  }
})();
