/* Watermelon UI Continuous Tabs and Stats 4 adapted to native browser APIs.
 * Source revision and MIT notice: docs/WATERMELON_UI_LICENSE.md.
 * Feed counts describe loaded reports, never audience analytics. */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.PHNewsroomUI = api;
})(typeof window === 'undefined' ? globalThis : window, function () {
  'use strict';
  const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const state = { tab: 'overview', density: 'comfortable' };
  let observer, resizeObserver, currentHome, frame = 0;

  function summarize(items, categories, matches) {
    const publishers = new Set(items.map(item => String(item.source || '').trim().toLowerCase()).filter(Boolean));
    const coverage = categories.filter(category => category[0] !== 'all').map(category => ({
      key: category[0], label: category[1], count: items.filter(item => matches(item, category[0])).length
    }));
    return { reports: items.length, publishers: publishers.size, desks: coverage.filter(desk => desk.count > 0).length, coverage };
  }

  function dashboard(items, categories, matches, href) {
    const data = summarize(items, categories, matches);
    const stats = [
      ['Reports', data.reports, 'In this loaded feed'],
      ['Named sources', data.publishers, 'Publishers attributed in the feed'],
      ['News desks', data.desks, 'With reports to explore']
    ].map(stat => '<div class="ph-ui-stat ph-ui-card"><small>'+stat[0]+'</small><strong>'+stat[1].toLocaleString('en-IN')+'</strong><span>'+stat[2]+'</span></div>').join('');
    const desks = data.coverage.map(desk => '<a class="ph-ui-card" href="'+escape(href(desk.key))+'"><strong>'+escape(desk.label)+'</strong><span>'+desk.count+' '+(desk.count === 1 ? 'report' : 'reports')+'</span><div class="ph-ui-meter" aria-hidden="true"><i style="--coverage:'+Math.round(data.reports ? desk.count/data.reports*100 : 0)+'%"></i></div></a>').join('');
    return '<section class="ph-ui-dashboard ph-ui-reveal" aria-labelledby="ph-ui-dashboard-title">'+
      '<div class="ph-ui-dashboard-head"><div><span class="ph-ui-eyebrow">THE READING ROOM</span><h2 id="ph-ui-dashboard-title">A little context. A clearer picture.</h2><p>Your starting point for exploring the news.</p></div>'+
      '<div class="ph-ui-tabs" role="tablist" aria-label="Feed dashboard"><span class="ph-ui-tab-indicator" aria-hidden="true"></span>'+
      '<button class="ph-ui-tab" id="ph-ui-overview-tab" type="button" role="tab" aria-selected="true" aria-controls="ph-ui-overview">Overview</button>'+
      '<button class="ph-ui-tab" id="ph-ui-desks-tab" type="button" role="tab" aria-selected="false" tabindex="-1" aria-controls="ph-ui-desks">By news desk</button></div></div>'+
      '<div class="ph-ui-panel" id="ph-ui-overview" role="tabpanel" aria-labelledby="ph-ui-overview-tab"><div class="ph-ui-stats">'+stats+'</div><div class="ph-ui-quicklinks">'+
      '<a class="ph-ui-card" href="/briefing/"><span class="ph-ui-icon" aria-hidden="true">'+icon('brief')+'</span><div><strong>The quick briefing</strong><small>Catch up, one story at a time</small></div><b aria-hidden="true">↗</b></a>'+
      '<a class="ph-ui-card" href="/topics/"><span class="ph-ui-icon" aria-hidden="true">'+icon('topics')+'</span><div><strong>Follow the bigger picture</strong><small>Timelines, topics and context</small></div><b aria-hidden="true">↗</b></a>'+
      '<a class="ph-ui-card" href="/saved.html"><span class="ph-ui-icon" aria-hidden="true">'+icon('saved')+'</span><div><strong>Your reading list</strong><small>Return to stories you saved</small></div><b aria-hidden="true">↗</b></a></div></div>'+
      '<div class="ph-ui-panel" id="ph-ui-desks" role="tabpanel" aria-labelledby="ph-ui-desks-tab" hidden><div class="ph-ui-coverage">'+desks+'</div></div>'+
      '<p class="ph-ui-note">Counts describe this loaded feed, not the complete archive. A report can appear in more than one desk. <a href="/library/">Explore the full library →</a></p></section>';
  }

  function icon(name) {
    const paths = {
      brief: '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6M9 12h6M9 16h3"/>',
      topics: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><path d="M14 15h7M14 20h5"/>',
      saved: '<path d="M6 4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v17l-6-4-6 4Z"/>',
      search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>'
    };
    return '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+(paths[name] || paths.brief)+'</svg>';
  }

  function moveIndicator() {
    if (!currentHome?.isConnected) return;
    const active = currentHome.querySelector('.ph-ui-tab[aria-selected="true"]');
    const indicator = currentHome.querySelector('.ph-ui-tab-indicator');
    if (!active || !indicator) return;
    indicator.style.left = active.offsetLeft+'px';
    indicator.style.width = active.offsetWidth+'px';
  }

  function selectTab(home, tab, focus) {
    state.tab = tab.id === 'ph-ui-desks-tab' ? 'desks' : 'overview';
    home.querySelectorAll('.ph-ui-tab').forEach(button => {
      const selected = button === tab;
      button.setAttribute('aria-selected', String(selected));
      button.tabIndex = selected ? 0 : -1;
      home.querySelector('#'+button.getAttribute('aria-controls')).hidden = !selected;
    });
    if (focus) tab.focus();
    moveIndicator();
  }

  function applyDensity(home) {
    const feed = home.querySelector('.ph14-feed');
    if (feed) feed.dataset.density = state.density;
    home.querySelectorAll('[data-news-density]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.newsDensity === state.density)));
  }

  function observe(home) {
    if (!home?.isConnected) return;
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduce || !('IntersectionObserver' in window)) {
      observer?.disconnect();
      home.classList.remove('ph-ui-motion-ready');
      return;
    }
    if (!observer) observer = new IntersectionObserver(entries => entries.forEach(entry => {
      if (entry.isIntersecting) { entry.target.classList.add('is-visible'); observer.unobserve(entry.target); }
    }), { rootMargin: '0px 0px 40px 0px', threshold: 0.01 });
    home.classList.add('ph-ui-motion-ready');
    home.querySelectorAll('.ph-ui-reveal:not(.is-visible)').forEach(element => {
      // Keyboard navigation must never land on an invisible link.
      if (element.getBoundingClientRect().top < window.innerHeight) element.classList.add('is-visible');
      else observer.observe(element);
    });
  }

  function bind(home) {
    observer?.disconnect(); observer = null;
    resizeObserver?.disconnect();
    if (frame) { cancelAnimationFrame(frame); frame = 0; }
    currentHome = home;
    if (!home) return;
    const selected = home.querySelector('#ph-ui-'+state.tab+'-tab');
    if (selected) selectTab(home, selected, false);
    applyDensity(home);
    home.addEventListener('click', event => {
      const tab = event.target.closest('.ph-ui-tab');
      if (tab) selectTab(home, tab, false);
      const density = event.target.closest('[data-news-density]');
      if (density) { state.density = density.dataset.newsDensity; applyDensity(home); }
      if (event.target.closest('[data-news-search]')) document.getElementById('sbtn')?.click();
    });
    home.addEventListener('keydown', event => {
      const tab = event.target.closest('.ph-ui-tab');
      if (!tab || !['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
      event.preventDefault();
      const tabs = Array.from(home.querySelectorAll('.ph-ui-tab'));
      const index = tabs.indexOf(tab);
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length-1 : (index+(event.key === 'ArrowRight' ? 1 : tabs.length-1))%tabs.length;
      selectTab(home, tabs[next], true);
    });
    home.addEventListener('focusin', event => event.target.closest('.ph-ui-reveal')?.classList.add('is-visible'));
    home.addEventListener('pointermove', event => {
      if (!window.matchMedia('(hover: hover) and (pointer: fine) and (prefers-reduced-motion: no-preference)').matches) return;
      const card = event.target.closest('.ph-ui-card');
      if (!card || frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        if (!card.isConnected) return;
        const rect = card.getBoundingClientRect();
        card.style.setProperty('--spot-x', (event.clientX-rect.left)+'px');
        card.style.setProperty('--spot-y', (event.clientY-rect.top)+'px');
      });
    }, { passive: true });
    if ('ResizeObserver' in window) {
      resizeObserver = new ResizeObserver(moveIndicator);
      const tabs = home.querySelector('.ph-ui-tabs');
      if (tabs) resizeObserver.observe(tabs);
    }
    document.fonts?.ready.then(moveIndicator);
    observe(home);
  }

  if (typeof window !== 'undefined') {
    window.addEventListener('resize', moveIndicator, { passive: true });
    window.matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change', () => observe(currentHome));
    document.addEventListener('keydown', event => {
      if (!(event.ctrlKey || event.metaKey) || event.altKey || event.key.toLowerCase() !== 'k' || event.repeat) return;
      if (!currentHome?.isConnected || /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName) || document.activeElement?.isContentEditable || document.querySelector('#sp.open')) return;
      event.preventDefault(); document.getElementById('sbtn')?.click();
    });
  }
  return { summarize, dashboard, icon, bind, observe };
});
