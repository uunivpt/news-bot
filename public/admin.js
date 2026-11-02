/* Private workspace state stays in memory. Only the display theme is persisted. */
'use strict';
const $ = id => document.getElementById(id);
const arr = value => Array.isArray(value) ? value : [];
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const views = {overview:'Overview',news:'Newsroom',sources:'Source coverage',operations:'Agent operations',upgrade:'Intelligence & QA',activity:'Activity',system:'System status',settings:'Settings',team:'Team & roles',events:'Events & sources',studio:'Marathi Studio',readiness:'AdSense readiness'};
let manualRequestId='', manualBusy=false;
let csrf = '', settings = {}, workspace = null, rows = [], currentView = 'overview';
let pageNumber = 1, pageTotal = 0, queue = 'all', selected = new Set(), visibleRows = [];
let deliveryController = null;
let workspacePromise = null, workspaceController = null, workspaceSequence = 0, newsController = null, newsSequence = 0, inspectorSequence = 0;
let newsTimer, liveTimer, noticeTimer, loginBusy = false, mutationBusy = false, sessionVersion = 0;
const pending = new Map();

function notice(message, type = 'ok') {
  $('notice').textContent = message;
  $('notice').className = 'notice ' + type;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => $('notice').classList.add('hidden'), 5500);
}
function showLogin(message = '') {
  window.Editorial?.reset();
  clearStaffCredentials();
  $('teamMembers').replaceChildren();
  manualRequestId='';manualBusy=false;
  sessionVersion++;
  closeMenu();
  clearInterval(liveTimer); liveTimer = null;
  deliveryController?.abort(); deliveryController = null; mutationBusy = false;
  workspaceController?.abort(); workspaceSequence++; newsController?.abort(); inspectorSequence++; newsSequence++;
  pending.clear(); workspacePromise = null;
  for (const id of ['inspector','commandDialog','confirmDialog']) if ($(id).open) $(id).close();
  workspace = null; rows = []; visibleRows = []; settings = {}; selected.clear(); csrf = '';
  for (const id of ['newsList','recentStories','activityList','inspectorBody','agents','errors','overviewMetrics','health','attentionList','sourceMetrics','sourceChart','sourceTable','qualityChart','deskChart','opsTotals','opsPhases','quality','advancedReport','upgradeMetrics','upgradeAlerts','upgradeScores','upgradeSources','upgradeEvents','upgradeResources','upgradeHistory','upgradeRegression','sessionDetails','systemChecks']) $(id).replaceChildren();
  $('shell').classList.add('hidden'); $('login').classList.remove('hidden');
  $('loginErr').textContent = message;
}
async function api(url, options = {}) {
  const method = options.method || 'GET';
  const request = async () => {
    const version = sessionVersion;
    const {signal, ...requestOptions} = options;
    const deadline = AbortSignal.timeout(30000);
    const requestSignal = signal ? AbortSignal.any([signal,deadline]) : deadline;
    // Retry a transient read once. Mutations are never automatically repeated.
    for (let attempt = 0; attempt < 2; attempt++) {
      if (requestSignal.aborted) throw requestSignal.reason || new DOMException('Request cancelled','AbortError');
      if (version !== sessionVersion) throw new DOMException('Session changed','AbortError');
      try {
        const response = await fetch(url, {credentials:'same-origin', cache:'no-store', ...requestOptions, signal:requestSignal});
        let data = {};
        try { data = await response.json(); } catch {
          if (response.ok) throw new Error('Admin service returned an invalid response. Please retry when the phone admin is available.');
        }
        if (version !== sessionVersion) throw new DOMException('Session changed','AbortError');
        if (!response.ok) {
          if (response.status === 401 && !url.endsWith('/login')) showLogin('Your session has ended. Please sign in again.');
          const error = new Error(data?.error || `Request failed (${response.status})`);
          error.status = response.status;
          throw error;
        }
        if (!data || typeof data !== 'object') throw new Error('Admin service returned an invalid response. Please retry.');
        return data;
      } catch (error) {
        const retryable = error.name === 'TypeError' || [502,503,504].includes(error.status);
        if (method !== 'GET' || attempt || !retryable || requestSignal.aborted || version !== sessionVersion || error.name === 'AbortError') throw error;
        await new Promise(resolve => setTimeout(resolve,250));
      }
    }
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
  if (!views[view] || (workspace && !canView(view))) view = 'overview';
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
  if (view === 'team') loadTeam();
  if (['events','studio','readiness'].includes(view)) window.Editorial?.load(view);
  window.scrollTo({top:0,behavior:'instant'});
}
function powerLabel(permission) {
  return ({'news.read':'Read newsroom','news.create':'Create drafts','news.edit':'Edit stories','news.process':'Process source material','news.publish':'Verify and publish','news.reject':'Reject stories','reports.read':'Download diagnosis reports','operations.read':'View operations and quality','settings.manage':'Manage publishing settings','training.manage':'Record operating guidance','activity.read':'Read audit history','users.manage':'Manage staff and roles'})[permission] || permission;
}
function can(permission) {
  if (!workspace || workspace.access.read_only) return false;
  const powers = workspace.access.permissions;
  return Array.isArray(powers) ? powers.includes(permission) : true;
}
function canView(view) {
  if (workspace?.access.read_only) return view !== 'team';
  return !({readiness:'reports.read',team:'users.manage',settings:'settings.manage',activity:'activity.read',operations:'operations.read',upgrade:'operations.read'}[view]) || can({readiness:'reports.read',team:'users.manage',settings:'settings.manage',activity:'activity.read',operations:'operations.read',upgrade:'operations.read'}[view]);
}
function controlPermission(node) {
  if (node.dataset.permission) return node.dataset.permission;
  if (node.dataset.bulk) return node.dataset.bulk === 'reject' ? 'news.reject' : 'news.publish';
  if (['factBtn'].includes(node.id)) return 'news.publish';
  if (['websiteEnabled','saveSettings','siteToggle'].includes(node.id)) return 'settings.manage';
  if (['trainAgent','trainNotes','trainBtn'].includes(node.id)) return 'training.manage';
  if (node.id === 'manualComposer') return 'news.create';
  return 'news.read';
}
function clearStaffCredentials() {
  $('staffLogin').value = ''; $('staffPassword').value = '';
  if ($('staffCredentials').open) $('staffCredentials').close();
}
function showStaffCredentials(data) {
  $('staffLogin').value = data.username; $('staffPassword').value = data.password;
  $('staffCredentials').showModal();
}
let teamRoles = [];
async function loadTeam() {
  if (!can('users.manage')) return;
  try {
    const data = await api('/api/admin/users');
    teamRoles = data.roles;
    $('hireRole').innerHTML = '<option value="">Select a role…</option>' + teamRoles.map(role => `<option value="${esc(role.id)}">${esc(role.name)}</option>`).join('');
    $('hirePowers').textContent = 'Choose a job to see exactly which actions it permits.';
    $('teamMembers').innerHTML = '<table class="table"><thead><tr><th>Username</th><th>Role / powers</th><th>Actions</th></tr></thead><tbody>' + data.users.map(user => `<tr><td>${esc(user.username)}</td><td>${user.protected ? '<b>Main owner · all permissions</b>' : `<select class="field" data-staff-role="${esc(user.username)}">${!user.enabled ? '<option value="">Disabled · select a role to restore</option>' : ''}${teamRoles.map(role => `<option value="${esc(role.id)}" ${user.role === role.id ? 'selected' : ''}>${esc(role.name)}</option>`).join('')}</select>`}<small>${esc(user.permissions.map(powerLabel).join(', ') || 'No access')}</small></td><td>${user.protected ? 'Protected owner' : `<button class="btn small" data-policy-user="${esc(user.username)}">Exact permissions</button> <button class="btn small" data-staff="role" data-user="${esc(user.username)}">Save role</button> <button class="btn small" data-staff="reset_password" data-user="${esc(user.username)}">Generate new password</button> <button class="btn small danger" data-staff="disable" data-user="${esc(user.username)}" ${!user.enabled ? 'disabled' : ''}>Disable access</button>`}</td></tr>`).join('') + '</tbody></table>';
  } catch (error) { notice(error.message,'err'); }
}
async function downloadDiagnosis() {
  if (!can('reports.read')) return;
  const button = $('downloadDiagnostics'), version = sessionVersion;
  button.disabled = true; button.textContent = 'Preparing live diagnosis…';
  try {
    const response = await fetch('/api/admin/diagnostics.pdf?days=' + encodeURIComponent($('diagnosisPeriod').value),{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(30000)});
    if (!response.ok) { const error = await response.json().catch(() => ({})); throw new Error(error.error || 'Diagnosis download failed'); }
    if (!(response.headers.get('Content-Type') || '').startsWith('application/pdf')) throw new Error('The diagnosis service did not return a PDF.');
    const blob = await response.blob();
    if (version !== sessionVersion) return;
    download('politicshub-diagnosis-' + new Date().toISOString().slice(0,10) + '.pdf',blob,'application/pdf');
    notice('Fresh diagnosis downloaded. Full database totals and source inventory; recent history is scoped in the PDF.');
  } catch (error) { notice(error.message,'err'); }
  finally { button.textContent = '↓ Download diagnosis PDF'; button.disabled = !can('reports.read'); }
}

function applyCapabilities() {
  const writable = !!workspace && !workspace.access.read_only;
  document.querySelectorAll('[data-write]').forEach(node => { node.disabled = !writable || !can(controlPermission(node)) || mutationBusy; node.title = writable ? '' : workspace?.data_origin === 'termux_github' ? 'Edits run on the Termux phone, not on the public website' : 'Requires a live database and owner session'; });
  document.querySelectorAll('[data-view]').forEach(node => { node.hidden = !canView(node.dataset.view); });
  $('downloadDiagnostics').disabled = !can('reports.read');
  $('publishManual').disabled = !can('news.create') || !can('news.publish') || mutationBusy;
  $('saveManual').closest('.panel').hidden = !can('news.create');
  $('status').disabled = !writable; $('review').disabled = !writable;
  $('settingsState').textContent = writable ? '' : workspace?.data_origin === 'termux_github' ? 'Read-only website. Review and approve stories using the local Termux workflow.' : 'Read-only. Publishing controls require a live database owner session.';
}
function renderWorkspace() {
  const data = workspace, health = data.health, stats = data.stats, sample = data.coverage.sample_size;
  const githubOnly = data.data_origin === 'termux_github' && data.mode !== 'live';
  rows = data.stories;
  settings = data.settings || {};
  $('userName').textContent = data.access.username;
  $('avatar').textContent = data.access.username.slice(0,1).toUpperCase();
  $('sessionRole').textContent = data.access.scope === 'recovery' ? 'Recovery · read-only' : data.access.read_only ? (githubOnly ? 'Owner · GitHub feed view' : 'Owner · database unavailable') : (data.access.role || 'Administrator') + ' session';
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
  $('health').innerHTML = `<div class="health-row"><div><b>${githubOnly ? 'News storage' : 'Database'}</b><small>${githubOnly ? 'PostgreSQL is local to Termux; phone health is not checked here' : health.database === 'connected' ? 'Connection available' : 'Persistent services are paused'}</small></div><span class="pill ${health.database === 'connected' ? 'green' : 'amber'}">${githubOnly ? 'Termux' : esc(health.database)}</span></div><div class="health-row"><div><b>Story delivery</b><small>Newest report: ${esc(date(health.latest_published_at))}</small></div><span class="pill ${health.latest_age_seconds != null && health.latest_age_seconds < 86400 ? 'green' : 'amber'}">${esc(age(health.latest_age_seconds))}</span></div><div class="health-row"><div><b>Editorial permissions</b><small>${data.access.read_only ? 'Changes are disabled server-side' : 'Permissions follow your assigned role'}</small></div><span class="pill ${data.access.read_only ? 'amber' : 'green'}">${data.access.read_only ? 'Read-only' : esc(data.access.role || 'Administrator')}</span></div>`;
  $('attentionList').innerHTML = data.coverage.quality.slice(0,4).map(item => `<div class="attention-row"><span>${esc(item.name)}</span><b>${number(item.count)} stories</b></div>`).join('') || '<p class="muted">No completeness flags in the loaded sample.</p>';
  const synced = new Date(data.generated_at).toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit'});
  $('footerSync').textContent = `Updated ${synced} IST · Refreshes every 60s on overview`;
  $('todayLabel').textContent = new Date().toLocaleDateString('en-IN',{timeZone:'Asia/Kolkata',weekday:'short',day:'numeric',month:'long',year:'numeric'});
  fillOptions('category',data.coverage.categories,'All desks');
  fillOptions('source',sourceOptions(),'All sources');
  applyCapabilities();
  if (!canView(currentView)) go('overview');
  if (currentView === 'sources') renderSources();
  if (currentView === 'system') renderSystem();
}
function fillOptions(id, items, label) {
  const value = $(id).value;
  $(id).innerHTML = `<option value="all">${label}</option>` + arr(items).map(item => `<option value="${esc(item.name)}">${esc(item.name)}</option>`).join('');
  if ([...$(id).options].some(option => option.value === value)) $(id).value = value;
}
function sourceOptions() {
  const items = [...arr(workspace?.source_inventory?.items),...arr(workspace?.coverage?.sources)];
  return [...new Map(items.map(item => [item.name,item])).values()].sort((a,b) => a.name.localeCompare(b.name));
}
async function loadOverview(silent = false, {fresh = false} = {}) {
  if (workspacePromise && !fresh) return workspacePromise;
  if (fresh) workspaceController?.abort();
  const version = sessionVersion, sequence = ++workspaceSequence;
  const controller = new AbortController(); workspaceController = controller;
  $('refresh').disabled = true;
  const promise = (async () => {
    try {
      const data = await api('/api/admin/workspace',{signal:controller.signal});
      if (version !== sessionVersion || sequence !== workspaceSequence || $('shell').classList.contains('hidden')) return null;
      workspace = data; renderWorkspace(); return data;
    } catch (error) {
      if (version === sessionVersion && sequence === workspaceSequence && error.status !== 401 && error.name !== 'AbortError') {
        if (!silent) notice(error.name === 'TimeoutError' ? 'Workspace refresh timed out. Displayed data is retained; retry with Refresh.' : error.message,'err');
        $('connectionBadge').className = 'pill amber'; $('connectionBadge').textContent = 'Refresh failed';
        $('workspaceBanner').classList.remove('hidden');
        $('workspaceBanner').textContent = 'Workspace refresh failed. Displayed data may be out of date. Retry with Refresh.';
      }
      return null;
    } finally {
      if (version === sessionVersion && sequence === workspaceSequence) {
        workspacePromise = null; workspaceController = null; $('refresh').disabled = false;
      }
    }
  })();
  workspacePromise = promise;
  return promise;
}
function filteredSnapshot() {
  const query = $('search').value.trim().toLowerCase();
  const result = rows.filter(row => (!query || [row.id,row.news_number,row.title,row.summary,row.source_name].join(' ').toLowerCase().includes(query)) && ($('category').value === 'all' || row.category === $('category').value) && ($('source').value === 'all' || row.source_name === $('source').value) && ($('status').value === 'all' || row.status === $('status').value) && (queue !== 'quality' || row.quality_flags.length));
  const sort = $('sort').value;
  return result.sort((a,b) => sort === 'oldest' ? (a.timestamp || 0)-(b.timestamp || 0) : sort === 'views' ? Number(b.view_count || 0)-Number(a.view_count || 0) : sort === 'quality' ? b.quality_flags.length-a.quality_flags.length : (b.timestamp || 0)-(a.timestamp || 0));
}
function storyActions(row) {
  if(row.archived && !workspace?.access.read_only) return `<button class="btn" data-inspect="${Number(row.id)}">Inspect saved article</button><button class="btn" data-restore-archive="${esc(row.news_number)}">Restore for editing</button>`;
  if (workspace?.access.read_only) return `<button class="btn" data-inspect="${Number(row.id)}">Inspect ↗</button>`;
  const id = Number(row.id);
  return `<button class="btn" data-inspect="${id}">Inspect</button><button class="btn" data-studio="${id}">Studio</button>` + (!row.article_available ? `<button class="btn" data-permission="news.process" data-news="process" data-id="${id}" data-write>Process</button>` : '') + (row.status === 'pending' ? `<button class="btn" data-permission="news.publish" data-news="approve" data-id="${id}" data-write>Verify &amp; publish</button>` : '') + (row.status !== 'rejected' ? `<button class="btn danger" data-permission="news.reject" data-news="reject" data-id="${id}" data-write>Reject</button>` : '');
}
function renderNews(list, total) {
  visibleRows = list; pageTotal = total;
  $('newsList').innerHTML = list.map(row => `<article class="story"><input type="checkbox" data-select="${Number(row.id)}" aria-label="Select story ${Number(row.id)}" ${selected.has(Number(row.id)) ? 'checked' : ''}><div class="story-content"><div class="story-tags"><span class="desk-tag">${esc(row.category || 'General')}</span><span class="pill ${row.status === 'published' ? 'green' : 'amber'}">${esc(row.status)}</span><span class="quality-tag">${row.quality_flags.length ? row.quality_flags.length+' completeness flags' : 'No completeness flags'}</span></div><h3><button class="story-title" data-inspect="${Number(row.id)}">${esc(row.title)}</button></h3><div class="meta">News No. ${esc(row.news_number || row.id)} · ${esc(row.source_name || 'Unknown source')} · ${esc(date(row.timestamp ? row.timestamp * 1000 : row.published_at))}</div><p>${esc(row.summary)}</p></div><div class="actions">${storyActions(row)}</div></article>`).join('') || empty('No matching stories','Try another search or reset your filters.');
  $('newsCount').textContent = `${number(total)} matching ${total === 1 ? 'story' : 'stories'}`;
  $('newsScope').textContent = workspace.mode === 'snapshot' ? `Read-only search across ${rows.length} saved public reports. Private queues require the database.` : 'Search the full database. Showing 25 stories per page.';
  $('exportNews').textContent = workspace.mode === 'snapshot' ? '↓ Export filtered CSV' : '↓ Export page CSV';
  $('prevPage').disabled = pageNumber <= 1;
  $('nextPage').disabled = pageNumber * 25 >= total;
  $('pageInfo').textContent = `Page ${pageNumber} of ${Math.max(1,Math.ceil(total/25))}`;
  updateSelection();
  applyCapabilities();
}
function newsNumberInput(value) {
  const text=String(value || '').trim().replace(/^(?:News\s*No\.?\s*[:#]?\s*|#)/i,'');
  if (/^\d{9,16}$/.test(text)) return text;
  try { const url=new URL(text); return /^https?:$/.test(url.protocol) ? (url.pathname.match(/\/(\d{9,16})(?:-[^/]*)?\/?$/)?.[1] || '') : ''; }
  catch { return ''; }
}
async function loadNews(reset = false, {silent = false} = {}) {
  if (!workspace) return false;
  if (reset) { pageNumber = 1; selected.clear(); }
  const sequence = ++newsSequence;
  newsController?.abort();
  newsController = new AbortController();
  const signal=newsController.signal;
  const numberQuery=newsNumberInput($('search').value);
  $('newsList').setAttribute('aria-busy','true');
  try {
    if (numberQuery) {
      let article;
      try { article=await api('/api/news/'+encodeURIComponent(numberQuery),{signal}); }
      catch(error) { if (error.status !== 404) throw error; }
      if (sequence !== newsSequence || signal.aborted) return false;
      if (article?.id) {
        const stamp=Date.parse(article.published_at_iso || article.published_at_site || article.published_at);
        const story={...article,news_number:String(article.news_number || numberQuery),
          summary:article.bot_summary || article.summary || '', quality_flags:[],
          article_available:!!(article.article || article.bot_article), timestamp:Number.isFinite(stamp)?stamp/1000:null,
          status:'published',fact_check_status:null,archived:true};
        renderNews([story],1);
        $('newsScope').textContent='Exact news number match across the public archive. Queue and desk filters do not hide this result.';
        // Public identity resolution must work even while the phone runs an
        // older queue implementation or the article is absent from its database.
        if (!workspace.access.read_only) {
          try {
            const draft=await api('/api/admin/story/'+encodeURIComponent(story.id),{signal});
            if(sequence !== newsSequence || signal.aborted)return false;
            if(String(draft.id)===String(story.id)) {
              Object.assign(story,draft,{archived:false,status:draft.status || 'unknown'});
              renderNews([story],1);
              $('newsScope').textContent='Exact news number match. The connected editor contains this story.';
            }
          } catch(error) {
            if(sequence !== newsSequence || signal.aborted || error.status===401)return false;
            $('newsScope').textContent='Public article found. Its saved text is available to inspect; the connected editor has not confirmed an editable copy.';
          }
        }
        return true;
      }
    }
    if (workspace.mode === 'snapshot') { const result = filteredSnapshot(); renderNews(result.slice((pageNumber-1)*25,pageNumber*25),result.length); return true; }
    const query = new URLSearchParams({page:pageNumber,search:numberQuery || $('search').value.trim(),category:$('category').value,source:$('source').value,status:$('status').value,review:$('review').value,sort:$('sort').value,quality:queue === 'quality' ? '1' : '0'});
    const data = await api('/api/admin/stories?' + query,{signal});
    if (sequence === newsSequence) { renderNews(data.stories,data.total); return true; }
    return false;
  } catch (error) {
    if (sequence === newsSequence && error.name !== 'AbortError') {
      if (!silent) notice(error.name === 'TimeoutError' ? 'News refresh timed out. Displayed stories are retained.' : error.message,'err');
      $('newsScope').textContent = 'News refresh failed. Displayed stories may be out of date; use Refresh to retry.';
    }
    return false;
  } finally { if (sequence === newsSequence) $('newsList').removeAttribute('aria-busy'); }
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
function markPublished(id) {
  const previous = [...visibleRows,...rows].find(row => Number(row.id) === id)?.status;
  for (const list of [rows,visibleRows]) for (const row of list) if (Number(row.id) === id) {
    row.status = 'published'; row.fact_check_status = 'reviewed';
  }
  selected.delete(id);
  if (workspace && previous && previous !== 'published') {
    if (workspace.stats.pending != null && previous === 'pending') workspace.stats.pending = Math.max(0,workspace.stats.pending-1);
    if (workspace.stats.published != null) workspace.stats.published++;
  }
  if (currentView === 'news') {
    const statusFilter = $('status').value, reviewFilter = $('review').value;
    const publishedExcluded = (statusFilter !== 'all' && statusFilter !== 'published') || (reviewFilter !== 'all' && reviewFilter !== 'reviewed');
    const list = publishedExcluded ? visibleRows.filter(row => Number(row.id) !== id) : visibleRows;
    renderNews(list,Math.max(0,pageTotal-(publishedExcluded && previous !== 'published' ? 1 : 0)));
  }
}
async function refreshAfterMutation() {
  const checks = [loadOverview(true,{fresh:true})];
  if (currentView === 'news') checks.push(loadNews(false,{silent:true}));
  const results = await Promise.allSettled(checks);
  return results.every(result => result.status === 'fulfilled' && !!result.value);
}
function publicationMessage(result) {
  const state = result.public_delivery?.state;
  if (state === 'synced') return 'Story published on the website.';
  if (result.public_delivery?.configured === false) return 'Story published on the phone. Website sync is not configured.';
  if (state === 'queued' || state === 'verifying') return 'Publication saved. Checking that the story is visible on the website…';
  if (state === 'not_configured') return 'Story published on the phone. Website sync is not configured.';
  if (state === 'failed') return 'Story published on the phone. Website sync failed; publication is saved.';
  return 'Story published.';
}
async function waitForPublicationDelivery(id, result, version) {
  if (!['queued','verifying'].includes(result.public_delivery?.state) || result.public_delivery.configured !== true) return result;
  const controller = new AbortController(); deliveryController = controller;
  const signal = AbortSignal.any([controller.signal,AbortSignal.timeout(20000)]);
  const end = Date.now()+20000;
  try {
    while (Date.now() < end && !signal.aborted && version === sessionVersion) {
      await new Promise(resolve => setTimeout(resolve,2000));
      if (signal.aborted || version !== sessionVersion) break;
      try {
        const response = await api('/api/admin/story/'+id+'/delivery',{signal});
        if (version !== sessionVersion) break;
        const delivery = response.public_delivery || response;
        result = {...result,public_delivery:{...result.public_delivery,...delivery}};
        if (['synced','failed','not_configured','not_queued'].includes(delivery.state)) return result;
      } catch (error) {
        if (signal.aborted || error.status === 401 || version !== sessionVersion) break;
        // Publication is saved. A failed status read never repeats the write.
      }
    }
  } finally { if (deliveryController === controller) deliveryController = null; }
  return result;
}
function showPublicationNotice(message, result, type = 'ok') {
  notice(message,type);
  if (result.public_delivery?.state !== 'synced') return;
  try { const channel=new BroadcastChannel('politicshub-public-news'); channel.postMessage({type:'published'});channel.close(); } catch {}
  const raw = result.public_delivery.public_url || result.public_url || result.url;
  if (!raw) return;
  let url;
  try { url = new URL(raw,location.origin); } catch { return; }
  if (!['https://www.politicshub.in',location.origin].includes(url.origin)) return;
  const link = document.createElement('a');
  link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.textContent = 'View article ↗';
  $('notice').append(' ',link);
  clearTimeout(noticeTimer); noticeTimer = setTimeout(() => $('notice').classList.add('hidden'),15000);
}
async function newsAction(kind, id) {
  if (mutationBusy || !workspace || workspace.access.read_only || !['process','approve','publish','reject'].includes(kind)) return;
  if (kind === 'reject' && !await confirmAction('Reject this story?',`Story #${id}. This changes its publication state in the live database.`)) return;
  const publication = kind === 'approve' || kind === 'publish', version = sessionVersion;
  const row = [...visibleRows,...rows].find(item => Number(item.id) === id);
  const payload = row?.revision ? {revision:row.revision} : {};
  mutationBusy = true; applyCapabilities();
  try {
    let result = await action(`/api/news/${id}/${publication ? 'approve' : kind}`,payload);
    if (publication && (result.ok !== true || result.status !== 'published')) throw new Error('Publication was not confirmed by the server. Refresh the story before retrying.');
    if (publication) {
      markPublished(id);
      notice(publicationMessage(result));
      result = await waitForPublicationDelivery(id,result,version);
      if (version !== sessionVersion) return;
    }
    const message = publication ? publicationMessage(result) : kind === 'process' ? 'Story processed.' : 'Story rejected.';
    if (publication) showPublicationNotice(message,result); else notice(message);
    const refreshed = await refreshAfterMutation();
    if (version !== sessionVersion) return;
    if (!refreshed) {
      const warning = message + ' Latest lists could not be refreshed; use Refresh.';
      if (publication) showPublicationNotice(warning,result,'warn'); else notice(warning,'warn');
    }
  } catch (error) { if (version === sessionVersion && error.name !== 'AbortError') notice(error.message,'err'); }
  finally { if (version === sessionVersion) { mutationBusy = false; applyCapabilities(); } }
}
async function bulkAction(kind) {
  if (mutationBusy || !workspace || workspace.access.read_only || !selected.size || !['approve','publish','reject'].includes(kind)) return;
  if (selected.size > 10) return notice('Select at most 10 stories per action.','err');
  const ids = [...selected], publication = kind === 'approve' || kind === 'publish', version = sessionVersion;
  if (!publication && !await confirmAction(`Reject ${ids.length} stories?`,'Actions run sequentially. Processing stops at the first failure; completed changes stay saved.')) return;
  mutationBusy = true; applyCapabilities();
  let completed = 0, failure = '', websitePending = false;
  try {
    for (const id of ids) {
      if (version !== sessionVersion) return;
      const row = [...visibleRows,...rows].find(item => Number(item.id) === id);
      const result = await action(`/api/news/${id}/${publication ? 'approve' : kind}`,row?.revision ? {revision:row.revision} : {});
      if (publication && (result.ok !== true || result.status !== 'published')) throw new Error(`Publication of story #${id} was not confirmed. Refresh before retrying.`);
      if (publication) {
        markPublished(id);
        if (result.public_delivery && result.public_delivery.state !== 'synced') websitePending = true;
      } else selected.delete(id);
      completed++;
    }
  } catch (error) { failure = error.message; }
  finally {
    if (version !== sessionVersion) return;
    const refreshed = await refreshAfterMutation();
    if (version !== sessionVersion) return;
    mutationBusy = false; applyCapabilities();
    let message = `${completed} ${completed === 1 ? 'story' : 'stories'} ${publication ? 'published' : 'rejected'}.`;
    if (websitePending) message += ' Website sync is pending for some stories.';
    if (failure) notice(message + ' Stopped: ' + failure,'err');
    else if (!refreshed) notice(message + ' Latest lists could not be refreshed; use Refresh.','warn');
    else notice(message);
  }
}
async function inspectStory(id) {
  const row = [...visibleRows,...rows].find(item => Number(item.id) === id);
  if (!row) return;
  const sequence = ++inspectorSequence, url = safeUrl(row.url);
  $('inspectorBody').innerHTML = `<span class="desk-tag">${esc(row.category || 'General')} / News No. ${esc(row.news_number || id)}</span><h2 id="inspectorTitle">${esc(row.title)}</h2><span class="pill ${row.status === 'published' ? 'green' : 'amber'}">${esc(row.status)}</span><dl class="detail-grid">${detail('Source',row.source_name || 'Unknown')}${detail('Published',date(row.timestamp ? row.timestamp*1000 : row.published_at))}${detail('Review',row.fact_check_status || 'Not available in public snapshot')}${detail('Recorded views',number(row.view_count))}</dl><p class="inspector-summary">${esc(row.summary || 'No summary available.')}</p><div class="quality-flags">${row.quality_flags.map(flag => `<span class="pill amber">${esc(flag)}</span>`).join('')}</div><div class="actions">${url ? `<a class="btn" target="_blank" rel="noopener noreferrer" href="${esc(url)}">Open original source ↗</a>` : ''}<button id="loadArticle" class="btn">Load article text</button><button id="copySource" class="btn" ${url ? '' : 'disabled'}>Copy source URL</button></div><div id="inspectorArticle" class="article-body"></div>`;
  if (!$('inspector').open) $('inspector').showModal();
  $('loadArticle').onclick = async () => {
    $('loadArticle').disabled = true; $('inspectorArticle').textContent = 'Loading article…';
    try { const data = await api((workspace && !workspace.access.read_only && !row.archived ? '/api/admin/story/' + id + '/article' : '/api/news/' + id)); if (sequence !== inspectorSequence || !$('inspector').open) return; $('inspectorArticle').textContent = data.article || data.bot_article || data.summary || 'No article text available.'; }
    catch (error) { if (sequence === inspectorSequence && $('inspector').open) { $('inspectorArticle').textContent = error.message; $('loadArticle').disabled = false; } }
  };
  $('copySource').onclick = async () => { try { await navigator.clipboard.writeText(url); notice('Source link copied'); } catch { notice('Clipboard unavailable. Open the original source link.','err'); } };
  if (can('news.edit') && !row.archived) {
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
      try { await action('/api/news/' + id + '/edit',{title:$('editTitle').value.trim(),category:$('editCategory').value,summary:$('editSummary').value.trim(),bot_summary:$('editSummary').value.trim()},{'If-Match':revision}); $('inspector').close(); notice('Story changes saved'); if (!await refreshAfterMutation()) notice('Story changes saved. Latest lists could not be refreshed; use Refresh.','warn'); }
      catch (error) { notice(error.message,'err'); }
      finally { button.disabled = false; }
    };
  }
}
function renderSources() {
  if (!workspace) return;
  const inventory = workspace.source_inventory;
  const complete = !!inventory && Array.isArray(inventory.items);
  const scope = complete ? inventory.scope : 'sample';
  const database = scope === 'database', snapshot = scope === 'snapshot';
  const countScope = database ? workspace.access?.policy ? 'Your accessible database stories' : 'Entire database' : snapshot ? 'Saved public snapshot only' : scope === 'sample' ? 'Loaded sample only' : 'Database counts unavailable';
  const items = complete ? inventory.items : arr(workspace.coverage.sources).map(source => ({name:source.name,story_count:source.count,collection_status:'unknown'}));
  const total = complete ? inventory.total_stories : workspace.coverage.sample_size;
  const represented = complete ? inventory.represented_count : items.length;
  $('sourceMetrics').innerHTML = metric('Configured publishers',complete ? number(inventory.configured_count) : 'Unavailable','Full source configuration') + metric('Publishers with reports',number(represented),countScope) + metric('Stored reports',number(total),countScope) + metric('Desks represented',number(complete ? inventory.categories_count : workspace.coverage.categories.length),countScope);
  const counted = items.filter(item => Number(item.story_count) > 0).sort((a,b) => b.story_count-a.story_count || a.name.localeCompare(b.name));
  $('sourceChart').innerHTML = counted.length ? barChart(counted.map(item => ({name:item.name,count:item.story_count})),total,12) : empty('No stored reports in this scope',scope === 'unavailable' ? 'Database counts could not be loaded.' : 'Configured publishers remain listed in the directory below.');
  $('sourceChartScope').textContent = countScope + ' · largest 12 publishers';
  $('qualityChart').innerHTML = barChart(workspace.coverage.quality,workspace.coverage.sample_size,10);
  $('qualityScope').textContent = `Completeness checks cover ${number(workspace.coverage.sample_size)} loaded stories. Source counts use ${database ? 'the entire database' : snapshot ? 'the saved public snapshot' : 'the scope shown above'}.`;
  const warnings = complete ? arr(inventory.errors).map(error => typeof error === 'string' ? error : error.message || 'Source inventory could not be fully loaded.') : ['Full source inventory is unavailable from this phone version. Update the Termux service to load every configured publisher; the counts below describe only the loaded sample.'];
  if (snapshot) warnings.unshift('Stored report counts cover the saved public snapshot. Private phone collection status is not checked here.');
  $('sourceInventoryNotice').classList.toggle('hidden',!warnings.length);
  $('sourceInventoryNotice').textContent = warnings.join(' ');
  const query = $('sourceSearch').value.trim().toLocaleLowerCase();
  const filtered = items.filter(item => [item.name,item.category,arr(item.categories).join(' '),item.kind,item.url,item.feed_url].join(' ').toLocaleLowerCase().includes(query));
  $('sourceScope').textContent = `${number(filtered.length)} of ${number(items.length)} publishers · ${countScope}`;
  $('sourceTable').innerHTML = filtered.length ? '<table class="table source-directory"><thead><tr><th>Publisher / desk</th><th>Stored reports</th><th>Collection status</th><th>Latest stored report</th><th></th></tr></thead><tbody>' + filtered.map(source => {
    const url = source.url || source.feed_url ? safeUrl(source.url || source.feed_url) : '';
    const categories = arr(source.categories).length ? source.categories.join(', ') : source.category || '';
    const configured = source.configured === false ? 'Stored source · not in current configuration' : source.kind ? String(source.kind).replaceAll('_',' ') : '';
    const status = sourceCollectionStatus(source,scope);
    const latest = source.latest_collected_at || source.latest_published_at;
    const count = source.story_count == null ? 'Unavailable' : number(source.story_count);
    const canFilter = source.story_count != null && Number(source.story_count) > 0;
    return `<tr><td><b>${url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(source.name)} ↗</a>` : esc(source.name)}</b><small>${esc([categories,configured].filter(Boolean).join(' · '))}</small></td><td>${esc(count)}</td><td><span class="pill ${status.tone}">${esc(status.label)}</span>${status.detail ? `<small>${esc(status.detail)}</small>` : ''}</td><td>${esc(latest ? date(latest) : 'Not recorded')}</td><td>${canFilter ? `<button class="text-btn" data-source-filter="${esc(source.name)}">${database ? 'View stories' : 'View saved stories'} ↗</button>` : `<span class="muted">${source.story_count == null ? 'Counts unavailable' : 'No stored stories'}</span>`}</td></tr>`;
  }).join('') + '</tbody></table>' : empty('No matching publishers','Try another publisher name, language or desk.');
}
function sourceCollectionStatus(source,scope) {
  if (source.configured === false) return {label:'Stored source',tone:'',detail:'Not in current configuration'};
  if (source.enabled === false) return {label:'Disabled',tone:'',detail:'Not enabled for collection'};
  const status = source.collection_status;
  if (status === 'external_pipeline') return {label:'Separate pipeline',tone:'',detail:'Collected by the GitHub pipeline'};
  if (scope === 'snapshot' || scope === 'sample') return {label:'Not checked',tone:'',detail:'Phone collection status unavailable'};
  if (status === 'failed') return {label:'Collection failed',tone:'red',detail:String(source.last_error || 'Latest collection attempt failed').slice(0,300)};
  if (status === 'stale') return {label:'Collection overdue',tone:'amber',detail:source.last_success_at ? 'Last successful fetch: ' + date(source.last_success_at) : 'No recent successful fetch recorded'};
  if (status === 'healthy' || status === 'ok') return {label:'Fetch succeeded',tone:'green',detail:source.last_success_at ? date(source.last_success_at) : 'Successful collection recorded'};
  if (status === 'checking') return {label:'Collection in progress',tone:'amber',detail:source.last_attempt_at ? 'Started: ' + date(source.last_attempt_at) : 'Feed check started'};
  if (status === 'awaiting_collection' || status === 'pending' || status === 'never_attempted') return {label:'Awaiting first collection',tone:'amber',detail:'Configured; no collection attempt recorded'};
  if (status === 'not_configured') return {label:'Not configured',tone:'amber',detail:'Collector configuration is incomplete'};
  return {label:'Not recorded',tone:'',detail:source.last_attempt_at ? 'Last attempt: ' + date(source.last_attempt_at) : 'No collection telemetry recorded'};
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
  const githubOnly = workspace.data_origin === 'termux_github' && workspace.mode !== 'live';
  $('systemChecks').innerHTML = (githubOnly ? metric('Primary storage','Termux PostgreSQL','Private phone database; not remotely checked') + metric('Public delivery','GitHub feed','Approved phone exports plus attributed public sources') : metric('Database',health.database === 'connected' ? 'Connected' : 'Unavailable',health.database === 'connected' ? 'Connection verified' : 'Persistent writes are paused') + metric('Data mode',workspace.mode === 'live' ? 'Live' : 'Snapshot',workspace.mode === 'live' ? 'Database-backed newsroom' : 'Saved public reports')) + metric('Latest report age',age(health.latest_age_seconds),date(health.latest_published_at)) + metric('Workspace response',health.response_ms + ' ms','Server processing time, not browser latency');
  $('lastSync').textContent = 'Checked ' + date(workspace.generated_at);
  $('sessionDetails').innerHTML = detail('Signed in as',access.username) + detail('Assigned role',access.role || 'Administrator') + detail('Allowed actions',arr(access.permissions).map(powerLabel).join(', ') || 'Read-only / unavailable') + detail('Access scope',access.scope === 'recovery' ? 'Recovery · read-only' : access.read_only ? 'Writes unavailable' : (access.role || 'Administrator')) + detail('Session expires',access.expires_at ? date(access.expires_at*1000) : 'Legacy session') + detail(githubOnly ? 'Public website edits' : 'Database writes',githubOnly ? 'Disabled — manage locally in Termux' : access.read_only ? 'Blocked' : 'Limited to assigned role; CSRF protection required') + detail('Private data storage','Session cookie only; no admin records in local storage') + detail('Coverage limit',workspace.limits.stories + ' loaded stories; charts describe this sample');
}
function fillSettings(value) { settings = value || {}; $('websiteEnabled').checked = settings.website_enabled !== 'false'; }
async function loadSettings() {
  $('trainAgent').innerHTML = ['trend','manager','research','factcheck','writer','reviewer','hr','automation','publisher','reporting'].map(agent => `<option>${agent}</option>`).join('');
  if (!can('settings.manage')) { $('websiteEnabled').checked = false; applyCapabilities(); return; }
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
  $('commandResults').innerHTML = Object.entries(views).filter(([key,label]) => canView(key) && label.toLowerCase().includes(query)).map(([key,label],index) => `<button class="command-item" data-command="${key}" aria-selected="${index === 0}"><span>${esc(label)}</span><small>Open ↵</small></button>`).join('') || '<p class="muted">No matching sections.</p>';
}
async function signedIn(data) {
  if (!data.authenticated) {
    // A successful password response does not prove the browser retained the
    // phone session cookie. Verify it before opening an empty workspace.
    data = await api('/api/admin/me');
  }
  if (!data.authenticated || !data.csrf_token) {
    throw new Error('Your sign-in session could not be saved. Allow cookies for this site and try again.');
  }
  csrf = data.csrf_token || '';
  $('password').value = ''; $('password').type = 'password'; $('showPassword').textContent = 'Show'; $('showPassword').setAttribute('aria-pressed','false');
  $('login').classList.add('hidden'); $('shell').classList.remove('hidden');
  await loadOverview();
  if (!workspace) {
    showLogin('Your session is valid, but the phone workspace could not be loaded. Check that the phone admin is online and retry.');
    return;
  }
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
$('createArticleForm').addEventListener('input',()=>{if(!manualBusy)manualRequestId='';});
$('createArticleForm').onsubmit = async event => {
 event.preventDefault();
 if(manualBusy)return;
 if (workspace?.access.read_only) return notice('Remote write access is not connected yet. Open the authenticated phone admin or configure the secure bridge.','err');
 const publishNow=event.submitter?.id==='publishManual';
 if(publishNow && !can('news.publish'))return notice('Your role cannot publish news.','err');
 manualBusy=true;manualRequestId=manualRequestId || crypto.randomUUID();
 const button = $('saveManual'); button.disabled = true; $('publishManual').disabled=true;
 try {
  let result = await action('/api/admin/news/create',{...manualPayload(),publish_now:publishNow,request_id:manualRequestId});
  if(publishNow){
   if(result.status!=='published')throw new Error('Publication was not confirmed.');
   result=await waitForPublicationDelivery(result.id,result,sessionVersion);
   $('createArticleForm').reset();manualRequestId='';$('manualMessage').textContent='Article #'+result.id+' · '+publicationMessage(result);
   showPublicationNotice(publicationMessage(result),result);
   await refreshAfterMutation();return;
  }
  $('createArticleForm').reset();manualRequestId=''; $('manualMessage').textContent = 'Draft #' + result.id + ' saved for human review.';
  notice('New article draft #' + result.id + ' saved. Verify before publishing.');
  pageNumber = 1; selected.clear();
  if (!await refreshAfterMutation()) notice('Draft saved. Latest lists could not be refreshed; use Refresh.','warn');
 } catch(error) { $('manualMessage').textContent = error.message; notice(error.message,'err'); }
 finally { manualBusy=false;button.disabled = false; applyCapabilities(); }
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
$('refresh').onclick = async () => { const view = currentView; await loadOverview(false,{fresh:true}); if (workspace && currentView === view) go(view,false); };
$('newsRefresh').onclick = async () => { await Promise.allSettled([loadOverview(false,{fresh:true}),loadNews()]); };
$('search').oninput = () => { newsSequence++; newsController?.abort(); clearTimeout(newsTimer); newsTimer = setTimeout(() => loadNews(true),250); };
$('sourceSearch').oninput = renderSources;
for (const id of ['category','source','status','review','sort']) $(id).onchange = () => loadNews(true);
$('resetFilters').onclick = () => { $('search').value = ''; for (const id of ['category','source','status','review']) $(id).value = 'all'; $('sort').value = 'newest'; queue = 'all'; document.querySelectorAll('[data-queue]').forEach(node => node.classList.toggle('active',node.dataset.queue === 'all')); loadNews(true); };
$('selectAll').onchange = event => { for (const row of visibleRows) event.target.checked ? selected.add(Number(row.id)) : selected.delete(Number(row.id)); renderNews(visibleRows,pageTotal); };
$('clearSelection').onclick = () => { selected.clear(); renderNews(visibleRows,pageTotal); };
$('prevPage').onclick = () => { pageNumber--; loadNews(); };
$('nextPage').onclick = () => { pageNumber++; loadNews(); };
$('exportNews').onclick = exportNews;
$('hireRole').onchange = () => { const role = teamRoles.find(item => item.id === $('hireRole').value); $('hirePowers').textContent = role ? 'Allowed actions: ' + role.permissions.map(powerLabel).join(', ') : 'Select a role.'; };
$('hireForm').onsubmit = async event => {
  event.preventDefault(); if (!can('users.manage')) return;
  $('hireSubmit').disabled = true;
  try { const data = await action('/api/admin/users',{username:$('hireUsername').value.trim(),role:$('hireRole').value}); $('hireForm').reset(); await loadTeam(); showStaffCredentials(data); }
  catch (error) { notice(error.message,'err'); }
  finally { $('hireSubmit').disabled = false; }
};
$('teamMembers').onclick = async event => {
  const button = event.target.closest('[data-staff]'); if (!button || !can('users.manage')) return;
  const username = button.dataset.user, operation = button.dataset.staff;
  const select = [...document.querySelectorAll('[data-staff-role]')].find(node => node.dataset.staffRole === username);
  button.disabled = true;
  try { const data = await action('/api/admin/users/' + encodeURIComponent(username),{operation,role:select?.value}); await loadTeam(); if (data.password) showStaffCredentials(data); else notice('Staff access updated'); }
  catch (error) { notice(error.message,'err'); }
  finally { button.disabled = false; }
};
$('staffCredentialsClose').onclick = clearStaffCredentials;
$('staffCredentials').addEventListener('close',() => { $('staffLogin').value = ''; $('staffPassword').value = ''; });
$('downloadDiagnostics').onclick = downloadDiagnosis;
$('saveSettings').onclick = saveSettings;
$('siteToggle').onclick = async () => { if (!await confirmAction('Change website publishing?', 'This updates the persistent publication setting.')) return; try { const data = await action('/api/admin/settings',{website_enabled:settings.website_enabled === 'false'}); fillSettings(data.settings); notice('Publishing controls saved'); } catch (error) { notice(error.message,'err'); } };
$('trainBtn').onclick = async () => { const notes = $('trainNotes').value.trim(); if (!notes) return notice('Enter a reviewed operating instruction.','err'); $('trainBtn').disabled = true; try { await action('/api/admin/training',{agent_id:$('trainAgent').value,event_type:'knowledge_update',notes}); $('trainNotes').value = ''; notice('Knowledge event recorded'); } catch (error) { notice(error.message,'err'); } finally { applyCapabilities(); } };
$('factBtn').onclick = async () => { if (mutationBusy) return; mutationBusy = true; applyCapabilities(); try { const data = await action('/api/fact-check'); notice('Verification precheck completed: ' + (data.checked || 0) + ' stories'); if (!await refreshAfterMutation()) notice('Source precheck completed. Latest lists could not be refreshed; use Refresh.','warn'); } catch (error) { notice(error.message,'err'); } finally { mutationBusy = false; applyCapabilities(); } };
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
  const source = event.target.closest('[data-source-filter]'); if (source) { $('search').value = ''; for (const id of ['category','status','review']) $(id).value = 'all'; $('sort').value = 'newest'; queue = 'all'; pageNumber = 1; selected.clear(); $('source').value = source.dataset.sourceFilter; go('news'); }
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

document.addEventListener('click',async event=>{
 const button=event.target.closest('[data-restore-archive]'); if(!button)return;
 button.disabled=true;
 try {const result=await action('/api/admin/archive/restore',{number:button.dataset.restoreArchive}); await loadNews(true); notice('Archived story restored. Open its inspector to edit.');}
 catch(error){notice(error.message,'err');}finally{button.disabled=false;}
});
