# Google AdSense

Publisher: `ca-pub-1752666987448533`.

News section pages, article pages and the news archive include this script once in their HTML `<head>`:

```html
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-1752666987448533" crossorigin="anonymous"></script>
```

The homepage retains account verification metadata but does not load Auto ads, to avoid unfilled mobile ad placeholders. The matching account verification meta tag and `/ads.txt` DIRECT entry are also present. The former first-party loader, `/api/ads-config` endpoint and `ADSENSE_ENABLED` / `ADSENSE_CMP_READY` flags have been removed. The supplied script loads directly without those environment flags.

Ad approval, Auto ads, placements and privacy messages are managed in the Google AdSense account. This code does not establish approval or guarantee ad delivery. No manual ad-unit IDs have been supplied.

In AdSense, add or review `politicshub.in`, enable Auto ads when approved, and preview desktop/mobile placements. Configure Privacy & messaging for the site's audience, including a Google-certified CMP where required. The site's browser-preferences banner only controls local theme/cache storage and is separate from advertising consent.

Utility, legal and admin documents do not include the script. Configure Auto ads page exclusions for search/settings URLs as needed, including any hash routes on news pages. The script already loaded on a news page remains active during navigation within that document.

To verify deployment, inspect page source for one matching async script and confirm `/ads.txt` serves `google.com, pub-1752666987448533, DIRECT, f08c47fec0942fa0`. Browser checks can intercept the Google script request to validate loading without generating ad impressions. Check actual delivery in AdSense; never click your own ads.
