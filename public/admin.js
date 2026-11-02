/* Private workspace state stays in memory. Only the display theme is persisted. */
'use strict';
const $ = id => document.getElementById(id);
const arr = value => Array.isArray(value) ? value : [];
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const views = {overview:'Overview',news:'Newsroom',sources:'Source coverage',operations:'Agent operations',upgrade:'Intelligence & QA',activity:'Activity',system:'System status',settings:'Settings'};
let csrf = '', settings = {}, workspace = null, rows = [], currentView = 'overview';
let pageNumber = 1, pageTotal = 0, queue = 'all', selected = new Set(), visibleRows = [];
let workspacePromise = null, newsController = null, newsSequence = 0, inspectorSequence = 0;
let newsTimer, liveTimer, noticeTimer, loginBusy = false, mutationBusy = false, sessionVersion = 0;
const pending = new Map();

function notice(message, type = 'ok') {
  $('notice').textContent = message;
  $('notice').className = 'notice ' + type;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => $('notice').classList.add('hidden'), 5500);
}
function showLogin(message = '') {
  sessionVersion++;
  closeMenu();
  clearInterval(liveTimer); liveTimer = null;
  newsController?.abort(); inspectorSequence++; newsSequence++;
  pending.clear(); workspacePromise = null;
  for (const id of ['inspector','commandDialog','confirmDialog']) if ($(id).open) $(id).close();
  workspace = null; rows = []; visibleRows = []; settings = {}; selected.clear(); csrf = '';
  for (const id of ['newsList','recentStories','activityList','inspectorBody','agents','errors','overviewMetrics','health','attentionList','sourceMetrics','sourceChart','sourceTable','qualityChart','deskChart','opsTotals','opsPhases','quality','advancedReport','upgradeMetrics','upgradeAlerts','upgradeScores','upgradeSources','upgradeEvents','upgradePreviews','upgradeResources','upgradeHistory','upgradeRegression','sessionDetails','systemChecks']) $(id).replaceChildren();
  $('shell').classList.add('hidden'); $('login').classList.remove('hidden');
  $('loginErr').textContent = message;
}
async function api(url, options = {}) {
  const method = options.method || 'GET';
  const request = async () => {
    const version = sessionVersion;
    const response = await fetch(url, {credentials:'same-origin', cache:'no-store', signal:AbortSignal.timeout(15000), ...options});
    let data = {};
    try { data = await response.json(); } catch { /* HTTP status still determines success. */ }
    if (version !== sessionVersion) throw new DOMException('Session changed','AbortError');
    if (!response.ok) {
      if (response.status === 401 && !url.endsWith('/login')) showLogin('Your session has ended. Please sign in again.');
      const error = new Error(data.error || `Request failed (${response.status})`);
      error.status = response.status;
      throw error;
    }
    return data;
  };
  // Share identical read requests; search requests have their own abort lifecycle.
  if (method !== 'GET' || options.signal) return request();
  if (pending.has(url)) return pending.get(url);
  const promise = request().finally(() => { if (pending.get(url) === promise) pending.delete(url); });
  pending.set(url, promise);
  return promise;
}
function action(url, body = {}, headers = {}) {
  if (workspace?.access.read_only) return Promise.reject(new Error(workspace?.data_origin === 'termux_github' ? 'Read-only public dashboard: edit stories on Termux instead.' : 'Read-only access. Restore the database and sign in again to make changes.'));
  return api(url, {method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':csrf,...headers}, body:JSON.stringify(body)});
}
function metric(label, value, detail = '') {
  return `<div class="card metric"><small>${esc(label)}</small><strong>${esc(value ?? '—')}</strong><span>${esc(detail)}</span></div>`;
}
function pct(value) { return value == null ? '—' : value + '%'; }
function number(value) { return value == null ? '—' : Number(value).toLocaleString('en-IN'); }
function date(value) {
  if (!value) return 'Not recorded';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString('en-IN', {dateStyle:'medium',timeStyle:'short',timeZone:'Asia/Kolkata'}) + ' IST';
}
function age(seconds) {
  if (seconds == null) return 'Unknown';
  if (seconds < 60) return 'Less than a minute';
  if (seconds < 3600) return Math.floor(seconds / 60) + ' minutes';
  if (seconds < 86400) return Math.floor(seconds / 3600) + ' hours';
  return Math.floor(seconds / 86400) + ' days';
}
function safeUrl(value) {
  try { const url = new URL(String(value), location.origin); return ['http:','https:'].includes(url.protocol) ? url.href : ''; } catch { return ''; }
}
function empty(title, message) { return `<div class="empty"><h3>${esc(title)}</h3><p>${esc(message)}</p></div>`; }
function barChart(items, total, limit = 8) {
  return arr(items).slice(0, limit).map(item => `<div class="bar-row"><div class="bar-label"><span>${esc(item.name)}</span><b>${number(item.count)}</b></div><div class="bar-track"><i style="width:${Math.min(100,Math.max(0,Number(item.count) / Math.max(1,total) * 100))}%"></i></div></div>`).join('') || empty('No data yet','No records are available for this sample.');
}
function detail(label, value) { return `<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`; }
function closeMenu(returnFocus = false) {
  const wasOpen = $('sidebar').classList.contains('open');
  $('sidebar').classList.remove('open'); $('sidebarBackdrop').classList.add('hidden');
  $('menuToggle').setAttribute('aria-expanded','false');
  $('sidebar').inert = matchMedia('(max-width: 800px)').matches;
  document.body.style.overflow = '';
  if (wasOpen && returnFocus) $('menuToggle').focus();
}
function go(view, updateHash = true) {
  if (!views[view]) view = 'overview';
  currentView = view;
  document.querySelectorAll('.view').forEach(node => node.classList.toggle('active', node.id === view));
  document.querySelectorAll('.nav button').forEach(node => { node.classList.toggle('active',node.dataset.view === view); if (node.dataset.view === view) node.setAttribute('aria-current','page'); else node.removeAttribute('aria-current'); });
  $('pageTitle').textContent = views[view];
  document.title = views[view] + ' · PoliticsHub Admin';
  if (updateHash) history.replaceState(null,'','#' + view);
  closeMenu();
  if (view === 'news') loadNews();
  if (view === 'sources') renderSources();
  if (view === 'operations') loadOps();
  if (view === 'upgrade') loadUpgrade();
  if (view === 'activity') loadActivity();
  if (view === 'system') renderSystem();
  if (view === 'settings') loadSettings();
  window.scrollTo({top:0,behavior:'instant'});
}
function applyCapabilities() {
  const writable = !!workspace && !workspace.access.read_only;
  document.querySelectorAll('[data-write]').forEach(node => { node.disabled = !writable || mutationBusy; node.title = writable ? '' : workspace?.data_origin === 'termux_github' ? 'Edits run on the Termux phone, not on the public website' : 'Requires a live database and owner session'; });
  $('status').disabled = !writable; $('review').disabled = !writable;
  $('settingsState').textContent = writable ? '' : workspace?.data_origin === 'termux_github' ? 'Read-only website. Review and approve stories using the local Termux workflow.' : 'Read-only. Publishing controls require a live database owner session.';
}
function renderWorkspace() {
  const data = workspace, health = data.health, stats = data.stats, sample = data.coverage.sample_size;
  const githubOnly = data.data_origin === 'termux_github';
  rows = data.stories;
  settings = data.settings || {};
  $('userName').textContent = data.access.username;
  $('avatar').textContent = data.access.username.slice(0,1).toUpperCase();
  $('sessionRole').textContent = data.access.scope === 'recovery' ? 'Recovery · read-only' : data.access.read_only ? (githubOnly ? 'Owner · GitHub feed view' : 'Owner · database unavailable') : 'Owner session';
  $('connectionBadge').className = 'pill ' + (data.mode === 'live' || (githubOnly && sample) ? 'green' : 'amber');
  $('connectionBadge').textContent = data.mode === 'live' ? 'Live database' : githubOnly ? 'GitHub news feed' : 'Snapshot mode';
  $('workspaceBanner').classList.toggle('hidden',!data.notice);
  $('workspaceBanner').innerHTML = data.notice ? `<p><b>${data.access.read_only ? 'Read-only workspace. ' : ''}</b>${esc(data.notice)}</p><button class="text-btn" data-view="system">View status ↗</button>` : '';
  $('heroEyebrow').textContent = data.mode === 'live' ? 'EDITORIAL PULSE' : githubOnly ? 'PUBLIC FEED MONITOR' : 'CONTINUITY MODE';
  $('heroTitle').textContent = data.mode === 'live' ? (stats.review_needed ? `${number(stats.review_needed)} stories need a closer look.` : 'The next story starts here.') : 'The newsroom stays in view.';
  $('heroDescription').textContent = data.mode === 'live' ? 'Review your queue, inspect source material and keep publication decisions accountable.' : githubOnly ? 'Published news is delivered through GitHub. Private editing, reviews and PostgreSQL remain on your Termux phone; this website cannot access that local database.' : 'Browse the latest saved public reports, inspect coverage and follow recovery status. Editorial changes resume when the database is restored.';
  $('heroCount').textContent = number(sample);
  $('heroCountLabel').textContent = data.mode === 'live' ? 'recent stories loaded' : githubOnly ? 'published GitHub stories' : 'public snapshot stories';
  $('overviewMetrics').innerHTML = metric(data.mode === 'live' ? 'All stories' : githubOnly ? 'Public feed stories' : 'Snapshot stories',number(data.mode === 'live' ? stats.total : sample),data.mode === 'live' ? 'Entire database' : 'Latest saved public copy') + metric('Published',number(stats.published),data.mode === 'live' ? 'Entire database' : 'In this snapshot') + metric('Needs review',number(stats.review_needed),data.mode === 'live' ? 'Verification queue' : 'Requires live moderation data') + metric('Pending',number(stats.pending),data.mode === 'live' ? 'Awaiting publication' : 'Requires live editorial data');
  $('queueBadge').textContent = stats.pending == null ? number(sample) : number(stats.pending);
  $('recentStories').innerHTML = rows.slice(0,5).map((row,index) => `<article class="recent-story"><span class="story-index">${String(index+1).padStart(2,'0')}</span><div><button data-inspect="${Number(row.id)}">${esc(row.title)}</button><div class="meta">${esc(row.source_name || 'Unknown source')} · ${esc(row.category || 'General')}</div></div></article>`).join('') || empty('No reports available','No saved public stories were found.');
  $('deskChart').innerHTML = barChart(data.coverage.categories,sample,6);
  $('coverageScope').textContent = `Based on ${sample} loaded stories. Distribution is not a count of the full archive.`;
  $('health').innerHTML = `<div class="health-row"><div><b>${githubOnly ? 'News storage' : 'Database'}</b><small>${githubOnly ? 'PostgreSQL is local to Termux; phone health is not checked here' : health.database === 'connected' ? 'Connection available' : 'Persistent services are paused'}</small></div><span class="pill ${health.database === 'connected' ? 'green' : 'amber'}">${githubOnly ? 'Termux' : esc(health.database)}</span></div><div class="health-row"><div><b>Story delivery</b><small>Newest report: ${esc(date(health.latest_published_at))}</small></div><span class="pill ${health.latest_age_seconds != null && health.latest_age_seconds < 86400 ? 'green' : 'amber'}">${esc(age(health.latest_age_seconds))}</span></div><div class="health-row"><div><b>Editorial permissions</b><small>${data.access.read_only ? 'Changes are disabled server-side' : 'Authenticated owner access'}</small></div><span class="pill ${data.access.read_only ? 'amber' : 'green'}">${data.access.read_only ? 'Read-only' : 'Owner'}</span></div>`;
  $('attentionList').innerHTML = data.coverage.quality.slice(0,4).map(item => `<div class="attention-row"><span>${esc(item.name)}</span><b>${number(item.count)} stories</b></div>`).join('') || '<p class="muted">No completeness flags in the loaded sample.</p>';
  const synced = new Date(data.generated_at).toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit'});
  $('footerSync').textContent = `Updated ${synced} IST · Refreshes every 60s on overview`;
  $('todayLabel').textContent = new Date().toLocaleDateString('en-IN',{timeZone:'Asia/Kolkata',weekday:'short',day:'numeric',month:'long',year:'numeric'});
  fillOptions('category',data.coverage.categories,'All desks');
  fillOptions('source',data.coverage.sources,'All sources');
  applyCapabilities();
  if (currentView === 'sources') renderSources();
  if (currentView === 'system') renderSystem();
}
function fillOptions(id, items, label) {
  const value = $(id).value;
  $(id).innerHTML = `<option value="all">${label}</option>` + arr(items).map(item => `<option value="${esc(item.name)}">${esc(item.name)}</option>`).join('');
  if ([...$(id).options].some(option => option.value === value)) $(id).value = value;
}
async function loadOverview(silent = false) {
  if (workspacePromise) return workspacePromise;
  const version = sessionVersion;
  $('refresh').disabled = true;
  workspacePromise = (async () => {
    try { const data = await api('/api/admin/workspace'); if ($('shell').classList.contains('hidden')) return; workspace = data; renderWorkspace(); return data; }
    catch (error) { if (version === sessionVersion && error.status !== 401) { if (!silent) notice(error.message,'err'); $('connectionBadge').className = 'pill amber'; $('connectionBadge').textContent = 'Refresh failed'; $('workspaceBanner').classList.remove('hidden'); $('workspaceBanner').textContent = 'Workspace refresh failed. Displayed data may be out of date. Retry with Refresh.'; } }
    finally { if (version === sessionVersion) { workspacePromise = null; $('refresh').disabled = false; } }
  })();
  return workspacePromise;
}
function filteredSnapshot() {
  const query = $('search').value.trim().toLowerCase();
  const result = rows.filter(row => (!query || [row.title,row.summary,row.source_name].join(' ').toLowerCase().includes(query)) && ($('category').value === 'all' || row.category === $('category').value) && ($('source').value === 'all' || row.source_name === $('source').value) && ($('status').value === 'all' || row.status === $('status').value) && (queue !== 'quality' || row.quality_flags.length));
  const sort = $('sort').value;
  return result.sort((a,b) => sort === 'oldest' ? (a.timestamp || 0)-(b.timestamp || 0) : sort === 'views' ? Number(b.view_count || 0)-Number(a.view_count || 0) : sort === 'quality' ? b.quality_flags.length-a.quality_flags.length : (b.timestamp || 0)-(a.timestamp || 0));
}
function storyActions(row) {
  if (workspace?.access.read_only) return `<button class="btn" data-inspect="${Number(row.id)}">Inspect ↗</button>`;
  const id = Number(row.id);
  return `<button class="btn" data-inspect="${id}">Inspect</button>` + (!row.article_available ? `<button class="btn" data-news="process" data-id="${id}">Process</button>` : '') + (row.status === 'pending' && !['reviewed','verified','passed','approved'].includes(row.fact_check_status) ? `<button class="btn" data-news="approve" data-id="${id}">Verify &amp; approve</button>` : '') + (row.status === 'pending' && ['reviewed','verified','passed','approved'].includes(row.fact_check_status) ? `<button class="btn" data-news="publish" data-id="${id}">Publish</button>` : '') + (row.status !== 'rejected' ? `<button class="btn danger" data-news="reject" data-id="${id}">Reject</button>` : '');
}
function renderNews(list, total) {
  visibleRows = list; pageTotal = total;
  $('newsList').innerHTML = list.map(row => `<article class="story"><input type="checkbox" data-select="${Number(row.id)}" aria-label="Select story ${Number(row.id)}" ${selected.has(Number(row.id)) ? 'checked' : ''}><div class="story-content"><div class="story-tags"><span class="desk-tag">${esc(row.category || 'General')}</span><span class="pill ${row.status === 'published' ? 'green' : 'amber'}">${esc(row.status)}</span><span class="quality-tag">${row.quality_flags.length ? row.quality_flags.length+' completeness flags' : 'No completeness flags'}</span></div><h3><button class="story-title" data-inspect="${Number(row.id)}">${esc(row.title)}</button></h3><div class="meta">#${Number(row.id)} · ${esc(row.source_name || 'Unknown source')} · ${esc(date(row.timestamp ? row.timestamp * 1000 : row.published_at))}</div><p>${esc(row.summary)}</p></div><div class="actions">${storyActions(row)}</div></article>`).join('') || empty('No matching stories','Try another search or reset your filters.');
  $('newsCount').textContent = `${number(total)} matching ${total === 1 ? 'story' : 'stories'}`;
  $('newsScope').textContent = workspace.mode === 'snapshot' ? `Read-only search across ${rows.length} saved public reports. Private queues require the database.` : 'Search the full database. Showing 25 stories per page.';
  $('exportNews').textContent = workspace.mode === 'snapshot' ? '↓ Export filtered CSV' : '↓ Export page CSV';
  $('prevPage').disabled = pageNumber <= 1;
  $('nextPage').disabled = pageNumber * 25 >= total;
  $('pageInfo').textContent = `Page ${pageNumber} of ${Math.max(1,Math.ceil(total/25))}`;
  updateSelection();
}
async function loadNews(reset = false) {
  if (!workspace) return;
  if (reset) { pageNumber = 1; selected.clear(); }
  const sequence = ++newsSequence;
  newsController?.abort();
  if (workspace.mode === 'snapshot') { const result = filteredSnapshot(); renderNews(result.slice((pageNumber-1)*25,pageNumber*25),result.length); return; }
  newsController = new AbortController();
  $('newsList').setAttribute('aria-busy','true');
  const query = new URLSearchParams({page:pageNumber,search:$('search').value.trim(),category:$('category').value,source:$('source').value,status:$('status').value,review:$('review').value,sort:$('sort').value,quality:queue === 'quality' ? '1' : '0'});
  try { const data = await api('/api/admin/stories?' + query,{signal:AbortSignal.any([newsController.signal,AbortSignal.timeout(15000)])}); if (sequence === newsSequence) renderNews(data.stories,data.total); }
  catch (error) { if (sequence === newsSequence && error.name !== 'AbortError') { notice(error.message,'err'); if (error.status === 503) { await loadOverview(); if (workspace?.mode === 'snapshot') loadNews(true); } } }
  finally { if (sequence === newsSequence) $('newsList').removeAttribute('aria-busy'); }
}
function updateSelection() {
  $('bulkBar').classList.toggle('hidden',!selected.size);
  $('selectedCount').textContent = `${selected.size} selected · maximum 10 per action`;
  $('selectAll').checked = visibleRows.length > 0 && visibleRows.every(row => selected.has(Number(row.id)));
  $('selectAll').indeterminate = visibleRows.some(row => selected.has(Number(row.id))) && !$('selectAll').checked;
}
function confirmAction(title, message) {
  $('confirmTitle').textContent = title; $('confirmMessage').textContent = message;
  const dialog = $('confirmDialog'); dialog.returnValue = ''; dialog.showModal();
  return new Promise(resolve => dialog.addEventListener('close',() => resolve(dialog.returnValue === 'yes'),{once:true}));
}
async function newsAction(kind, id) {
  if (mutationBusy || workspace?.access.read_only || !['process','approve','publish','reject'].includes(kind)) return;
  if (['publish','reject'].includes(kind) && !await confirmAction(`${kind === 'publish' ? 'Publish' : 'Reject'} this story?`,`Story #${id}. This changes its publication state in the live database.`)) return;
  let payload = {};
  if (kind === 'approve') {
    const evidence = prompt('Independently verified source URLs (one per line; conflict/Telegram news needs at least two different publishers):');
    if (evidence === null) return;
    const sources = evidence.split(/[\\n,]+/).map(s => s.trim()).filter(Boolean);
    const notes = prompt('Verification notes: which facts, dates, locations, context and originality did you personally check? (40+ characters)');
    if (notes === null) return;
    const confirmation = prompt(`After checking the FULL article, type APPROVE ${id} to confirm this exact story:`);
    if (confirmation !== `APPROVE ${id}`) return notice('Approval cancelled; no changes made.','err');
    payload = {evidence_urls:sources,notes,confirm:confirmation,confirmed_facts:true,confirmed_originality:true};
  }
  mutationBusy = true; applyCapabilities();
  try { await action(`/api/news/${id}/${kind}`, payload); notice(kind === 'approve' ? 'Human verification saved; publish only after final review.' : 'Action completed'); await loadOverview(); await loadNews(); }
  catch (error) { notice(error.message,'err'); }
  finally { mutationBusy = false; applyCapabilities(); }
}
async function bulkAction(kind) {
  if (mutationBusy || workspace?.access.read_only || !selected.size) return;
  if (selected.size > 10) return notice('Select at most 10 stories per action.','err');
  if (['approve','publish'].includes(kind)) return notice('Approve and publish one verified story at a time; bulk publication is disabled.','err');
  const ids = [...selected];
  if (!await confirmAction(`${kind === 'approve' ? 'Mark reviewed' : kind === 'publish' ? 'Publish' : 'Reject'} ${ids.length} stories?`,'Actions run sequentially. Processing stops at the first failure; completed changes stay saved.')) return;
  mutationBusy = true; applyCapabilities();
  let completed = 0;
  try { for (const id of ids) { await action(`/api/news/${id}/${kind}`); selected.delete(id); completed++; } notice(`${completed} stories updated`); }
  catch (error) { notice(`${completed} updated. Stopped: ${error.message}`,'err'); }
  finally { mutationBusy = false; await loadOverview(); await loadNews(); applyCapabilities(); }
}
async function inspectStory(id) {
  const row = [...visibleRows,...rows].find(item => Number(item.id) === id);
  if (!row) return;
  const sequence = ++inspectorSequence, url = safeUrl(row.url);
  $('inspectorBody').innerHTML = `<span class="desk-tag">${esc(row.category || 'General')} / #${id}</span><h2 id="inspectorTitle">${esc(row.title)}</h2><span class="pill ${row.status === 'published' ? 'green' : 'amber'}">${esc(row.status)}</span><dl class="detail-grid">${detail('Source',row.source_name || 'Unknown')}${detail('Published',date(row.timestamp ? row.timestamp*1000 : row.published_at))}${detail('Review',row.fact_check_status || 'Not available in public snapshot')}${detail('Recorded views',number(row.view_count))}</dl><p class="inspector-summary">${esc(row.summary || 'No summary available.')}</p><div class="quality-flags">${row.quality_flags.map(flag => `<span class="pill amber">${esc(flag)}</span>`).join('')}</div><div class="actions">${url ? `<a class="btn" target="_blank" rel="noopener noreferrer" href="${esc(url)}">Open original source ↗</a>` : ''}<button id="loadArticle" class="btn">Load article text</button><button id="copySource" class="btn" ${url ? '' : 'disabled'}>Copy source URL</button></div><div id="inspectorArticle" class="article-body"></div>`;
  if (!$('inspector').open) $('inspector').showModal();
  $('loadArticle').onclick = async () => {
    $('loadArticle').disabled = true; $('inspectorArticle').textContent = 'Loading article…';
    try { const data = await api((workspace && !workspace.access.read_only ? '/api/admin/story/' + id + '/article' : '/api/news/' + id)); if (sequence !== inspectorSequence || !$('inspector').open) return; $('inspectorArticle').textContent = data.article || data.bot_article || data.summary || 'No article text available.'; }
    catch (error) { if (sequence === inspectorSequence && $('inspector').open) { $('inspectorArticle').textContent = error.message; $('loadArticle').disabled = false; } }
  };
  $('copySource').onclick = async () => { try { await navigator.clipboard.writeText(url); notice('Source link copied'); } catch { notice('Clipboard unavailable. Open the original source link.','err'); } };
  if (!workspace.access.read_only) {
    const editor = document.createElement('details'); editor.className = 'story-editor';
    editor.innerHTML = `<summary>Edit headline &amp; summary</summary><form id="editStoryForm"><label class="label" for="editTitle">Headline</label><textarea id="editTitle" class="field" maxlength="500" required rows="3">${esc(row.title)}</textarea><label class="label" for="editCategory">Editorial desk</label><select id="editCategory" class="field">${['general','india','world','politics','business','technology','sports','entertainment','science','health','hindi','maharashtra'].map(category => `<option ${category === row.category ? 'selected' : ''}>${category}</option>`).join('')}</select><label class="label" for="editSummary">Summary</label><textarea id="editSummary" class="field" maxlength="6000" rows="5">${esc(row.summary)}</textarea><p class="panel-foot">Changes are saved to the database and recorded in the audit trail. Source links stay attached to the story.</p><button class="btn primary" type="submit">Save story</button></form>`;
    $('inspectorBody').append(editor);
    let revision = '', draftLoading = false;
    const draftControls = [...editor.querySelectorAll('textarea,select,button')];
    draftControls.forEach(control => control.disabled = true);
    editor.addEventListener('toggle',async () => {
      if (!editor.open || revision || draftLoading) return;
      draftLoading = true;
      try {
        const draft = await api('/api/admin/story/' + id);
        if (sequence !== inspectorSequence || !$('inspector').open) return;
        revision = draft.revision;
        $('editTitle').value = draft.title; $('editSummary').value = draft.summary; $('editCategory').value = draft.category;
        draftControls.forEach(control => control.disabled = false);
      } catch (error) { notice('Could not load the full editable draft: ' + error.message,'err'); }
      finally { draftLoading = false; }
    });
    $('editStoryForm').onsubmit = async event => {
      event.preventDefault(); const button = event.currentTarget.querySelector('[type=submit]'); button.disabled = true;
      if (!revision) { button.disabled = false; return notice('Load the full editorial draft before saving.','err'); }
      try { await action('/api/news/' + id + '/edit',{title:$('editTitle').value.trim(),category:$('editCategory').value,summary:$('editSummary').value.trim(),bot_summary:$('editSummary').value.trim()},{'If-Match':revision}); $('inspector').close(); notice('Story changes saved'); await loadOverview(); await loadNews(); }
      catch (error) { notice(error.message,'err'); }
      finally { button.disabled = false; }
    };
  }
}
function renderSources() {
  if (!workspace) return;
  const data = workspace.coverage, total = data.sample_size, lead = data.sources[0];
  $('sourceMetrics').innerHTML = metric('Sources represented',data.sources.length,'In the loaded sample') + metric('Desks represented',data.categories.length,'In the loaded sample') + metric('Largest source share',lead ? pct(Math.round(lead.count/Math.max(1,total)*100)) : '—',lead?.name || 'No records') + metric('Reports sampled',number(total),workspace.mode === 'snapshot' ? 'Saved public snapshot' : 'Latest database records');
  $('sourceChart').innerHTML = barChart(data.sources,total,12);
  $('qualityChart').innerHTML = barChart(data.quality,total,10);
  $('sourceScope').textContent = total + ' loaded stories';
  $('sourceTable').innerHTML = '<table class="table"><thead><tr><th>Publisher</th><th>Stories</th><th>Share</th><th>Latest report</th><th></th></tr></thead><tbody>' + data.sources.map(source => {const matching = rows.filter(row => (row.source_name || 'Unknown') === source.name); const latest = Math.max(...matching.map(row => row.timestamp || 0)); return `<tr><td>${esc(source.name)}</td><td>${source.count}</td><td>${Math.round(source.count/Math.max(1,total)*100)}%</td><td>${esc(latest ? date(latest*1000) : 'Not recorded')}</td><td><button class="text-btn" data-source-filter="${esc(source.name)}">View stories ↗</button></td></tr>`;}).join('') + '</tbody></table>';
}
function telemetryAvailable(kind) {
  const available = !!workspace?.capabilities.telemetry;
  $(kind + 'Content').classList.toggle('hidden',!available);
  $(kind + 'Unavailable').classList.toggle('hidden',available);
  if (!available) $(kind + 'Unavailable').innerHTML = '<h3>Live telemetry is unavailable</h3><p>Worker history is private to the phone PostgreSQL database. This website serves the public GitHub feed only; review execution metrics locally in Termux.</p><button class="btn" data-view="system">View system status</button>';
  return available;
}
function telemetryError(kind, message) {
  $(kind + 'Content').classList.add('hidden');
  $(kind + 'Unavailable').classList.remove('hidden');
  $(kind + 'Unavailable').innerHTML = '<h3>Telemetry refresh failed</h3><p>' + esc(message) + '</p><p>Refresh this section to retry. Previous metrics are hidden until a successful response.</p>';
  notice(message,'err');
}
async function loadActivity() {
  if (!workspace) return;
  if (!workspace.capabilities.telemetry) { $('activityList').innerHTML = empty('The audit trail needs the database','The public GitHub feed does not expose private phone editing or audit history.'); return; }
  try { const items = await api('/api/admin/activity?limit=100'); $('activityList').innerHTML = arr(items).map(item => `<article class="activity-item"><h3>${esc(item.action)}</h3><div class="meta">${esc(date(item.created_at))} · ${esc(item.username || 'System')}${item.item_id ? ' · #'+Number(item.item_id) : ''}</div><p>${esc(item.details || '')}</p></article>`).join('') || empty('No activity recorded','Admin actions will appear here after they are saved.'); }
  catch (error) { notice(error.message,'err'); }
}
function renderSystem() {
  if (!workspace) return;
  const health = workspace.health, access = workspace.access;
  $('systemChecks').innerHTML = (workspace.data_origin === 'termux_github' ? metric('Primary storage','Termux PostgreSQL','Private phone database; not remotely checked') + metric('Public delivery','GitHub feed','Approved phone exports plus attributed public sources') : metric('Database',health.database === 'connected' ? 'Connected' : 'Unavailable',health.database === 'connected' ? 'Connection verified' : 'Persistent writes are paused') + metric('Data mode',workspace.mode === 'live' ? 'Live' : 'Snapshot',workspace.mode === 'live' ? 'Database-backed newsroom' : 'Saved public reports')) + metric('Latest report age',age(health.latest_age_seconds),date(health.latest_published_at)) + metric('Workspace response',health.response_ms + ' ms','Server processing time, not browser latency');
  $('lastSync').textContent = 'Checked ' + date(workspace.generated_at);
  $('sessionDetails').innerHTML = detail('Signed in as',access.username) + detail('Access scope',access.scope === 'recovery' ? 'Recovery · read-only' : access.read_only ? 'Owner · writes unavailable' : 'Owner') + detail('Session expires',access.expires_at ? date(access.expires_at*1000) : 'Legacy session') + detail(workspace.data_origin === 'termux_github' ? 'Public website edits' : 'Database writes',workspace.data_origin === 'termux_github' ? 'Disabled — manage locally in Termux' : access.read_only ? 'Blocked' : 'Allowed with CSRF protection') + detail('Private data storage','Session cookie only; no admin records in local storage') + detail('Coverage limit',workspace.limits.stories + ' loaded stories; charts describe this sample');
}
function fillSettings(value) { settings = value || {}; $('websiteEnabled').checked = settings.website_enabled !== 'false'; }
async function loadSettings() {
  $('trainAgent').innerHTML = ['trend','manager','research','factcheck','writer','reviewer','hr','automation','publisher','reporting'].map(agent => `<option>${agent}</option>`).join('');
  if (workspace?.access.read_only) { $('websiteEnabled').checked = false; applyCapabilities(); return; }
  $('saveSettings').disabled = true; $('siteToggle').disabled = true;
  try { fillSettings(await api('/api/admin/settings')); applyCapabilities(); }
  catch (error) { notice(error.message,'err'); }
}
async function saveSettings() {
  $('saveSettings').disabled = true;
  try { const data = await action('/api/admin/settings',{website_enabled:$('websiteEnabled').checked}); if (!data.ok) throw new Error('Save was not confirmed'); fillSettings(data.settings); notice('Controls saved'); }
  catch (error) { notice(error.message,'err'); }
  finally { applyCapabilities(); }
}
function download(name, text, type) {
  const blob = new Blob([text],{type}); const url = URL.createObjectURL(blob), link = document.createElement('a');
  link.href = url; link.download = name; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url),1000);
}
function csvCell(value) {
  let text = String(value ?? '');
  if (/^[\s]*[=+\-@]/.test(text)) text = "'" + text; // Prevent spreadsheet formula execution.
  return '"' + text.replace(/"/g,'""') + '"';
}
function exportNews() {
  const list = workspace?.mode === 'snapshot' ? filteredSnapshot() : visibleRows;
  const fields = ['id','title','source_name','category','status','url','published_at'];
  const text = [fields.map(csvCell).join(','),...list.map(row => fields.map(key => csvCell(row[key])).join(','))].join('\r\n');
  download('politicshub-stories-' + new Date().toISOString().slice(0,10) + '.csv','\ufeff' + text,'text/csv;charset=utf-8');
}
function openCommands() {
  if ($('shell').classList.contains('hidden')) return;
  $('commandInput').value = ''; renderCommands(); $('commandDialog').showModal(); $('commandInput').focus();
}
let commandIndex = 0;
function renderCommands() {
  const query = $('commandInput').value.trim().toLowerCase(); commandIndex = 0;
  $('commandResults').innerHTML = Object.entries(views).filter(([,label]) => label.toLowerCase().includes(query)).map(([key,label],index) => `<button class="command-item" data-command="${key}" aria-selected="${index === 0}"><span>${esc(label)}</span><small>Open ↵</small></button>`).join('') || '<p class="muted">No matching sections.</p>';
}
async function signedIn(data) {
  csrf = data.csrf_token || '';
  $('password').value = ''; $('password').type = 'password'; $('showPassword').textContent = 'Show'; $('showPassword').setAttribute('aria-pressed','false');
  $('login').classList.add('hidden'); $('shell').classList.remove('hidden');
  await loadOverview();
  if (!workspace) return;
  go(location.hash.slice(1) || 'overview',false);
  if (!liveTimer) liveTimer = setInterval(() => { if (!document.hidden && currentView === 'overview' && !mutationBusy) loadOverview(true); },60000);
}

function manualPayload() {
 return {
  title:$('newTitle').value.trim(), category:$('newCategory').value,
  source_name:$('newSourceName').value.trim(), source_url:$('newSourceUrl').value.trim(),
  summary:$('newSummary').value.trim(), article:$('newArticle').value.trim(),
  image_url:$('newImageUrl').value.trim(), image_license:$('newImageLicense').value,
  image_credit:$('newImageCredit').value.trim()
 };
}
$('previewManual').onclick = () => {
 const row = manualPayload();
 $('manualPreview').replaceChildren();
 const title = document.createElement('h2'); title.textContent = row.title || 'Untitled';
 const summary = document.createElement('p'); summary.textContent = row.summary;
 const article = document.createElement('div'); article.textContent = row.article;
 article.style.whiteSpace = 'pre-wrap';
 $('manualPreview').append(title,summary,article);
 $('manualPreview').parentElement.open = true;
};
$('createArticleForm').onsubmit = async event => {
 event.preventDefault();
 if (workspace?.access.read_only) return notice('Remote write access is not connected yet. Open the authenticated phone admin or configure the secure bridge.','err');
 const button = $('saveManual'); button.disabled = true;
 try {
  const result = await action('/api/admin/news/create',manualPayload());
  $('createArticleForm').reset(); $('manualMessage').textContent = 'Draft #' + result.id + ' saved for human review.';
  notice('New article draft #' + result.id + ' saved. Verify before publishing.');
  await loadOverview(); await loadNews(true);
 } catch(error) { $('manualMessage').textContent = error.message; notice(error.message,'err'); }
 finally { button.disabled = false; applyCapabilities(); }
};
$('loginForm').onsubmit = async event => {
  event.preventDefault(); if (loginBusy) return; loginBusy = true;
  const submit = event.currentTarget.querySelector('[type=submit]'); submit.disabled = true; $('loginErr').textContent = 'Verifying your account…';
  try { const data = await api('/api/admin/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:$('username').value.trim(),password:$('password').value})}); $('loginErr').textContent = ''; await signedIn(data); }
  catch (error) { $('loginErr').textContent = error.name === 'TimeoutError' ? 'Sign-in timed out. Please retry.' : error.message; }
  finally { loginBusy = false; submit.disabled = false; }
};
$('showPassword').onclick = () => { const visible = $('password').type === 'password'; $('password').type = visible ? 'text' : 'password'; $('showPassword').textContent = visible ? 'Hide' : 'Show'; $('showPassword').setAttribute('aria-pressed',String(visible)); };
$('logout').onclick = async () => {
  $('logout').disabled = true;
  try { await api('/api/admin/logout',{method:'POST',headers:{'X-CSRF-Token':csrf}}); showLogin(); }
  catch (error) { notice('Sign-out was not confirmed. Please retry.','err'); }
  finally { $('logout').disabled = false; }
};
$('refresh').onclick = async () => { await loadOverview(); go(currentView,false); };
$('newsRefresh').onclick = async () => { await loadOverview(); loadNews(); };
$('search').oninput = () => { newsSequence++; newsController?.abort(); clearTimeout(newsTimer); newsTimer = setTimeout(() => loadNews(true),250); };
for (const id of ['category','source','status','review','sort']) $(id).onchange = () => loadNews(true);
$('resetFilters').onclick = () => { $('search').value = ''; for (const id of ['category','source','status','review']) $(id).value = 'all'; $('sort').value = 'newest'; queue = 'all'; document.querySelectorAll('[data-queue]').forEach(node => node.classList.toggle('active',node.dataset.queue === 'all')); loadNews(true); };
$('selectAll').onchange = event => { for (const row of visibleRows) event.target.checked ? selected.add(Number(row.id)) : selected.delete(Number(row.id)); renderNews(visibleRows,pageTotal); };
$('clearSelection').onclick = () => { selected.clear(); renderNews(visibleRows,pageTotal); };
$('prevPage').onclick = () => { pageNumber--; loadNews(); };
$('nextPage').onclick = () => { pageNumber++; loadNews(); };
$('exportNews').onclick = exportNews;
$('downloadDiagnostics').onclick = () => { if (workspace) download('politicshub-diagnostics.json',JSON.stringify({generated_at:workspace.generated_at,mode:workspace.mode,health:workspace.health,capabilities:workspace.capabilities,limits:workspace.limits},null,2),'application/json'); };
$('saveSettings').onclick = saveSettings;
$('siteToggle').onclick = async () => { if (!await confirmAction('Change website publishing?', 'This updates the persistent publication setting.')) return; try { const data = await action('/api/admin/settings',{website_enabled:settings.website_enabled === 'false'}); fillSettings(data.settings); notice('Publishing controls saved'); } catch (error) { notice(error.message,'err'); } };
$('trainBtn').onclick = async () => { const notes = $('trainNotes').value.trim(); if (!notes) return notice('Enter a reviewed operating instruction.','err'); $('trainBtn').disabled = true; try { await action('/api/admin/training',{agent_id:$('trainAgent').value,event_type:'knowledge_update',notes}); $('trainNotes').value = ''; notice('Knowledge event recorded'); } catch (error) { notice(error.message,'err'); } finally { applyCapabilities(); } };
$('factBtn').onclick = async () => { if (mutationBusy) return; mutationBusy = true; applyCapabilities(); try { const data = await action('/api/fact-check'); notice('Verification precheck completed: ' + (data.checked || 0) + ' stories'); await loadOverview(); await loadNews(); } catch (error) { notice(error.message,'err'); } finally { mutationBusy = false; applyCapabilities(); } };
$('activityRefresh').onclick = loadActivity;
$('menuToggle').onclick = () => { const open = !$('sidebar').classList.contains('open'); closeMenu(); if (open) { $('sidebar').inert = false; $('sidebar').classList.add('open'); $('sidebarBackdrop').classList.remove('hidden'); $('menuToggle').setAttribute('aria-expanded','true'); document.body.style.overflow = 'hidden'; $('commandOpen').focus(); } };
$('sidebarBackdrop').onclick = () => closeMenu(true);
$('inspectorClose').onclick = () => $('inspector').close();
$('inspector').addEventListener('close',() => inspectorSequence++);
$('commandOpen').onclick = openCommands;
$('commandClose').onclick = () => $('commandDialog').close();
$('commandInput').oninput = renderCommands;
$('confirmCancel').onclick = () => $('confirmDialog').close('no');
$('confirmProceed').onclick = () => $('confirmDialog').close('yes');
document.addEventListener('click',event => {
  const command = event.target.closest('[data-command]'); if (command) { $('commandDialog').close(); go(command.dataset.command); return; }
  const view = event.target.closest('[data-view]'); if (view) go(view.dataset.view);
  const story = event.target.closest('[data-inspect]'); if (story) inspectStory(Number(story.dataset.inspect));
  const actionButton = event.target.closest('[data-news]'); if (actionButton) newsAction(actionButton.dataset.news,Number(actionButton.dataset.id));
  const bulk = event.target.closest('[data-bulk]'); if (bulk) bulkAction(bulk.dataset.bulk);
  const filter = event.target.closest('[data-queue]'); if (filter && !filter.disabled) { queue = filter.dataset.queue; $('status').value = ['pending','published'].includes(queue) ? queue : 'all'; $('review').value = queue === 'needs_review' ? 'needs_review' : 'all'; document.querySelectorAll('[data-queue]').forEach(node => node.classList.toggle('active',node === filter)); loadNews(true); }
  const source = event.target.closest('[data-source-filter]'); if (source) { $('resetFilters').click(); $('source').value = source.dataset.sourceFilter; go('news'); }
});
document.addEventListener('change',event => { if (event.target.matches('[data-select]')) { const id = Number(event.target.dataset.select); event.target.checked ? selected.add(id) : selected.delete(id); updateSelection(); } });
document.addEventListener('keydown',event => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); if (!$('commandDialog').open) openCommands(); }
  if (event.key === 'Escape') closeMenu(true);
  if ($('commandDialog').open && ['ArrowDown','ArrowUp','Enter'].includes(event.key)) {
    const buttons = [...document.querySelectorAll('[data-command]')]; if (!buttons.length) return;
    event.preventDefault(); if (event.key === 'Enter') buttons[commandIndex]?.click(); else { commandIndex = (commandIndex + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length; buttons.forEach((node,index) => node.setAttribute('aria-selected',String(index === commandIndex))); buttons[commandIndex].scrollIntoView({block:'nearest'}); }
  }
  if (event.key === 'Tab' && $('sidebar').classList.contains('open') && matchMedia('(max-width:800px)').matches) {
    const controls = [...$('sidebar').querySelectorAll('a,button')].filter(node => !node.disabled), first = controls[0], last = controls.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }
});
function setTheme(theme) { document.documentElement.dataset.adminTheme = theme; $('themeToggle').setAttribute('aria-label',theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'); }
try { const theme = localStorage.getItem('ph-admin-theme'); if (theme === 'dark' || theme === 'light') setTheme(theme); } catch { /* Display preference storage is optional. */ }
$('themeToggle').onclick = () => { const theme = document.documentElement.dataset.adminTheme === 'dark' ? 'light' : 'dark'; setTheme(theme); try { localStorage.setItem('ph-admin-theme',theme); } catch {} };
window.addEventListener('hashchange',() => { if (workspace) go(location.hash.slice(1),false); });
matchMedia('(max-width:800px)').addEventListener('change',() => closeMenu());
document.addEventListener('DOMContentLoaded',async () => { closeMenu(); try { const data = await api('/api/admin/me'); if (data.authenticated) await signedIn(data); } catch (error) { $('loginErr').textContent = 'Session check unavailable. You can still try signing in.'; } });
