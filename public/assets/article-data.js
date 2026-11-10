/* Progressive enhancement of server-rendered, reviewed article datasets. */
const styled = () => {
  if (document.querySelector('link[data-article-data-style]')) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet'; link.href = '/assets/article-data.css?v=3';
  link.dataset.articleDataStyle = ''; document.head.append(link);
};

function enhance(root) {
  for (const chart of root.querySelectorAll('.article-data-chart')) {
    if (chart.dataset.enhanced) continue;
    chart.dataset.enhanced = 'true';
    const tooltip = chart.querySelector('.article-data-tooltip');
    let active = null, mode = 'keyboard', dismissed = false;
    const hide = () => { tooltip.hidden = true; };
    const show = bar => {
      const title = document.createElement('strong'), value = document.createElement('span');
      title.textContent = bar.dataset.label; value.textContent = bar.dataset.value;
      tooltip.replaceChildren(title, value); tooltip.hidden = false;
      const box = chart.getBoundingClientRect(), rect = bar.getBoundingClientRect();
      const left = Math.max(8, Math.min(rect.left - box.left + rect.width / 2 - tooltip.offsetWidth / 2,
        chart.clientWidth - tooltip.offsetWidth - 8));
      tooltip.style.left = left + chart.scrollLeft + 'px';
      tooltip.style.top = Math.max(8, rect.top - box.top - tooltip.offsetHeight - 10) + 'px';
    };
    for (const bar of chart.querySelectorAll('.data-bar, .story-point, .story-slice')) {
      // Scrolling a focused bar into view can cause pointerenter without a
      // mouse move. That must not substitute a neighbouring value for focus.
      bar.addEventListener('pointerenter', () => { if (!active || mode === 'pointer') show(bar); });
      bar.addEventListener('pointermove', event => {
        if (event.movementX || event.movementY) { mode = 'pointer'; dismissed = false; show(bar); }
      });
      bar.addEventListener('focus', () => { active = bar; mode = 'keyboard'; dismissed = false; show(bar); });
      bar.addEventListener('pointerdown', () => { bar.focus(); mode = 'pointer'; dismissed = false; show(bar); });
      bar.addEventListener('blur', () => { active = null; hide(); });
      bar.addEventListener('keydown', event => { if (event.key === 'Escape') { dismissed = true; hide(); } });
    }
    chart.addEventListener('pointerleave', () => {
      if (active && !dismissed) { mode = 'keyboard'; show(active); }
      else hide();
    });
    chart.addEventListener('scroll', () => { if (active && mode === 'keyboard' && !dismissed) show(active); });
  }
}

// SPA article routes request the same escaped HTML renderer as canonical pages.
// Charts never parse article prose, feed markup, or arbitrary source numbers.
export async function mount(root, identity) {
  if (!root?.isConnected || !/^[0-9]{1,19}$/.test(String(identity))) return;
  try {
    const response = await fetch('/api/article-visuals/' + encodeURIComponent(identity),
      {signal: AbortSignal.timeout(8000), headers: {Accept: 'application/json'}});
    if (!response.ok || !root.isConnected) return;
    const result = await response.json();
    if (!root.isConnected || typeof result.html !== 'string' || !result.html || result.html.length > 100000) return;
    styled();
    // Only this same-origin endpoint's bounded, escaped renderer supplies HTML.
    const template = document.createElement('template'); template.innerHTML = result.html;
    root.querySelector('.body')?.before(template.content);
    enhance(root);
  } catch (_) { /* A chart outage must not interrupt the article text. */ }
}

if (document.querySelector('.article-data')) enhance(document);

// Only the reviewed, same-origin catalog supplies the homepage indicator cards.
export async function mountHighlights(root) {
  if (!root?.isConnected) return;
  styled();
  try {
    const response = await fetch('/api/data-desk/cards', {signal: AbortSignal.timeout(8000)});
    if (!response.ok || !root.isConnected) return;
    const result = await response.json();
    if (!root.isConnected || typeof result.html !== 'string' || result.html.length > 100000) return;
    const target = root.querySelector('[data-data-cards]');
    if (target) { target.innerHTML = result.html; enhance(target); }
  } catch (_) { /* The Data Desk link remains usable if the summary is unavailable. */ }
}
