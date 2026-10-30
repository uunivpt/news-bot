(() => {
  const $ = selector => document.querySelector(selector);
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-consent-choice]');
    if (!button) return;
    const mode = button.dataset.consentChoice === 'preferences' ? 'preferences' : 'essential';
    try {
      localStorage.setItem('ph-consent-v1', mode);
      if (mode === 'essential') {
        ['ph-news-cache','ph-news-cache-v6','ph-news-cache-v5','ph-news-cache-v4','ph-theme','ph-cookie','ph-ls','ph-reading-list-v1'].forEach(key => localStorage.removeItem(key));
        document.documentElement.dataset.theme = 'light';
      }
    } catch (_) {}
    button.textContent = mode === 'preferences' ? 'Preferences allowed' : 'Essential only selected';
    document.querySelectorAll('[data-consent-choice]').forEach(el => el.setAttribute('aria-pressed', String(el === button)));
  });
  function bind(form, message, method, data) {
    if (!form) return;
    const submit = form.querySelector('button[type="submit"]');
    let busy = false;
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (busy || !form.reportValidity()) return;
      busy = true; submit.disabled = true; form.setAttribute('aria-busy','true'); message.textContent = 'Sending…';
      try {
        const response = await fetch('/api/newsletter', {method,headers:{'Content-Type':'application/json'},body:JSON.stringify(data()),signal:AbortSignal.timeout(15000)});
        const result = await response.json();
        message.textContent = result.message || result.error || 'Please try again.';
        if (response.ok) form.reset();
      } catch (_) { message.textContent = 'Could not complete your request. Please try again.'; }
      finally { busy = false; submit.disabled = false; form.removeAttribute('aria-busy'); }
    });
  }
  const newsletter = $('#newsletterForm');
  bind(newsletter, $('#newsletterMessage'), 'POST', () => ({email:$('#newsletterEmail').value,consent:$('#newsletterPrivacy').checked,adult:$('#newsletterAdult').checked}));
  bind($('#unsubscribeForm'), $('#unsubscribeMessage'), 'DELETE', () => ({email:$('#unsubscribeEmail').value}));
  if (newsletter) fetch('/api/newsletter', {cache:'default'}).then(r => r.json()).then(status => {
    if (status.available === false) {
      const button = newsletter.querySelector('button[type="submit"]'); button.disabled = true; button.textContent = status.delivery_configured ? 'Temporarily unavailable' : 'Coming soon';
      $('#newsletterMessage').textContent = status.message || 'Subscription is temporarily unavailable. Please try again later.';
    }
  }).catch(() => {});
})();
