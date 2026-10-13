/* Approval-pending sites never request Google's advertising script. */
(() => {
  if (!['politicshub.in','www.politicshub.in'].includes(location.hostname)) return;
  if (/^#\/(settings|search|article)/.test(location.hash)) return;
  let config, loading = false;
  function start(tc, success) {
    if (!success || !config?.enabled || loading || document.getElementById('ph-adsense')) return;
    if (!['tcloaded','useractioncomplete'].includes(tc?.eventStatus)) return;
    // Browser-storage preferences are NOT advertising consent. A separately
    // configured Google-certified CMP supplies the IAB TCF decision.
    const consent = tc.gdprApplies === false || (tc.gdprApplies === true && tc.vendor?.consents?.[755] && [1,3,4].every(id => tc.purpose?.consents?.[id]));
    if (!consent || /^#\/(settings|search|article)/.test(location.hash)) return;
    loading = true;
    const script = document.createElement('script');
    script.id = 'ph-adsense'; script.async = true; script.crossOrigin = 'anonymous';
    script.src = 'https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=' + encodeURIComponent(config.client);
    script.onerror = () => { script.remove(); loading = false; };
    document.head.append(script);
  }
  fetch('/api/ads-config', {cache:'no-store', credentials:'omit'})
    .then(r => r.ok ? r.json() : null)
    .then(value => {
      if (!value?.enabled || !/^ca-pub-\d{16}$/.test(value.client)) return;
      config = value;
      if (typeof window.__tcfapi === 'function') window.__tcfapi('addEventListener',2,start);
      // CMP integrations that initialize later can signal readiness without
      // treating the site's preferences banner as advertising consent.
      else window.addEventListener('ph:cmp-ready', () => {
        if (typeof window.__tcfapi === 'function') window.__tcfapi('addEventListener',2,start);
      }, {once:true});
    }).catch(() => {});
})();
