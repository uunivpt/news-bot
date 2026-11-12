/* Progressive enhancement of server-rendered, reviewed article datasets. */
const styled = () => {
  if (document.querySelector('link[data-article-data-style]')) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet'; link.href = '/assets/article-data.css?v=4';
  link.dataset.articleDataStyle = ''; document.head.append(link);
};

function enhance(root) {
  for (const chart of root.querySelectorAll('.article-data-chart')) {
    if (chart.dataset.enhanced) continue;
    chart.dataset.enhanced = 'true';
    addChartDownload(chart);
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

// Export only static chart geometry and text. The SVG has its own colours,
// labels and provenance, with no page CSS, scripts, images or remote resources.
function chartDocument(chart) {
  const section = chart.closest('.article-data'), original = chart.querySelector('svg');
  const box = original.viewBox.baseVal, ns = 'http://www.w3.org/2000/svg';
  if (!box.width || !box.height || box.width > 5000 || box.height > 5000) throw Error('Invalid chart');
  const node = (tag, attrs = {}, text) => {
    const element = document.createElementNS(ns, tag);
    for (const [name, value] of Object.entries(attrs)) element.setAttribute(name, value);
    if (text !== undefined) element.textContent = text;
    return element;
  };
  const svg = node('svg', {viewBox:'0 0 900 1', width:900, role:'img'});
  const heading = section.querySelector('h2')?.textContent.trim() || 'News chart';
  const title = section.closest('article')?.querySelector('h1')?.textContent.trim() || heading;
  svg.append(node('title', {}, 'PoliticsHub — ' + title));
  const description = node('desc'), metadata = [];
  svg.append(description);
  const background = node('rect', {width:900, height:'100%', fill:getComputedStyle(section).backgroundColor});
  // Article figures always have an opaque card background in both themes.
  svg.append(background);
  const ink = getComputedStyle(section).color;
  let y = 30;
  const canvas = document.createElement('canvas').getContext('2d');
  canvas.font = '16px system-ui, sans-serif';
  const textLine = (text, bold = false) => {
    metadata.push(String(text).replace(/\s+/g,' ').trim());
    canvas.font = (bold ? '700 ' : '') + '16px system-ui, sans-serif';
    const lines = []; let line = '';
    for (const word of String(text).trim().split(/\s+/)) {
      if (line && canvas.measureText(line + ' ' + word).width > 800) { lines.push(line); line = ''; }
      if (canvas.measureText(word).width <= 800) { line += (line ? ' ' : '') + word; continue; }
      // Long URLs wrap by grapheme, preserving Marathi/Hindi combining marks.
      const segments = new Intl.Segmenter(undefined, {granularity:'grapheme'}).segment(word);
      for (const {segment} of segments) {
        if (canvas.measureText(line + segment).width > 800) { lines.push(line); line = ''; }
        line += segment;
      }
    }
    if (line) lines.push(line);
    for (const value of lines) {
      svg.append(node('text', {x:40, y:y+=23, fill:ink, 'font-family':'system-ui, sans-serif', 'font-size':16, 'font-weight':bold?700:400}, value));
    }
    y += 10;
  };
  textLine('POLITICSHUB.IN · ' + title, true);
  if (heading !== title) textLine(heading);
  textLine(section.querySelector('figcaption')?.textContent || '');
  const geometry = node('g', {transform:`translate(40 ${y}) scale(${820 / box.width}) translate(${-box.x} ${-box.y})`});
  const tags = new Set(['g','rect','circle','path','polyline','line','text','title']);
  const attrs = new Set(['x','y','x1','x2','y1','y2','width','height','rx','ry','cx','cy','r','d','points','text-anchor']);
  const copy = source => {
    if (!tags.has(source.localName)) return null;
    const target = node(source.localName);
    for (const {name, value} of source.attributes) if (attrs.has(name)) target.setAttribute(name, value);
    const style = getComputedStyle(source);
    for (const property of ['fill','stroke','stroke-width','stroke-dasharray','font-size','font-weight']) {
      const value = style.getPropertyValue(property);
      if (value && !/url\s*\(/i.test(value)) target.setAttribute(property, value);
    }
    target.setAttribute('font-family','system-ui, sans-serif');
    for (const child of source.childNodes) {
      if (child.nodeType === Node.TEXT_NODE) target.append(document.createTextNode(child.textContent));
      else if (child.nodeType === Node.ELEMENT_NODE) { const safe = copy(child); if (safe) target.append(safe); }
    }
    return target;
  };
  for (const child of original.children) { const safe = copy(child); if (safe) geometry.append(safe); }
  svg.append(geometry); y += box.height * 820 / box.width + 15;
  textLine('Displayed observations', true);
  const legend = chart.querySelectorAll('li');
  const observations = legend.length ? [...legend].map(li => [...li.children].map(n => n.textContent).join(' '))
    : [...chart.querySelectorAll('.data-bar,.story-point,.story-slice')].map(mark => mark.dataset.label + ': ' + mark.dataset.value);
  observations.forEach(value => textLine(value));
  const publication = section.closest('article')?.querySelector('.article-published');
  if (publication) textLine(publication.textContent);
  for (const paragraph of section.querySelectorAll('.article-data-description,.article-data-note,.article-data-freshness,.article-data-source,.article-data-table blockquote')) {
    if (!paragraph.querySelector('a[download]')) textLine(paragraph.textContent);
  }
  for (const link of section.querySelectorAll('.article-data-source a[href]')) {
    try {
      const url = new URL(link.href);
      if (/^https?:$/.test(url.protocol) && !url.username && !url.password) textLine(link.textContent + ': ' + url.href);
    } catch (_) {}
  }
  const hash = /^#\/article\/\d+$/.test(location.hash) ? location.hash : '';
  textLine('Page: ' + location.origin + location.pathname + hash);
  const height = Math.ceil(y + 30);
  // Keep complete, unbroken source URLs and labels accessible in the file,
  // even when their visible text must wrap across several lines.
  description.textContent = metadata.join('\n');
  svg.setAttribute('viewBox', '0 0 900 ' + height); svg.setAttribute('height', height);
  return new XMLSerializer().serializeToString(svg);
}

function addChartDownload(chart) {
  if (!chart.querySelector('svg')) return;
  const controls = document.createElement('p'); controls.className = 'article-data-export';
  const button = document.createElement('button'); button.type = 'button'; button.className = 'btn';
  button.textContent = 'Download chart (SVG)';
  const status = document.createElement('span'); status.setAttribute('role','status');
  controls.append(button, status); chart.closest('figure').after(controls);
  button.addEventListener('click', () => {
    let url;
    try {
      const content = chartDocument(chart);
      url = URL.createObjectURL(new Blob([content], {type:'image/svg+xml;charset=utf-8'}));
      const link = document.createElement('a'); link.href = url;
      const key = chart.closest('.article-data').querySelector('h2')?.id || 'chart';
      link.download = 'politicshub-' + key.replace(/[^a-z0-9-]/gi,'').slice(0,80) + '.svg';
      document.body.append(link); link.click(); link.remove();
      status.textContent = 'Chart prepared with source details. CSV keeps the exact reported values.';
    } catch (_) { status.textContent = 'Could not prepare this chart. Try again or use the figures CSV.'; }
    finally { if (url) setTimeout(() => URL.revokeObjectURL(url), 10000); }
  });
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
