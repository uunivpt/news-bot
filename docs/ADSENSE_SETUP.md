# Google AdSense

Publisher: `ca-pub-1752666987448533`.

## Delivery and eligibility

`public/ads.txt` contains the matching DIRECT seller entry. Vercel serves it as
plain text; the verified apex domain redirects to `www.politicshub.in` with 308.
Keep HTTP and HTTPS reachable without a bot challenge. A Cloudflare rejection
before this redirect cannot be fixed inside Flask or vercel.json.

The homepage retains account-verification metadata. Homepage/section feeds,
archive, search/settings app routes, utility/legal/admin pages do not load Auto
ads. This also prevents a loaded Auto ads script from following client-side
navigation into screens without editorial content.

Dedicated article pages load one async AdSense script only after the separate
`app.monetization.is_monetizable` check. Search indexability alone does not enable
ads. An editor must inspect the full copy, independently verify its evidence,
confirm originality/rights and substantial added value, and approve the exact
copy using the authenticated admin workflow. This records a content fingerprint.
Source images also need recorded rights and credit; a source URL alone is not
permission. Changes to the reviewed copy invalidate eligibility; admin editing/reprocessing
also clears its approval and returns reviewed stories to pending. Old source
snapshots without these review records remain readable without ads. The existing
hand-authored standalone reports retain their explicit AdSense integration.

These checks are prerequisites, not a Google policy certification. Do not mark
source excerpts as original reporting or manufacture review flags. Attribution,
length, automated cross-source grouping and a source link alone do not establish
originality or republication rights. There is no official minimum article count
or word count that guarantees approval.

## Consent and measurement

Publish and enable the site's Google-certified European regulations message in
AdSense Privacy & messaging, including consent mode for Ads and Analytics as
appropriate. The AdSense tag deploys published Google messages. This repository
cannot configure the AdSense account or certify the live message's regional
behavior. Use `?fc=alwaysshow&fctype=gdpr` on a monetized article to preview a
published message; test actual regional behavior separately.

`public/assets/measurement.js` registers Google's `CONSENT_MODE_DATA_READY`
callback and waits before loading optional Google Ads/Analytics measurement.
Purposes must be GRANTED or NOT_APPLICABLE; UNKNOWN, NOT_CONFIGURED, missing or
denied values do not enable measurement. Analytics and advertising permissions
are independent. Repeated callbacks do not duplicate the tag or landing-page
conversion. Revocation updates consent and disables Analytics. A revocation
button is added when Google's supported consent API is available.

The site theme/cache banner is separate and never grants advertising consent.
If Google's CMP is absent, blocked or unconfigured, optional measurement stays
off. On non-monetized pages no AdSense tag is loaded to bootstrap messaging, so
measurement is also off there; the old homepage conversion does not fire merely
on a page load. Account approval, ad delivery and consent messaging remain
managed by AdSense. No manual ad-unit IDs have been supplied.

## Verification and operations

- Test `http(s)://politicshub.in/ads.txt` and both www variants. Expect the same
  seller entry and final HTTP 200, not a challenge or an HTML error page.
- Check Cloudflare Security Events for `/ads.txt` and `/robots.txt`, including
  Google requests. Change the rule responsible for the observed rejection;
  do not disable unrelated security or trust only a claimed User-Agent.
- AdSense status reflects the last crawl. Google documents days, or up to a
  month for low ad-request volume. Keep a valid file stable and use the status
  update control if offered. Do not delete/re-add the site to force a crawl.
- Compare the publisher ID with the actual account. Inspect rejection details;
  ads.txt detection and content approval are separate.
- Verify browser flows with third-party ads intercepted, never by clicking ads
  or generating production impressions as a test.

Official references:

- https://support.google.com/adsense/answer/7679060?hl=en
- https://support.google.com/publisherpolicies/answer/11190248?hl=en
- https://support.google.com/adsense/answer/13554116
- https://developers.google.com/funding-choices/fc-api-docs
