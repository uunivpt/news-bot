# PoliticsHub engagement analytics and Search Console audit (8 November 2026)

## Audit's zero score does not prove account configuration is missing

**GA4:** The repository already contains GA4 web measurement `G-2HVZQST08G` and the separate Google Ads destination `AW-18495731647`. Analytics is deliberately **consent-gated**. The original homepage did not load the consent bootstrap at all; this fix makes that local bootstrap available on homepage and public pages without firing an external Google tag until the Google CMP provides a valid consent signal. An automated scanner that does not complete a CMP flow can continue to report GA4 as "Not Detected". Use Tag Assistant and GA4 Realtime to verify events with a granted, appropriate consent state.

**Search Console:** PoliticsHub previously used domain property `sc-domain:politicshub.in`, which was reported connected/verified in October. Domain property verification is done with **DNS**, not an HTML `google-site-verification` tag. A scanner searching page HTML cannot determine ownership. The GSC Wizard connector currently rejects tool calls because its subscription is inactive, so current property access and verification cannot be rechecked from the connector.

Google Search Console verification can be checked in Search Console → select `sc-domain:politicshub.in` → Settings → Ownership verification. Preserve any existing verification DNS record; do not create a guessed tag/token or remove the DNS record.

If linking Analytics and Search Console is useful, use GA4 Admin → Product links → Search Console links, choose the already-verified domain property, and link the correct web data stream. This is an account-side action requiring appropriate owner/editor permissions.

**Important:** First-party theme, reading list, and local storage preferences are **not** analytics or advertising consent. A Google-certified advertising CMP remains a separate AdSense account requirement where applicable. Do not force Google tracking tags to load without the appropriate consent just to satisfy a generic SEO scanner.

Google references:
- https://support.google.com/webmasters/answer/9008080
- https://support.google.com/analytics/answer/14218557
- https://support.google.com/analytics/answer/10737381
