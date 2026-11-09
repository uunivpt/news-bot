/* Lightweight story-feed interactions: density, search shortcut and motion. */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.PHNewsroomUI = api;
})(typeof window === 'undefined' ? globalThis : window, function () {
  'use strict';
  const state = { density: 'comfortable' };
  let observer, currentHome, frame = 0;

  function icon(name) {
    const paths = {
      search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>'
    };
    return '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+(paths[name] || '')+'</svg>';
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
    if (frame) { cancelAnimationFrame(frame); frame = 0; }
    currentHome = home;
    if (!home) return;
    applyDensity(home);
    home.addEventListener('click', event => {
      const density = event.target.closest('[data-news-density]');
      if (density) { state.density = density.dataset.newsDensity; applyDensity(home); }
      if (event.target.closest('[data-news-search]')) document.getElementById('sbtn')?.click();
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
    observe(home);
  }

  if (typeof window !== 'undefined') {
    window.matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change', () => observe(currentHome));
    document.addEventListener('keydown', event => {
      if (!(event.ctrlKey || event.metaKey) || event.altKey || event.key.toLowerCase() !== 'k' || event.repeat) return;
      if (!currentHome?.isConnected || /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName) || document.activeElement?.isContentEditable || document.querySelector('#sp.open')) return;
      event.preventDefault(); document.getElementById('sbtn')?.click();
    });
  }
  return { icon, bind, observe };
});
