# AdSense and ads.txt audit — 2 November 2026

Scope: current checked-out source, live HTTP responses, five sampled sitemap articles, and official Google guidance. No production changes, Cloudflare configuration changes, account actions, or deployment were performed. This is not certification of every article, legal compliance, or approval eligibility.

## Findings

1. **ads.txt contents and origin delivery pass.** `public/ads.txt` contains `google.com, pub-1752666987448533, DIRECT, f08c47fec0942fa0`. `vercel.json` sets plain-text content type and a one-hour cache. Flask GET and HEAD both return 200. The homepage uses the matching publisher ID. Account ownership still needs an AdSense-account check.
2. **Root-domain access differs by User-Agent.** Live `https://politicshub.in/ads.txt` returns Cloudflare 403 / error 1010 for Python-urllib, but browser, Googlebot, Mediapartners-Google and AdsBot-Google name strings reach the www file with 200. The www file also works for Python-urllib. This establishes an edge filtering difference, not proof of a real Google crawler failure. Inspect Cloudflare Security Events and actual crawler logs; correct the matching rule for ads.txt and robots.txt without disabling unrelated protection. Repository changes alone cannot repair an upstream Cloudflare rejection.
3. **The screenshot reports an older crawl.** Its status is Getting ready, ads.txt Not found, last updated 28 October. Google documents several days and, for low ad-request volume, up to a month for updates. Current successful requests do not establish what happened on 28 October. Do not delete/re-add the site or repeatedly rewrite a valid file merely to trigger an update.
4. **High-priority monetization eligibility gap.** `api/index.py::_article_html` uses `app/seo_indexing.py::is_indexable` to decide whether to load AdSense. That predicate checks source identity, URL, dates and text length, but does not establish original reporting, editorial review or added value. A reproducible row whose entire article equals its summary passes the predicate and loads AdSense. All five live sampled articles displayed the same source-derived paragraph as lead and body. This is a substantial replicated/low-value-content risk, not a confirmed historical rejection reason.
5. **Extractive generation is explicit.** `app/newsroom.py::make_summary` copies selected source sentences; `make_article` groups selected sentences beneath labels. Labels and attribution do not themselves establish substantial added value or republication rights. Review source licenses and add actual reporting, useful contextual analysis or substantive reviewed curation before monetizing these pages. Search indexability and monetization eligibility should be separate decisions; length alone must not certify either originality or quality.
6. **Consent needs account/browser verification.** `public/assets/ui.js` initializes Google Analytics and Google Ads tags before reading site-preference consent. AdSense loads directly from document heads. The local preferences banner explicitly controls local storage only. Confirm a Google-certified CMP for personalized advertising in EEA/UK/Switzerland and verify consent behavior in the affected regions. Absence of CMP code in the repository does not prove an account-managed Google message is absent.
7. **Operational docs are stale.** `docs/ADSENSE_SETUP.md` says the archive loads ads and the homepage does not. Current source/tests do the opposite: homepage has the script; archive does not. Update this documentation before relying on it for release checks.

## Verification

- Python compilation passed for app, api, scripts and run.py.
- Python suite: 319 tests, OK, 6 skipped; skipped provider checks are not verified here. Existing unclosed-file ResourceWarnings appeared.
- JavaScript suite: 17 passed.
- Syntax checks: 18 JavaScript files passed.
- Validity of existing tests does not establish Google policy compliance. The synthetic identical-summary/body case passes current code despite the editorial-value gap.

## Recommended order

1. Inspect/fix root-domain Cloudflare filtering; verify real Google access with logs.
2. Keep the valid ads.txt stable and use AdSense's status-update control if offered.
3. Separate monetization from SEO eligibility; review source-derived content and restrict ads to editorially eligible pages. Do not manufacture review flags or filler.
4. Verify regional advertising/measurement consent in browser and AdSense settings.
5. Compare the exact previous rejection message before attributing its cause. Approval cannot be guaranteed by code changes.

## Official references

- https://support.google.com/adsense/answer/7679060?hl=en
- https://support.google.com/adsense/answer/12170222?hl=en
- https://support.google.com/publisherpolicies/answer/11190248?hl=en
- https://support.google.com/adsense/answer/7299563?hl=en
- https://support.google.com/adsense/answer/13554116

## Code remediation

The subsequent change separates monetization from indexability, records full-copy
review fingerprints through the authenticated approval flow on both remote and
local admin, blocks repeated-summary monetization, invalidates review on editing
or reprocessing, removes Auto ads from client-side feed/utility navigation, fixes
multiline evidence input parsing, and moves optional measurement behind Google's
CMP callback. Account-managed CMP deployment and Cloudflare edge filtering remain
external configuration checks. See ADSENSE_SETUP.md for current behavior.

## Remediation validation

- Full Python suite with local PostgreSQL 18: 326 tests passed, none skipped.
  This includes an isolated real-PostgreSQL create → approve → publish → edit flow.
  That flow exposed and fixed a pre-existing PostgreSQL `RETURNING id` dictionary
  lookup bug in manual story creation that SQLite did not reveal.
- JavaScript suites: 30 tests passed, including consent denial/grant,
  independent measurement purposes, withdrawal and multiline evidence URLs.
- Browser fixture: 23 checks passed across mobile/tablet/desktop, including the
  consent-to-network boundary with Google requests intercepted. This does not
  certify an actual account-managed CMP or real geographic behavior.
- Syntax checks: 19 JavaScript files; Python compilation and diff whitespace
  checks passed. No production database or real mail/ad delivery used.

The full-copy approval workflow also rejects repeated summaries; source-image
URLs without recorded image rights do not authorize monetization. Summary-only
reports are excluded from discovery XML. Optimistic editor revisions now include
body, image and approval state to detect concurrent changes to reviewed copy.
