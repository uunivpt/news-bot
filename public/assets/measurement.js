/* Basic consent mode: optional measurement waits for Google's CMP decision.
 * Site theme/cache preferences are deliberately not advertising consent.
 */
(() => {
  const path = location.pathname;
  if (/^\/(?:admin|api\/|newsroom-console|debug)/.test(path)) return;
  let initialized = false;
  let analyticsConfigured = false, adsConfigured = false;
  window.googlefc = window.googlefc || {};
  window.googlefc.callbackQueue = window.googlefc.callbackQueue || [];
  window.googlefc.callbackQueue.push({CONSENT_MODE_DATA_READY: () => {
    const fc = window.googlefc, enums = fc.ConsentModePurposeStatusEnum;
    if (!enums || typeof fc.getGoogleConsentModeValues !== 'function') return;
    const consent = fc.getGoogleConsentModeValues();
    if (!consent) return;
    const permitted = value => value !== undefined &&
      (value === enums.CONSENT_MODE_PURPOSE_STATUS_GRANTED ||
       value === enums.CONSENT_MODE_PURPOSE_STATUS_NOT_APPLICABLE);
    // NOT_CONFIGURED and UNKNOWN never substitute for a consent decision.
    const analytics = permitted(consent.analyticsStoragePurposeConsentStatus);
    const ads = permitted(consent.adStoragePurposeConsentStatus) &&
      permitted(consent.adUserDataPurposeConsentStatus) &&
      permitted(consent.adPersonalizationPurposeConsentStatus);
    if (!analytics && !ads && !initialized) return;
    window.dataLayer = window.dataLayer || [];
    window.gtag = window.gtag || function() { window.dataLayer.push(arguments); };
    window['ga-disable-G-2HVZQST08G'] = !analytics;
    const values = {
      analytics_storage: analytics ? 'granted' : 'denied',
      ad_storage: ads ? 'granted' : 'denied',
      ad_user_data: ads ? 'granted' : 'denied',
      ad_personalization: ads ? 'granted' : 'denied'
    };
    window.gtag('consent', initialized ? 'update' : 'default', values);
    if (!initialized) window.gtag('js', new Date());
    if (analytics && !analyticsConfigured) {
      analyticsConfigured = true;
      window.gtag('config', 'G-2HVZQST08G');
    }
    if (ads && !adsConfigured) {
      adsConfigured = true;
      window.gtag('config', 'AW-18495731647');
      if (path === '/' || path === '/index.html') {
        window.gtag('event', 'conversion', {
          'send_to': 'AW-18495731647/4NrBCOKXz6UdEL_vufNE'
        });
      }
    }
    if (initialized) return;
    initialized = true;
    const script = document.createElement('script');
    script.async = true;
    script.src = 'https://www.googletagmanager.com/gtag/js?id=' +
      (analytics ? 'G-2HVZQST08G' : 'AW-18495731647');
    document.head.appendChild(script);
  }});
  window.googlefc.callbackQueue.push({CONSENT_API_READY: () => {
    if (typeof window.googlefc.showRevocationMessage !== 'function') return;
    const footer = document.querySelector('footer');
    if (!footer || document.querySelector('[data-ad-privacy]')) return;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn';
    button.dataset.adPrivacy = '';
    button.textContent = 'Advertising privacy choices';
    button.addEventListener('click', () => window.googlefc.callbackQueue.push({
      CONSENT_API_READY: () => window.googlefc.showRevocationMessage()
    }));
    footer.appendChild(button);
  }});
})();
