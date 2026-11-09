/* Progressive enhancement of server-rendered, reviewed article datasets. */
const styled = () => {
  if (document.querySelector('link[data-article-data-style]')) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet'; link.href = '/assets/article-data.css?v=1';
  link.dataset.articleDataStyle = ''; document.head.append(link);
};

function enhance(root) {
  for (const chart of root.querySelectorAll('.article-data-chart')) {
    if (chart.dataset.enhanced) continue;
    chart.dataset.enhanced = 'true';
    const tooltip = chart.querySelector('.article-data-tooltip');
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
    for (const bar of chart.querySelectorAll('.data-bar')) {
      bar.addEventListener('pointerenter', () => show(bar));
      bar.addEventListener('focus', () => show(bar));
      bar.addEventListener('pointerdown', () => { bar.focus(); show(bar); });
      bar.addEventListener('blur', hide);
      bar.addEventListener('keydown', event => { if (event.key === 'Escape') hide(); });
    }
    chart.addEventListener('pointerleave', () => {
      if (!chart.contains(document.activeElement)) hide();
    });
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
