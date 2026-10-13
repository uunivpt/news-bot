# AdSense setup (approval pending)

Publisher: `ca-pub-1752666987448533`, matching the existing `public/ads.txt` DIRECT entry.

The homepage and news templates include Google's `google-adsense-account` verification meta tag. They load a small first-party configuration check; no Google advertising script is requested by default. Google approval, ownership verification and revenue cannot be established by repository code.

## Submit for review

1. Deploy the change. In AdSense, select the meta-tag verification method and request a review for politicshub.in. Check both the apex and www redirect destination.
2. Confirm `/ads.txt` serves `google.com, pub-1752666987448533, DIRECT, f08c47fec0942fa0` as plain text and the verification tag appears in page source.
3. Keep `ADSENSE_ENABLED=false` and `ADSENSE_CMP_READY=false` while review is pending. No ad-unit IDs were supplied, so this integration uses Auto ads; it does not invent display slot IDs or empty ad placeholders.

## After Google approves the site

1. Configure a Google-certified consent-management platform independently of the site's browser-preferences banner. The loader expects IAB TCF `window.__tcfapi` before it initializes; a later CMP can dispatch `ph:cmp-ready` after exposing that API. Missing or unsuccessful CMP decisions fail closed. The two environment flags alone cannot load ads without the CMP.
2. Review the CMP configuration for your audience, geography and applicable privacy requirements. For GDPR visitors this integration requires affirmative Google vendor 755 and purpose 1/3/4 consents. Outside GDPR it accepts the CMP's explicit `gdprApplies: false` decision. It does not implement a CMP, geographic detection, US-state privacy signals, or certification. Configure withdrawal behavior with the CMP, including page reload when needed to unload previously loaded tags.
3. Update the public privacy/cookie disclosures to describe the active provider and choices. Review the deployed CSP and permit the specific advertising/CMP hosts required by your chosen setup; actual ad delivery and consent UI must be verified on the deployed site.
4. Enable Auto ads for the site in AdSense. Preview ad density, mobile placement and exclusions. Exclude policy, settings, search, newsletter, admin and error pages in AdSense, including hash-based settings/search URLs. The loader also excludes utility hash routes at initialization and before a consent callback, and only runs on production domains. Once Auto ads is loaded, its placement/exclusion behavior is controlled by Google.
5. Set both flags to `true`, deploy, and inspect actual ad delivery, mobile layout shifts, consent accept/reject/withdraw paths and the browser console. Never click your own ads to test them.

To disable delivery, set `ADSENSE_ENABLED=false` and redeploy. `/api/ads-config` is uncached and is excluded from the service worker.
