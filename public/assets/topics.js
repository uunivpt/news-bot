(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const TOPICS = {
    all: null,
    elections: /\b(?:elect(?:ion|oral|ed)|vot(?:e|es|ing)|ballot|polls?|bjp|congress|assembly|mla|coalition)\b|निवडणूक|मतदान|चुनाव|विधानसभा|भाजप|काँग्रेस/i,
    parliament: /\b(?:parliament|lok sabha|rajya sabha|legislation|bill|policy|government|cabinet|minister)\b|संसद|लोकसभा|राज्यसभा|विधेयक|सरकार/i,
    maharashtra: /\b(?:maharashtra|mumbai|pune|nagpur|wardha|vidarbha|nashik|thane|kolhapur|marathi)\b|महाराष्ट्र|मुंबई|पुणे|नागपूर|विदर्भ|वर्धा/i,
    world: /\b(?:international|world|global|china|russia|ukraine|america|united states|israel|gaza|iran|europe|united kingdom)\b|जग|दुनिया|विदेश/i,
    economy: /\b(?:econom(?:y|ic)|budget|market|bank|inflation|rupee|trade|gst|rbi|investment|finance)\b|अर्थव्यवस्था|बाजार|महागाई|बँक/i
  };
  const VALID = new Set(['india','politics','world','hindi','maharashtra']);
  const all = [];
  let filtered = [], visible = 12, fallback = false;
  const preferencesAllowed = () => { try {return localStorage.getItem('ph-consent-v1') === 'preferences'} catch (_) {return false} };
  const text = (node, value) => { node.textContent = value == null ? '' : String(value); return node };
  const el = (tag, cls, value) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (value != null) text(node, value);
    return node;
  };
  const date = x => {
    const d = new Date(String(x || '').replace(/\s*[·•]\s*/g,' '));
    return Number.isFinite(d.getTime()) ? d : null;
  };
  const fmt = x => { const value = date(x); return value ? value.toLocaleString('en-IN', {timeZone:'Asia/Kolkata',day:'numeric',month:'short',year:'numeric',hour:'numeric',minute:'2-digit'}) + ' IST' : 'Date unavailable'; };
  const category = x => String(x.category || x.section || 'india').toLowerCase().trim();
  const safeUrl = value => {
    try {
      const url = new URL(String(value || ''), location.origin);
      if (!['https:','http:'].includes(url.protocol) || url.username || url.password) return '';
      return url.href;
    } catch (_) { return '' }
  };
  const articlePath = x => {
    const number = String(x.news_number || x.id || '');
    if (!/^\d+$/.test(number)) return '';
    const desk = category(x);
    const route = VALID.has(desk) ? (desk === 'maharashtra' ? 'india' : desk) : 'india';
    return '/' + route + '/' + number;
  };
  const normalize = (x, i) => ({
    id: String(x.id ?? ('record-' + i)),
    title: String(x.title || x.headline || '').trim(),
    summary: String(x.summary || x.bot_summary || x.description || '').trim(),
    source: String(x.source_name || (typeof x.source === 'string' ? x.source : x.source?.name) || x.publisher || 'Publisher').trim(),
    sourceUrl: safeUrl(x.url || x.link),
    date: x.published_at_iso || x.published_at_site || x.published_at || x.date || '',
    category: category(x),
    featured: x.editorial_featured === true,
    news_number: x.news_number,
  });
  const parse = data => {
    const rows = Array.isArray(data) ? data : (data.news || data.items || data.articles || data.data || []);
    return Array.isArray(rows) ? rows : [];
  };
  async function fetchJson(url) {
    const r = await fetch(url, {headers: {'Accept':'application/json'}, signal: AbortSignal.timeout(9500)});
    if (!r.ok) throw Error('HTTP ' + r.status);
    return parse(await r.json());
  }
  function from(rows) {
    for (const raw of rows) {
      if (!raw || typeof raw !== 'object') continue;
      const item = normalize(raw, all.length);
      if (item.title && articlePath(item) && !all.some(x => x.id === item.id)) all.push(item);
    }
    all.sort((a,b) => Number(b.featured) - Number(a.featured) || (date(b.date)?.getTime() || 0) - (date(a.date)?.getTime() || 0));
  }
  function external(item) {
    if (!item.sourceUrl) return null;
    const a = el('a','ph-story-source', 'Original publisher: ' + item.source);
    a.href = item.sourceUrl; a.rel = 'noopener noreferrer'; a.target = '_blank';
    return a;
  }
  function meta(item) {
    const node = el('div','ph-story-meta');
    node.append(el('span','',item.category.toUpperCase()), el('span','',fmt(item.date)));
    if (item.featured) node.append(el('span','','Newsroom featured'));
    return node;
  }
  function story(item, timeline = false) {
    const node = el(timeline ? 'li' : 'article',timeline ? '' : 'ph-story-card');
    const h = el('h3'), link = el('a','',item.title);
    link.href = articlePath(item); h.append(link);
    node.append(meta(item),h);
    if (item.summary) node.append(el('p','',item.summary.slice(0,360)));
    const source = external(item); if (source) node.append(source);
    else node.append(el('span','ph-muted','Original source link unavailable'));
    return node;
  }
  function matches(item) {
    const topic = $('topicSelect').value, desk = $('deskSelect').value;
    const duration = Number($('periodSelect').value);
    const search = $('topicSearch').value.toLocaleLowerCase().trim();
    const titleText = item.title + ' ' + item.summary;
    const isMaharashtra = TOPICS.maharashtra.test(titleText) || /tv9 marathi|abp majha|abp माझा/i.test(item.source);
    if (topic !== 'all' && !(topic === 'maharashtra' ? isMaharashtra : TOPICS[topic]?.test(titleText))) return false;
    if (desk !== 'all' && !(desk === 'maharashtra'
      ? isMaharashtra
      : (desk === 'politics' ? (item.category === 'politics' || TOPICS.elections.test(item.title)) : item.category === desk))) return false;
    if (duration && (!date(item.date) || Date.now() - date(item.date).getTime() > duration * 86400000)) return false;
    if (search && !(item.title+' '+item.source).toLocaleLowerCase().includes(search)) return false;
    return true;
  }
  function render() {
    filtered = all.filter(matches);
    // Timeline stays chronological even when the featured cards are editorially prioritized.
    const chronological = filtered.slice().sort((a,b) => (date(b.date)?.getTime() || 0) - (date(a.date)?.getTime() || 0));
    const features = $('featuredResults'); features.replaceChildren();
    if (filtered.length === 0) features.append(el('p','ph-topic-empty','No matching headlines. Choose another topic or date range.'));
    else filtered.slice(0,3).forEach(x => features.append(story(x)));
    const timeline = $('timelineResults'); timeline.replaceChildren();
    chronological.slice(0,visible).forEach(x => timeline.append(story(x,true)));
    if (!chronological.length) timeline.append(el('li','','No matching updates found.'));
    $('timelineCount').textContent = filtered.length + ' matching headlines';
    $('moreTimeline').hidden = filtered.length <= visible;
    const counts = new Map();
    for (const x of filtered) counts.set(x.source, (counts.get(x.source) || 0) + 1);
    const breakdown = $('sourceBreakdown'); breakdown.replaceChildren();
    [...counts].sort((a,b)=>b[1]-a[1]).slice(0,5).forEach(([name,count]) => {
      const p=el('p');p.append(el('span','',name),el('strong','',count));breakdown.append(p);
    });
    if (!counts.size) breakdown.append(el('p','','No sources in current selection.'));
  }
  function restorePreference() {
    const q = new URLSearchParams(location.search).get('topic');
    if (q && Object.prototype.hasOwnProperty.call(TOPICS,q)) {
      $('topicSelect').value = q;
    } else if (preferencesAllowed()) {
      try {const value=localStorage.getItem('ph-topic-v1'); if (Object.prototype.hasOwnProperty.call(TOPICS,value)) $('topicSelect').value = value} catch (_) {}
    }
    $('rememberTopic').checked = preferencesAllowed();
  }
  function savePreference() {
    if (!$('rememberTopic').checked) return;
    if (!preferencesAllowed()) {
      $('rememberTopic').checked = false;
      $('digestStatus').textContent = 'Enable optional site preferences first to remember your topic. Your current filter still works without storage.';
      return;
    }
    try {localStorage.setItem('ph-topic-v1',$('topicSelect').value)} catch (_) {}
  }
  function digest() {
    if (!filtered.length) { $('digestStatus').textContent = 'No headlines to copy for this selection.'; return }
    const label = $('topicSelect').selectedOptions[0].textContent;
    const result = ['PoliticsHub.in — '+label+' reading brief','Source-linked headlines · '+new Date().toLocaleDateString('en-IN'),''];
    filtered.slice().sort((a,b)=>(date(b.date)?.getTime()||0)-(date(a.date)?.getTime()||0)).slice(0,5).forEach((x,i)=>{
      result.push((i+1)+'. '+x.title, 'Published: '+fmt(x.date), 'Publisher: '+x.source);
      if (x.sourceUrl) result.push('Original source: '+x.sourceUrl);
      result.push('Read: '+new URL(articlePath(x),location.origin).href, '');
    });
    result.push('Summaries are reading aids. Verify claims at original sources.');
    const data=result.join('\n');
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(data).then(()=>{$('digestStatus').textContent='Copied '+Math.min(5,filtered.length)+' sourced headlines.'}).catch(()=>showCopy(data));
    } else showCopy(data);
  }
  function showCopy(value) {
    const node=el('textarea');node.readOnly=true;node.value=value;node.rows=10;node.style.width='100%';
    $('digestStatus').replaceChildren(el('p','','Select and copy the brief below:'),node);
    node.select();
  }
  for (const control of ['topicSelect','deskSelect','periodSelect','topicSearch']) {
    $(control).addEventListener(control==='topicSearch'?'input':'change',()=>{
      visible=12;savePreference();render();
    });
  }
  $('rememberTopic').addEventListener('change',()=>{
    if ($('rememberTopic').checked) savePreference();
    else try {localStorage.removeItem('ph-topic-v1')} catch (_) {}
  });
  $('moreTimeline').addEventListener('click',()=>{visible+=12;render()});
  $('copyDigest').addEventListener('click',digest);
  restorePreference();
  (async()=>{
    const main=await Promise.allSettled([fetchJson('/api/news?category=all&limit=120'),fetchJson('/api/hindi-feed')]);
    if (main[0].status === 'fulfilled') from(main[0].value);
    else {
      try {from(await fetchJson('/news-data.json'));fallback=true} catch (_) {}
    }
    if (main[1].status === 'fulfilled') from(main[1].value);
    const newest=all.map(x=>date(x.date)?.getTime()||0).reduce((a,b)=>Math.max(a,b),0);
    const stale=newest && Date.now()-newest>86400000;
    $('topicStatus').textContent=all.length
      ? all.length+' available headlines'+(fallback?' · backup feed': '')+(stale?' · latest record older than 24 hours':'')
      : 'News feeds unavailable. Browse the archive or try again.';
    render();
  })();
})();