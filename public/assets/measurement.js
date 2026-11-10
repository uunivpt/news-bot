/* Google tag: GA4 + Google Ads, Consent Mode v2.
 * Load the tag once with denied defaults so tag diagnostics can find it.
 * Google's advanced consent mode may send cookieless pings while denied;
 * full measurement and advertising cookies require a Google CMP decision.
 * Site preference choices are NOT Google advertising consent.
 */
(() => {
  const path = location.pathname;
  if (/^\/(?:admin(?:\/|$)|api(?:\/|$)|newsroom-console|debug)/.test(path)) return;

  const GA4_ID = 'G-2HVZQST08G';
  const ADS_ID = 'AW-18495731647';

  window.dataLayer = window.dataLayer || [];
  window.gtag = window.gtag || function () {
    window.dataLayer.push(arguments);
  };
  // Consent defaults must be queued before any configuration or events.
  window.gtag('consent', 'default', {
    analytics_storage: 'denied',
    ad_storage: 'denied',
    ad_user_data: 'denied',
    ad_personalization: 'denied',
    wait_for_update: 500
  });
  window.gtag('set', 'ads_data_redaction', true);
  window.gtag('js', new Date());
  window.gtag('config', GA4_ID);
  // A Google Ads account tag is not, by itself, a conversion event.
  window.gtag('config', ADS_ID);

  if (!document.querySelector('script[data-politicshub-google-tag]')) {
    const tag = document.createElement('script');
    tag.async = true;
    tag.src = 'https://www.googletagmanager.com/gtag/js?id=' + GA4_ID;
    tag.dataset.politicshubGoogleTag = '';
    document.head.appendChild(tag);
  }

  window.googlefc = window.googlefc || {};
  window.googlefc.callbackQueue = window.googlefc.callbackQueue || [];
  window.googlefc.callbackQueue.push({ CONSENT_MODE_DATA_READY: () => {
    const fc = window.googlefc;
    const enums = fc.ConsentModePurposeStatusEnum;
    if (!enums || typeof fc.getGoogleConsentModeValues !== 'function') return;
    const consent = fc.getGoogleConsentModeValues();
    if (!consent) return;
    const permitted = value => value !== undefined &&
      (value === enums.CONSENT_MODE_PURPOSE_STATUS_GRANTED ||
       value === enums.CONSENT_MODE_PURPOSE_STATUS_NOT_APPLICABLE);
    window.gtag('consent', 'update', {
      analytics_storage: permitted(consent.analyticsStoragePurposeConsentStatus) ? 'granted' : 'denied',
      ad_storage: permitted(consent.adStoragePurposeConsentStatus) ? 'granted' : 'denied',
      ad_user_data: permitted(consent.adUserDataPurposeConsentStatus) ? 'granted' : 'denied',
      ad_personalization: permitted(consent.adPersonalizationPurposeConsentStatus) ? 'granted' : 'denied'
    });
  } });

  window.googlefc.callbackQueue.push({ CONSENT_API_READY: () => {
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
  } });
})();
