# Quick Briefing — 31 October 2026

## Product decision

PoliticsHub already has a newsletter, saved stories, search and source guides.
The homepage presents a long chronological feed; it did not offer a bounded
catch-up view. The public snapshot inspected for this change contained 140
reports (127 India, 12 Politics, one World), so pure chronological selection
could easily bury the smaller desks.

Add `/briefing/`: up to six recent source-linked reports. Select the newest
available story per desk first, then fill remaining places by recency. Readers
can choose India, Politics, World or Hindi, and 24 hours or seven days. This is
a reading aid, not an editorial claim that these are the six most important
stories or an exhaustive search of the archive. The latest 200 available
published reports for the selected desk bound the selection.

## Delivery

- Server-rendered text, filters and links work without JavaScript or an account.
- Reuses the existing published-feed/database-outage snapshot path.
- Excludes unpublished, private-source, missing-date, future and out-of-window
  records. Deduplicates IDs and original source URLs.
- Keeps publication dates, source attribution and direct original-source links.
  Source HTML becomes plain-text excerpts; no new factual claims are generated.
- Empty/stale feeds stay empty with an explicit look-back/archive action.
- Homepage and menus link to the briefing. Existing page analytics can measure
  visits to `/briefing/`; no new tracking or email delivery is introduced.
- Utility page uses `noindex,follow`; filtered variants share its canonical URL.
  Anonymous responses have a short public cache lifetime; owner sessions retain
  the existing private/no-store policy.
- Vercel includes the new HTML template and rewrites both briefing URL forms.

## Validation

212 Python tests run successfully, six skipped because optional isolated
PostgreSQL integration fixtures are not configured here. All 24 JavaScript/Reel
tests and 21 browser flows pass. New checks cover selection windows, desk
representation, duplicates, markup cleanup, source links, escaped content,
snapshot failure/staleness, authenticated caching, no-JavaScript reading,
filter submission and mobile/desktop widths. Existing public, owner and offline
browser flows also pass. Tests do not use production credentials or send mail.

## Next measurement

Compare briefing visits and subsequent report-page navigation with homepage
navigation after enough real traffic accumulates. No retention or conversion
uplift is claimed from implementation alone. Database/provider capacity remains
an independent dependency for subscriptions and owner writes.

Rollback: revert the feature commit and redeploy. No schema or data migration.
