/* Private editorial material stays in memory and is cleared on logout. */
'use strict';
window.Editorial = (() => {
  let selectedSources = new Set(), sources = [], groups = [], current = null, id = 0, sequence = 0, jobSequence = 0, edits = 0, generated = null;
  let readinessPage = 1, readinessPages = 1, policyUser = '';
  const desks = ['general','india','world','politics','maharashtra','hindi','business','technology','sports','entertainment','science','health'];
  const globalPowers = ['reports.read','operations.read','settings.manage','training.manage','activity.read'];
  const sourceLink = (url, label) => `<a href="${esc(safeUrl(url))}" target="_blank" rel="noopener noreferrer">${esc(label || url)} ↗</a>`;
  function sourceCard(row, selectable = false) {
    return `<div class="source-report">${selectable ? `<label><input type="checkbox" data-event-source="${Number(row.id)}" ${selectedSources.has(Number(row.id)) ? 'checked' : ''}> Select report #${Number(row.id)}</label>` : ''}<h3>${esc(row.title || row.headline)}</h3><small>${esc(row.source_name || row.publisher)} · ${esc(date(row.published_at))} · ${esc(row.category || '')}</small><blockquote>${esc(row.summary || row.text || '')}</blockquote>${sourceLink(row.url,'Original source')} <button class="text-btn" data-studio="${Number(row.id)}">Open studio ↗</button></div>`;
  }
  function reset() {
    sequence++;jobSequence++;selectedSources.clear();sources=[];groups=[];current=null;id=0;generated=null;policyUser='';
    for (const name of ['eventSourceList','eventGroups','eventSuggestions','studioSourceList','studioClaims','studioUpdates','studioSuggestions','studioPreview','studioFacts','studioTimeline','readinessArticles','readinessMetrics','readinessTechnical','readinessLive','policyPermissions','policyDesks']) $(name).replaceChildren();
    $('eventSuggestions')._suggestions=[];$('studioHeadlines')._options=[];
    for (const name of ['studioMessage','studioAssignment','studioState','studioModelStatus','studioHeadlines','studioJobs','readinessNotice']) $(name).textContent='';
    $('studioAssignee').value='';
    for (const name of ['studioForm','claimForm','updateForm','eventCreateForm']) $(name).reset();
    $('studioContent').classList.add('hidden');$('studioId').value='';$('eventSearch').value='';$('studioApplyGenerated').classList.add('hidden');
    if ($('policyDialog').open) $('policyDialog').close();
  }
  function usable() {
    if (!workspace || workspace.access.read_only) { notice('This section needs the live phone database.','err'); return false; }
    return true;
  }
  async function load(view) {
    if (!usable()) return;
    if (view==='events') await loadEvents();
    if (view==='studio' && id) await open(id,false);
    if (view==='readiness') await loadReadiness();
  }
  async function loadEvents() {
    const serial=++sequence;
    try {
      const query=encodeURIComponent($('eventSearch').value.trim());
      const [directory,data]=await Promise.all([api('/api/admin/editorial/sources?search='+query),api('/api/admin/editorial/events?search='+query)]);
      if (serial!==sequence) return;
      sources=directory.stories;groups=data.events;
      $('eventSourceScope').textContent=`${number(directory.total)} matching reports · showing newest ${directory.stories.length}. Selection persists across searches.`;
      $('eventSourceList').innerHTML=sources.map(row=>sourceCard(row,true)).join('') || empty('No matching sources','Try a publisher name or event keyword.');
      $('eventSuggestionScope').textContent=data.suggestion_scope;
      $('eventSuggestions').innerHTML=data.suggestions.map((group,index)=>`<article class="editorial-source"><b>${esc(group.title)}</b><small>${group.stories.length} reports · ${group.publisher_count} publisher groups</small><button class="btn small" data-use-suggestion="${index}">Select these reports</button></article>`).join('') || '<p class="muted">No lexical matches. Select sources manually to group Marathi and English reports about the same event.</p>';
      $('eventSuggestions')._suggestions=data.suggestions;
      $('eventGroups').innerHTML=groups.map(group=>`<details class="section"><summary>${esc(group.title)} · ${group.stories.length} reports</summary><p class="muted">Grouped by ${esc(group.created_by)} · ${esc(date(group.updated_at))}</p><button class="btn small" data-add-group="${esc(group.id)}" ${!can('news.edit') ? 'disabled' : ''}>Add selected reports</button>${group.stories.map(row=>sourceCard(row)).join('')}</details>`).join('') || '<p class="muted">No confirmed groups yet.</p>';
      $('eventCreate').disabled=!can('news.edit');updateSelected();
    } catch(error){if(serial===sequence)notice(error.message,'err');}
  }
  function updateSelected(){ $('eventSelected').textContent=selectedSources.size+' selected · maximum 10'; }
  async function open(storyId,navigate=true) {
    if (!usable()) return;
    const chosen=Number(storyId);if(!Number.isSafeInteger(chosen)||chosen<1)return notice('Enter a valid story ID.','err');
    id=chosen;$('studioId').value=id;if(navigate && currentView!=='studio') { go('studio');return; }
    const serial=++sequence;jobSequence++;$('studioContent').classList.add('hidden');$('studioMessage').textContent='Loading source material…';
    try {
      const data=await api(`/api/admin/studio/${chosen}`);
      if(serial!==sequence)return;
      current=data;edits=0;generated=null;$('studioApplyGenerated').classList.add('hidden');
      $('studioMessage').textContent=`Story #${chosen} · ${data.story.source_name} · ${data.story.status}. Original source material is separate from your editorial draft.`;
      $('studioContent').classList.remove('hidden');
      const row=data.story;
      $('studioState').textContent=row.status;$('studioAssignment').textContent='Assigned to: '+(data.assigned_to || 'Not assigned');
      $('studioSourceList').innerHTML=data.source_pack.reports.map(report=>`<label class="editorial-source"><input type="checkbox" data-studio-source="${Number(report.id)}" checked ${Number(report.id)===id ? 'disabled' : ''}> ${esc(report.publisher)} · ${esc(report.headline)}</label><blockquote>${esc(report.text)}</blockquote>${sourceLink(report.url)}`).join('');
      $('studioFacts').textContent=data.source_pack.names_numbers_dates.join(' · ') || 'No extractable names or numeric tokens. Check the source text directly.';
      $('studioTimeline').innerHTML=data.source_pack.timeline.map(item=>`<p><b>${esc(date(item.at))}</b> · ${esc(item.publisher)}<br>${esc(item.headline)}</p>`).join('') || '<p class="muted">Sources did not provide usable publication dates.</p>';
      $('studioHeadline').value=row.title || '';$('studioSummary').value=row.bot_summary || row.summary || '';$('studioArticle').value=row.bot_article || '';
      $('studioCategory').innerHTML=desks.map(d=>`<option ${d===row.category ? 'selected' : ''}>${esc(d)}</option>`).join('');
      $('studioImage').value=row.image_url || '';$('studioLicense').value=row.image_license || '';$('studioCredit').value=row.image_credit || '';
      $('studioModelStatus').textContent=data.model_configured ? 'Automatic Marathi drafting is available through the configured newsroom model. Review the resulting draft against the sources.' : 'Automatic drafting needs an available newsroom model. The source outline and manual Marathi editor are available.';
      $('studioHeadlines').replaceChildren();
      $('studioJobs').innerHTML=arr(data.jobs).map(job=>`<p class="muted">Draft job · ${esc(job.status)} · ${esc(date(job.updated_at))} <button class="text-btn" data-load-job="${esc(job.id)}" ${row.status==='published'?'disabled':''}>Check / load result</button></p>`).join('');
      const editable=can('news.edit') && row.status!=='published';
      $('studioForm').querySelectorAll('input,textarea,select').forEach(node=>node.disabled=!editable);
      $('studioSave').disabled=!editable;$('studioVerify').disabled=!can('news.publish') || row.status==='published';
      $('studioOutline').disabled=!can('news.create') || row.status==='published';$('studioGenerate').disabled=!can('news.create') || !data.model_configured || row.status==='published';
      $('claimCreate').disabled=!can('news.edit');$('updateSave').disabled=!can('news.edit');$('studioAssignControls').hidden=!can('users.manage');
      $('studioAssignee').value=data.assigned_to || '';
      renderClaims();renderUpdates();preview();
    }catch(error){if(serial===sequence)$('studioMessage').textContent=error.message;}
  }
  function preview() {
    const article=$('studioPreview');article.replaceChildren();
    const title=document.createElement('h2');title.textContent=$('studioHeadline').value;
    const lead=document.createElement('p');lead.textContent=$('studioSummary').value;
    const body=document.createElement('p');body.textContent=$('studioArticle').value;
    article.append(title,lead,body);
  }
  function applyDraft(draft) {
    if(!current || current.story.status==='published')return;
    $('studioHeadline').value=draft.headline;$('studioSummary').value=draft.summary;$('studioArticle').value=draft.article;
    $('studioHeadlines').innerHTML=arr(draft.headline_options).map((title,index)=>`<button class="btn small" type="button" data-headline-option="${index}">${esc(title)}</button>`).join('');
    $('studioHeadlines')._options=draft.headline_options || [];
    $('studioModelStatus').textContent=draft.language_note || 'Generated draft; attribution, wording and facts still need editorial review.';edits++;preview();
  }
  async function prepare(mode) {
    if(!current)return;
    const capturedId=id,version=sessionVersion,counter=edits,jobToken=++jobSequence;
    $('studioGenerate').disabled=true;$('studioOutline').disabled=true;$('studioModelStatus').textContent='Preparing draft…';
    try {
      const story_ids=[...document.querySelectorAll('[data-studio-source]:checked')].map(node=>Number(node.dataset.studioSource));
      let data=await action(`/api/admin/studio/${capturedId}/prepare`,{mode,story_ids});
      if(data.job_id) {
        for(let attempt=0;attempt<150;attempt++) {
          if(jobToken!==jobSequence || version!==sessionVersion || id!==capturedId)return;
          await new Promise(resolve=>setTimeout(resolve,2000));
          data=await api(`/api/admin/studio/${capturedId}/jobs/${data.job_id}`);
          if(data.status==='complete')break;
          if(['failed','interrupted'].includes(data.status))throw new Error(data.message || 'Draft generation failed.');
          $('studioModelStatus').textContent=data.status==='queued' ? 'Draft is queued; your saved story is unchanged.' : 'Writing Marathi draft from the selected sources…';
        }
        if(!data.draft)throw new Error('Draft is still running. Reopen the studio later or prepare a source outline.');
      }
      if(jobToken!==jobSequence || version!==sessionVersion || id!==capturedId)return;
      if(counter!==edits){generated=data.draft;$('studioApplyGenerated').classList.remove('hidden');$('studioModelStatus').textContent='Draft ready. Your edits were preserved; use Apply generated draft to load it.';}
      else applyDraft(data.draft);
    }catch(error){if(version===sessionVersion && id===capturedId)$('studioModelStatus').textContent=error.message;}
    finally{if(version===sessionVersion && id===capturedId){$('studioOutline').disabled=!can('news.create') || current?.story.status==='published';$('studioGenerate').disabled=!can('news.create') || !current?.model_configured || current?.story.status==='published';}}
  }
  function renderClaims() {
    $('studioClaims').innerHTML=current.claims.map(claim=>`<article class="editorial-claim"><h3>${esc(claim.statement)}</h3><span class="pill ${claim.stale ? 'amber' : ''}">${claim.stale ? 'Needs review after article edits' : 'Editor assessment: '+esc(claim.assessment)}</span><small>${claim.publishers} publisher groups · recorded by ${esc(claim.created_by)}</small>${claim.evidence.map(e=>`<blockquote>${esc(e.excerpt)}<br>${sourceLink(e.source_url,e.publisher)} · ${esc(e.stance)} · ${esc(e.recorded_by)}</blockquote>`).join('')}<details><summary>Record source evidence / update assessment</summary><form data-evidence-form="${Number(claim.id)}"><label class="label">Publisher<input class="field" name="publisher" maxlength="200" required></label><label class="label">Public HTTPS source<input class="field" name="source_url" type="url" required></label><label class="label">Relevant source excerpt<textarea class="field" name="excerpt" maxlength="4000" minlength="3" required></textarea></label><label class="label">Evidence stance<select class="field" name="stance"><option value="supports">Supports claim</option><option value="disputes">Disputes claim</option><option value="context">Context only</option></select></label><label class="label">Your assessment<select class="field" name="assessment"><option value="insufficient">Insufficient evidence</option><option value="supported">Supported by cited evidence</option><option value="disputed">Disputed</option></select></label><button class="btn" type="submit" ${!can('news.edit')?'disabled':''}>Record evidence</button></form></details></article>`).join('') || '<p class="muted">No claim assessments recorded.</p>';
  }
  function renderUpdates() {
    $('studioSuggestions').innerHTML=current.suggested_updates.map((item,index)=>`<article class="editorial-source"><b>${esc(item.publisher)}</b><p>${esc(item.headline)}</p><small>${item.confirmed_event ? 'Newer collected report in this confirmed event' : 'Possible follow-up based on headline similarity; confirm it concerns this event'} · review before publication</small><button class="btn small" data-use-update="${index}" ${!can('news.edit')?'disabled':''}>Use as update proposal</button></article>`).join('');
    $('studioUpdates').innerHTML=current.updates.map(item=>`<article class="editorial-source"><h3>${esc(item.label)}</h3><span class="pill">${esc(item.kind)} · ${esc(item.status)}</span><p>${esc(item.body)}</p>${sourceLink(item.source_url)}<small>${esc(item.published_at ? 'Published '+date(item.published_at)+' by '+item.published_by : 'Proposed '+date(item.created_at)+' by '+item.created_by)}</small>${item.status==='pending' ? `<button class="btn" data-publish-update="${Number(item.id)}" ${!can('news.publish') || current.story.status!=='published'?'disabled':''}>Publish this update</button>` : ''}</article>`).join('') || '<p class="muted">No update proposals or corrections recorded.</p>';
  }
  async function loadReadiness() {
    const serial=++sequence;
    try {
      const data=await api('/api/admin/editorial/readiness?page='+readinessPage);if(serial!==sequence)return;
      readinessPages=data.pages;$('readinessNotice').textContent=data.notice+' Checked '+date(data.checked_at);
      $('readinessMetrics').innerHTML=metric('Published reports',number(data.totals.published),'Entire database')+metric('Short article bodies',number(data.totals.short_body),'Local 600-character quality check')+metric('Missing image rights',number(data.totals.missing_image_rights),'Published images without licence / credit')+metric('Repeated headline groups',number(data.totals.duplicate_title_groups),'Review for duplicate coverage');
      $('readinessTechnical').innerHTML=`<p><b>Local ads.txt:</b> ${data.ads_txt.expected_line_present?'Expected publisher line present':'Needs attention'}</p><ul>${data.policy_pages.map(item=>`<li>${sourceLink(item.path,item.path)} · ${item.present?'File present':'File missing'}</li>`).join('')}</ul><p>File presence does not establish that the content is sufficient or publicly reachable.</p>${data.guidance.map(item=>sourceLink(item.url,item.label)).join(' · ')}`;
      $('readinessArticles').innerHTML=data.articles.map(item=>`<article class="editorial-source"><h3>${esc(item.title)}</h3><span class="pill">${item.monetizable_under_local_rules?'Current local ad review complete':'Editorial review needed'}</span><ul>${item.findings.map(value=>`<li>${esc(value)}</li>`).join('')}</ul><button class="btn" data-studio="${Number(item.id)}">Open article studio</button></article>`).join('') || '<p class="muted">No published stories in this page.</p>';
      $('readinessPage').textContent=`Page ${readinessPage} of ${readinessPages}`;$('readinessPrev').disabled=readinessPage<=1;$('readinessNext').disabled=readinessPage>=readinessPages;
    }catch(error){if(serial===sequence)notice(error.message,'err');}
  }
  async function openPolicy(username) {
    if(!can('users.manage'))return;
    try {
      const data=await api('/api/admin/users'),user=data.users.find(item=>item.username===username);if(!user || user.protected)return;
      policyUser=username;$('policyTitle').textContent='Exact permissions · '+username;
      $('policyPermissions').className='editorial-permissions';$('policyDesks').className='editorial-permissions';
      $('policyPermissions').innerHTML=data.available_permissions.map(power=>`<label><input type="checkbox" data-policy-power="${esc(power)}" ${user.permissions.includes(power)?'checked':''}> ${esc(powerLabel(power))}</label>`).join('');
      $('policyDesks').innerHTML=data.desks.map(desk=>`<label><input type="checkbox" data-policy-desk="${esc(desk)}" ${user.policy?.categories.includes(desk)?'checked':''}> ${esc(desk)}</label>`).join('');
      $('policyOwnOnly').checked=!!user.policy?.own_only;$('policyDialog').showModal();
    }catch(error){notice(error.message,'err');}
  }
  // All actions share the existing same-origin CSRF and session lifecycle.
  $('eventsRefresh').onclick=loadEvents;$('eventSearchForm').onsubmit=event=>{event.preventDefault();loadEvents();};
  $('eventSourceList').onchange=event=>{const node=event.target.closest('[data-event-source]');if(!node)return;const value=Number(node.dataset.eventSource);if(node.checked && selectedSources.size>=10){node.checked=false;return notice('Select at most 10 reports.','err');}node.checked?selectedSources.add(value):selectedSources.delete(value);updateSelected();};
  $('eventCreateForm').onsubmit=async event=>{event.preventDefault();$('eventCreate').disabled=true;try{await action('/api/admin/editorial/events',{title:$('eventTitle').value,story_ids:[...selectedSources]});selectedSources.clear();$('eventTitle').value='';await loadEvents();notice('Event group saved');}catch(error){notice(error.message,'err');}finally{$('eventCreate').disabled=!can('news.edit');}};
  $('eventSuggestions').onclick=event=>{const button=event.target.closest('[data-use-suggestion]');if(!button)return;const group=$('eventSuggestions')._suggestions[Number(button.dataset.useSuggestion)];selectedSources=new Set(group.stories.slice(0,10).map(row=>Number(row.id)));$('eventTitle').value=group.title;document.querySelectorAll('[data-event-source]').forEach(node=>node.checked=selectedSources.has(Number(node.dataset.eventSource)));updateSelected();};
  $('eventGroups').addEventListener('click',async event=>{const button=event.target.closest('[data-add-group]');if(!button)return;button.disabled=true;try{await action('/api/admin/editorial/events/'+button.dataset.addGroup+'/sources',{story_ids:[...selectedSources]});selectedSources.clear();await loadEvents();notice('Sources added');}catch(error){notice(error.message,'err');}finally{button.disabled=!can('news.edit');}});
  $('studioOpenForm').onsubmit=event=>{event.preventDefault();open(Number($('studioId').value));};
  $('studioForm').oninput=()=>{edits++;preview();};
  $('studioForm').onsubmit=async event=>{event.preventDefault();if(!current)return;$('studioSave').disabled=true;try{await action(`/api/admin/studio/${id}/save`,{revision:current.revision,title:$('studioHeadline').value,summary:$('studioSummary').value,article:$('studioArticle').value,category:$('studioCategory').value,image_url:$('studioImage').value,image_license:$('studioLicense').value,image_credit:$('studioCredit').value});await open(id,false);notice('Draft saved; existing claim assessments need review if the copy changed.');}catch(error){notice(error.message,'err');}finally{$('studioSave').disabled=!can('news.edit') || current?.story.status==='published';}};
  $('studioOutline').onclick=()=>prepare('source');$('studioGenerate').onclick=()=>prepare('model');
  $('studioJobs').onclick=async event=>{const button=event.target.closest('[data-load-job]');if(!button)return;try{const data=await api(`/api/admin/studio/${id}/jobs/${button.dataset.loadJob}`);if(data.draft)applyDraft(data.draft);else notice(data.message || 'Draft job: '+data.status);}catch(error){notice(error.message,'err');}};
  $('studioApplyGenerated').onclick=()=>{if(generated)applyDraft(generated);generated=null;$('studioApplyGenerated').classList.add('hidden');};
  $('studioHeadlines').onclick=event=>{const button=event.target.closest('[data-headline-option]');if(button && can('news.edit')){$('studioHeadline').value=$('studioHeadlines')._options[Number(button.dataset.headlineOption)];edits++;preview();}};
  $('studioVerify').onclick=async()=>{if(!id || !can('news.publish'))return;await newsAction('approve',id);await open(id,false);};
  $('studioAssign').onclick=async()=>{try{await action(`/api/admin/editorial/story/${id}/assign`,{username:$('studioAssignee').value.trim()});await open(id,false);notice('Story assignment saved');}catch(error){notice(error.message,'err');}};
  $('claimForm').onsubmit=async event=>{event.preventDefault();try{await action(`/api/admin/editorial/story/${id}/claims`,{statement:$('claimStatement').value});$('claimForm').reset();await open(id,false);notice('Claim recorded; evidence is not yet established.');}catch(error){notice(error.message,'err');}};
  $('studioClaims').onsubmit=async event=>{const form=event.target.closest('[data-evidence-form]');if(!form)return;event.preventDefault();try{await action(`/api/admin/editorial/story/${id}/claims/${form.dataset.evidenceForm}`,Object.fromEntries(new FormData(form)));await open(id,false);notice('Evidence and your assessment recorded');}catch(error){notice(error.message,'err');}};
  $('updateForm').onsubmit=async event=>{event.preventDefault();try{await action(`/api/admin/editorial/story/${id}/updates`,{label:$('updateLabel').value,body:$('updateBody').value,source_url:$('updateSource').value,kind:$('updateKind').value,revision:current.revision});$('updateForm').reset();await open(id,false);notice('Update proposal saved');}catch(error){notice(error.message,'err');}};
  $('studioSuggestions').onclick=event=>{const button=event.target.closest('[data-use-update]');if(!button)return;const row=current.suggested_updates[Number(button.dataset.useUpdate)];$('updateLabel').value=row.headline.slice(0,250);$('updateBody').value=row.text || row.headline;$('updateSource').value=row.url;};
  $('studioUpdates').onclick=async event=>{const button=event.target.closest('[data-publish-update]');if(!button)return;button.disabled=true;try{const result=await action(`/api/admin/editorial/story/${id}/updates/${button.dataset.publishUpdate}/publish`);notice(publicationMessage(result));await open(id,false);}catch(error){notice(error.message,'err');}finally{button.disabled=!can('news.publish');}};
  $('readinessRefresh').onclick=loadReadiness;$('readinessPrev').onclick=()=>{readinessPage--;loadReadiness();};$('readinessNext').onclick=()=>{readinessPage++;loadReadiness();};
  $('readinessProbe').onclick=async()=>{$('readinessProbe').disabled=true;try{const data=await action('/api/admin/editorial/readiness/probe');$('readinessLive').innerHTML='<h3>Live HTTP checks</h3><p>'+esc(data.scope)+'</p>'+data.checks.map(item=>`<p><b>${esc(item.path)}</b> · ${esc(item.status)}${item.http_status?' · HTTP '+Number(item.http_status):''} · ${esc(date(item.checked_at))}${item.publisher_id_present!==undefined?' · publisher ID '+(item.publisher_id_present?'present':'missing'):''}${item.root_blocked?' · root Disallow found; review robots.txt':''}</p>`).join('');}catch(error){notice(error.message,'err');}finally{$('readinessProbe').disabled=!can('reports.read');}};
  $('policyClose').onclick=()=>$('policyDialog').close();
  $('policyForm').onchange=()=>{if($('policyOwnOnly').checked || document.querySelector('[data-policy-desk]:checked'))document.querySelectorAll('[data-policy-power]').forEach(node=>{if(globalPowers.includes(node.dataset.policyPower))node.checked=false;});};
  $('policyForm').onsubmit=async event=>{event.preventDefault();$('policySave').disabled=true;try{await action('/api/admin/users/'+encodeURIComponent(policyUser),{operation:'policy',permissions:[...document.querySelectorAll('[data-policy-power]:checked')].map(node=>node.dataset.policyPower),categories:[...document.querySelectorAll('[data-policy-desk]:checked')].map(node=>node.dataset.policyDesk),own_only:$('policyOwnOnly').checked});$('policyDialog').close();await loadTeam();notice('Exact staff permissions saved');}catch(error){notice(error.message,'err');}finally{$('policySave').disabled=false;}};
  document.addEventListener('click',event=>{const studio=event.target.closest('[data-studio]'),policy=event.target.closest('[data-policy-user]');if(studio){if($('inspector').open)$('inspector').close();open(Number(studio.dataset.studio));}if(policy)openPolicy(policy.dataset.policyUser);});
  return {load,open,reset};
})();
