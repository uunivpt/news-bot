/* Lightweight chrome for static pages, server-rendered stories and the home app. */
(() => {
  // Site-wide Google tag. Count the Google Ads "Page view" conversion once
  // on the campaign's main landing page, never on admin or secondary pages.
  const path = window.location.pathname;
  if (!path.startsWith('/admin') && !path.startsWith('/api/') &&
      !path.startsWith('/newsroom-console') && !path.startsWith('/debug')) {
    window.dataLayer = window.dataLayer || [];
    window.gtag = window.gtag || function() { window.dataLayer.push(arguments); };
    window.gtag('js', new Date());
    window.gtag('config', 'G-2HVZQST08G');
    window.gtag('config', 'AW-18495731647');
    if (!document.querySelector('script[src*="googletagmanager.com/gtag/js"]')) {
      const googleTag = document.createElement('script');
      googleTag.async = true;
      googleTag.src = 'https://www.googletagmanager.com/gtag/js?id=G-2HVZQST08G';
      document.head.appendChild(googleTag);
    }
    if (path === '/' || path === '/index.html') {
      window.gtag('event', 'conversion', {
        'send_to': 'AW-18495731647/4NrBCOKXz6UdEL_vufNE'
      });
    }
  }
  const desks = [['','Home'],['india','India'],['politics','Politics'],['world','World'],['business','Business'],['technology','Technology'],['sports','Sports'],['entertainment','Entertainment'],['science','Science'],['health','Health'],['hindi','Hindi']];
  try {
    if (localStorage.getItem('ph-consent-v1') === 'preferences') {
      document.documentElement.dataset.theme = localStorage.getItem('ph-theme') === 'dark' ? 'dark' : 'light';
    }
  } catch (_) {}
  document.querySelectorAll('time[datetime]').forEach(time => {
    const date = new Date(time.dateTime);
    if (!Number.isNaN(date.getTime())) time.textContent = date.toLocaleString('en-IN', {day:'numeric',month:'short',year:'numeric',hour:'numeric',minute:'2-digit'});
  });
  const search = document.querySelector('#sp');
  if (search) { search.setAttribute('role','dialog'); search.setAttribute('aria-modal','true'); search.setAttribute('aria-label','Search stories'); }
  const main = document.querySelector('main');
  if (main) {
    if (!main.id) main.id = 'main-content';
    main.tabIndex = -1;
    const skip = document.createElement('a');
    skip.className = 'skip-link'; skip.href = '#' + main.id; skip.textContent = 'Skip to content';
    skip.addEventListener('click', event => { event.preventDefault(); main.focus(); main.scrollIntoView(); });
    document.body.prepend(skip);
  }
  const header = document.querySelector('#hd');
  if (header && !document.querySelector('#dr')) {
    const top = header.querySelector('.top');
    const logo = header.querySelector('.logo');
    if (logo) { logo.href = '/'; logo.setAttribute('aria-label', 'PoliticsHub.in — home'); }
    let menu = document.querySelector('#bg');
    if (!menu && top) { menu = document.createElement('button'); menu.className = 'ib burger'; menu.id = 'bg'; menu.textContent = '☰'; top.prepend(menu); }
    const dialog = document.createElement('dialog'); dialog.className = 'ui-menu'; dialog.id = 'section-menu'; dialog.setAttribute('aria-label','News sections');
    dialog.innerHTML = '<button type="button" aria-label="Close menu">×</button><strong>Explore PoliticsHub</strong><nav aria-label="Sections">' + desks.map(([key,label]) => '<a href="/'+(key ? key+'/' : '')+'">'+label+'</a>').join('') + '<a href="/archive/">Archive</a><a href="/newsletter.html">Newsletter</a></nav>';
    document.body.append(dialog);
    if (menu) {
      menu.setAttribute('aria-label','Open menu'); menu.setAttribute('aria-controls',dialog.id); menu.setAttribute('aria-expanded','false');
      menu.onclick = () => { dialog.showModal(); menu.setAttribute('aria-expanded','true'); };
      dialog.addEventListener('close', () => { menu.setAttribute('aria-expanded','false'); menu.focus(); });
    }
    dialog.querySelector('button').onclick = () => dialog.close();
    dialog.addEventListener('click', event => { if (event.target === dialog) { const r=dialog.getBoundingClientRect(); if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close(); } });
    const nav = document.createElement('nav'); nav.className = 'ui-section-links'; nav.setAttribute('aria-label','News sections');
    nav.innerHTML = desks.map(([key,label]) => '<a href="/'+(key ? key+'/' : '')+'"'+(key && location.pathname.startsWith('/'+key+'/') ? ' aria-current="page"' : '')+'>'+label+'</a>').join('');
    header.append(nav);
  }
  document.querySelectorAll('form p.msg').forEach(el => {el.setAttribute('role','status'); el.setAttribute('aria-live','polite');});
  document.addEventListener('error', event => {
    if (!(event.target instanceof HTMLImageElement)) return;
    const wrapper = event.target.closest('.ahero,.ph14-media,.ph14-thumb');
    if (wrapper) wrapper.remove();
  },true);
})();
