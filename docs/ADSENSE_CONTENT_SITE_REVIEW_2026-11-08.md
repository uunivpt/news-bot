# PoliticsHub: site content, UI, and AdSense integrity review — 8 November 2026

This is a scoped repository, public-snapshot, and website audit, **not** a Google AdSense approval, a factual-verification certificate, or a full publisher-by-publisher plagiarism analysis.

## Evidence inspected
- Public PoliticsHub homepage, editorial, privacy and source-reference pages.
- Connected `uunivpt/news-bot` GitHub source for publication, frontend, indexing, and ads eligibility.
- Repository snapshots `public/news-data.json` (140 English entries) and `public/hindi-news.json` (100 Hindi entries), sampled 8 November 2026. Both were overwhelmingly RSS headline/excerpt entries with no independently written full article body in the snapshot; they should be described as **source-linked feeds** and not advertising-ready original reports.
- The English snapshot contained two repeated-title groups; the reader deduplicates exact headline/category copies without merging unrelated, similar headlines.
- Site routes such as `/archive/` and `/briefing/` are dynamic, so an absent physical `public/archive/index.html` is not evidence of a 404.

## Changes made
1. Preserve RSS `source_name` through article/card normalization so publishers receive accurate attribution even after cached hydration.
2. Merge exact duplicate headlines across separate feed IDs while preserving distinct category stories.
3. Rename the homepage lead action **Read source-linked brief**, and show the originating publisher.
4. Add explicit reader-article and server-rendered article disclosures that source-derived copy is not original PoliticsHub reporting.
5. Keep one consistent robots meta directive per server-rendered article and add `isBasedOn` to NewsArticle JSON-LD when the source URL is present.
6. Mark unreviewed, source-only RSS summaries `noindex,follow`. Readers can still browse them; verified/curated articles can be indexed under the existing checks.
7. Reject substantially repeated sentence blocks from ad eligibility even if long form and a review note are present. This is a **negative quality screen**, not a positive originality score.
8. Keep existing human review, exact-content hash, evidence, image-rights and sensitive-coverage advertising safeguards.
9. Update responsive source-label styling and cache-bust changed frontend assets. Regression tests cover feed attribution, duplicates, meta directives and ads eligibility.

## Google policy implications
Google Publisher Policies prohibit monetizing copied or automatically rewritten material without added original value. Pure publisher headlines/excerpts are not transformed into independently reported stories just by attribution. Public-interest journalism on controversial topics is not automatically prohibited; use page-level advertising suitability decisions, avoid graphic or harmful material, and retain factual source links.

Official references:
- https://support.google.com/publisherpolicies/answer/11190248
- https://support.google.com/adsense/answer/10008391
- https://developers.google.com/search/docs/fundamentals/creating-helpful-content

## Still requiring human/account-side work
- **Originality and factual verification:** individually compare final stories with their original sources, confirm added analysis and material claims, and verify image permissions. No honest 80%-originality rating can be inferred from source-linked feeds.
- **AdSense account:** Google-certified advertising CMP for covered regions, site approval, identity/payment eligibility and Policy center review require authorized account actions.
- **Live browser audit:** Validate responsive layout, actual Core Web Vitals, all live article URLs and CMP interaction using controlled browser sessions; public web retrieval does not consistently fetch dynamic routes.
- **Indexed URL count:** review in Search Console. Third-party simulated metrics are not verified indexing measurements.

Do not invent authors or citations, bulk-generate filler 700-word reports, purchase backlinks, or delete legitimate factual news simply for mentioning restricted topics. Publish genuinely original explainers with clear source evidence instead.
