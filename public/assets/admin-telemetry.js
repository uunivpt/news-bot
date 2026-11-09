// On-demand views of real records and measured storage. No simulated runs.
function telemetryBytes(value) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return 'Unavailable';
  if (value < 1024) return number(value) + ' B';
  if (value < 1048576) return Math.round(value / 1024 * 100) / 100 + ' KB';
  return Math.round(value / 1048576 * 100) / 100 + ' MB';
}
function telemetryEmpty(available, message) {
  return '<div class="empty">' + esc(available === false ? 'Data unavailable. Retry after the newsroom database is reachable.' : message) + '</div>';
}
function telemetryCount(value) { return value == null ? 'Unavailable' : number(value); }
async function loadOps() {
  if (!telemetryAvailable('ops')) return;
  try {
    const [d,r] = await Promise.all([api('/api/admin/operations'),api('/api/admin/report?days=7')]);
    if (!d || !r) return;
    const totals = d.totals || {}, agents = arr(d.agents);
    $('opsTotals').innerHTML = metric('Overall success',pct(totals.success_rate),'Completed agent runs') + metric('Runs',telemetryCount(totals.runs),'Last 7 days') + metric('Failures',telemetryCount(totals.failed),'Last 7 days') + metric('Agents active',agents.filter(x=>x.runs>0).length+'/'+agents.length,'Recent work');
    $('opsPhases').innerHTML = arr(d.phases).map(p=>'<div class="phase"><div><b>Phase '+p.phase+' · '+esc(p.name)+'</b><br><small>'+p.agents+' agents · '+p.runs+' runs · '+p.successes+' successes</small></div><span class="pill '+(p.operational_success_rate!=null&&p.operational_success_rate<80?'red':'green')+'">'+pct(p.operational_success_rate)+'</span></div>').join('');
    $('agents').innerHTML = agents.map(a=>'<div class="agent"><div class="agenttop"><div><div class="agentname">'+esc(a.name)+'</div><div class="role">P'+a.phase+' · '+esc(a.role)+'</div></div><span class="pill">'+telemetryCount(a.current_load)+' in flight</span></div><div class="stats"><span class="pill">'+pct(a.success_rate)+' success</span><span class="pill">'+telemetryCount(a.runs)+' runs</span><span class="pill">'+telemetryCount(a.failed)+' failed</span><span class="pill">'+(a.avg_duration_seconds==null?'—':esc(a.avg_duration_seconds)+'s')+' avg</span></div><div class="bar"><i style="width:'+Math.min(100,a.load_percent||0)+'%"></i></div><div class="role" style="margin-top:4px">Load '+(a.load_percent==null?'—':esc(a.load_percent)+'%')+'</div></div>').join('') || telemetryEmpty(true,'No agent runs recorded yet.');
    $('errors').innerHTML = arr(d.recent_errors).length ? '<table class="table"><tr><th>Bot</th><th>Operation</th><th>Error</th><th>Time</th></tr>'+d.recent_errors.map(e=>'<tr><td>'+esc(e.agent_id)+'</td><td>'+esc(e.operation)+'</td><td>'+esc(e.error)+'</td><td>'+esc(e.started_at)+'</td></tr>').join('')+'</table>' : telemetryEmpty(true,'No recent agent errors recorded.');
    const q = d.content_quality || {};
    $('quality').innerHTML = metric('Article coverage',pct(q.article_coverage_percent),telemetryCount(q.with_article)+'/'+telemetryCount(q.published)+' published stories') + metric('Image coverage',pct(q.image_coverage_percent),telemetryCount(q.with_image)+'/'+telemetryCount(q.published)+' have images') + metric('Story clusters',telemetryCount(q.cluster_count),'Recorded research groups');
    const v = r.verification_breakdown, ps = r.pipeline_state;
    $('advancedReport').innerHTML = metric('CONFIRMED',v ? telemetryCount(v.CONFIRMED??0) : 'Unavailable','Recorded cross-source checks') + metric('CONFLICTING',v ? telemetryCount(v.CONFLICTING??0) : 'Unavailable','Recorded cross-source checks') + metric('Single source',v ? telemetryCount(v['SINGLE SOURCE']??0) : 'Unavailable','Recorded source checks') + metric('Unverified',v ? telemetryCount(v.UNVERIFIED??0) : 'Unavailable','Recorded checks') + metric('Pipeline states',ps ? Object.keys(ps).length : 'Unavailable','Recorded transitions');
  } catch(e) { telemetryError('ops',e.message); }
}
async function loadUpgrade() {
  if (!telemetryAvailable('upgrade')) return;
  try {
    const d = await api('/api/admin/upgrade');
    const a=arr(d.alerts), f=arr(d.failures), s=arr(d.scores), src=arr(d.sources), ev=arr(d.events), rg=arr(d.regression);
    const res=d.resources||{}, h=d.history||{}, inv=d.inventory||{}, available=d.availability||{}, counts=d.counts||{};
    const database=res.database||{}, media=res.media||{};
    const dbBytes=database.status==='available'?database.bytes:null;
    $('upgradeMetrics').innerHTML = metric('Stored stories',telemetryCount(inv.total),'Actual database records') + metric('Published',telemetryCount(inv.published),'Actual publication state') + metric('Pending',telemetryCount(inv.pending),'Awaiting editorial action') + metric('Recorded scores',telemetryCount(counts.scores),'Processing/publication history') + metric('Recorded events',telemetryCount(counts.events),'Stored event groups') + metric('Database size',telemetryBytes(dbBytes),database.engine==='postgresql'?'Measured PostgreSQL database':'Allocated database pages');
    $('upgradeAlerts').innerHTML = a.length ? '<table class="table"><tr><th>Severity</th><th>Bot</th><th>Step</th><th>Item</th><th>Message</th></tr>'+a.map(x=>'<tr><td>'+esc(x.severity)+'</td><td>'+esc(x.bot)+'</td><td>'+esc(x.step)+'</td><td>'+esc(x.item_id??'—')+'</td><td>'+esc(x.message)+'</td></tr>').join('')+'</table>' : telemetryEmpty(available.alerts,'No unresolved alerts recorded.');
    $('upgradeScores').innerHTML = s.length ? '<table class="table"><tr><th>Item</th><th>Score</th><th>Fresh</th><th>Coverage</th><th>Importance</th><th>Source weight</th><th>Dup</th><th>Mode</th></tr>'+s.map(x=>'<tr><td>#'+esc(x.item_id)+'</td><td><b>'+esc(x.score)+'</b></td><td>'+esc(x.freshness)+'</td><td>'+esc(x.coverage)+'</td><td>'+esc(x.importance)+'</td><td>'+esc(x.verification)+'</td><td>'+esc(x.duplicate_risk)+'</td><td>'+Number(x.breaking?'1':'0')+'</td></tr>').join('')+'</table><p class="muted">Scores are rule-based editorial signals, not independent fact-check certificates.</p>' : telemetryEmpty(available.scores,'No scoring runs recorded yet. Stored stories remain visible in the inventory above; publishing or processing records new scores.');
    const inventorySources=arr(inv.sources);
    $('upgradeSources').innerHTML = src.length ? '<table class="table"><tr><th>Source</th><th>Success</th><th>Broken</th><th>Corrections</th><th>Coverage</th></tr>'+src.map(x=>'<tr><td>'+esc(x.source)+'</td><td>'+esc(x.success_rate)+'%</td><td>'+esc(x.broken_links)+'</td><td>'+esc(x.correction_frequency)+'%</td><td>'+esc(x.coverage_consistency)+'%</td></tr>').join('')+'</table>' : inventorySources.length ? '<p class="muted">Stored source coverage. Fetch success/reliability has not been recorded yet.</p><table class="table"><tr><th>Source</th><th>Stored stories</th><th>Published</th><th>Last collected</th></tr>'+inventorySources.map(x=>'<tr><td>'+esc(x.source||'Unknown source')+'</td><td>'+telemetryCount(x.records)+'</td><td>'+telemetryCount(x.published)+'</td><td>'+esc(date(x.last_collected_at))+'</td></tr>').join('')+'</table>' : telemetryEmpty(inv.sources_available===false?false:available.sources,'No source records available.');
    $('upgradeEvents').innerHTML = ev.length ? '<table class="table"><tr><th>Event</th><th>Category</th><th>Status</th><th>Updated</th></tr>'+ev.map(x=>'<tr><td>'+esc(x.canonical_title)+'</td><td>'+esc(x.category)+'</td><td>'+esc(x.status)+'</td><td>'+esc(x.updated_at)+'</td></tr>').join('')+'</table>' : telemetryEmpty(available.events,'No event groups recorded yet. This is separate from the stored story count above.');
    $('upgradeResources').innerHTML = metric('DB',telemetryBytes(dbBytes),database.status==='available'?(database.engine==='postgresql'?'Connected PostgreSQL':'SQLite allocated pages'):'Size measurement unavailable') + metric('Media',telemetryBytes(media.status==='available'?media.bytes:null),media.status==='not_configured'?'No media directory configured':media.status==='available'?'Measured files':'Size measurement unavailable');
    $('upgradeHistory').innerHTML = '<div class="kv">'+metric('Scores',telemetryCount(h.counts?.scores),'Recorded in last 30 days')+metric('Alerts',telemetryCount(h.counts?.alerts),'Recorded in last 30 days')+metric('Failures',telemetryCount(h.counts?.failures),'Recorded in last 30 days')+'</div>';
    $('upgradeRegression').innerHTML = rg.length ? '<table class="table"><tr><th>Commit</th><th>Status</th><th>Created</th></tr>'+rg.map(x=>'<tr><td>'+esc(x.commit_ref||'—')+'</td><td>'+esc(x.status)+'</td><td>'+esc(x.created_at)+'</td></tr>').join('')+'</table>' : telemetryEmpty(available.regression,'No CI results imported into this database. See the repository Actions page for actual CI runs.');
  } catch(e) { telemetryError('upgrade',e.message); }
}
