# Source reliability and reader cleanup — 31 October 2026

## Findings and changes

Some publisher descriptions contain entity-encoded HTML. The previous emergency
feed cleaner removed literal tags before decoding entities, leaving decoded
`<p class=...>` fragments in reader-facing summaries. Use a shared plain-text
cleaner for RSS ingestion, public API/article output, Quick Briefing and emergency
snapshots. Remove active markup, retain Unicode and article paragraph breaks,
and repair retained snapshot summaries without changing their publication dates.
Plain text takes a fast path without HTML parsing.

RSS, website monitoring, article enrichment and the licensed-image proxy used
automatic redirects; several read complete response bodies before slicing them.
They now share a streaming client that:

- rejects credentials, control characters, nonstandard ports and private,
  loopback, link-local, multicast and reserved destination addresses;
- checks hostname resolution before each request, including every redirect;
- confines configured RSS/website redirects to their permitted publisher hosts;
- refuses HTTPS downgrades and redirect loops, with at most five requests;
- checks a request deadline between redirects/chunks, limits decompressed bytes,
  and closes responses on success and failure;
- retains the configured runtime proxy, trusted CAs and TLS validation.

The image proxy reuses that client instead of a separate download loop. It only
serves supported raster formats, rejecting SVG/HTML, while retaining its existing
licensing requirement, cache policy and `nosniff`. Errors log the exception class
instead of upstream details. No database, billing or advertising changes.

This is scoped hardening, not a certification that every outbound client in the
repository is covered. DNS is validated before requests but is not pinned to the
connection; deployment egress controls remain necessary against DNS rebinding.
System DNS and an individual blocking connect/read can outlast a deadline before
control returns. Platform timeouts and network policy remain part of the boundary.

## Sources and new reader feature

Add the official BBC World RSS endpoint using the same attributed metadata-only
policy as the existing BBC India feed. A live check returned 34 reports; all 34
passed the existing public-excerpt gate. A local dry-run merge of those reports
with the existing 140-report snapshot retained 18 BBC World reports and 20 World
reports in total. This is a dry-run observation, not a permanent coverage promise.

The source directory now combines keyword search with Official/Publisher filters,
shows a clear empty state and resets both controls. References stay visible
without JavaScript. Its BBC reference links to the World headline feed.

`PYTHONPATH=. python scripts/check_sources.py --output artifacts/sources.json`
is a read-only diagnostic for enabled public RSS sources. It distinguishes
available, empty, undated, stale, future-dated and unavailable feeds without
database credentials, publication writes or exposing source query strings.

Observed checks during this release: 14 feeds, ten available with recent dates;
PIB Press Releases returned a valid empty feed, PIB Media Invitations an undated
entry, GovInfo Presidential Documents old entries, and Amar Ujala future dates.
Keep existing sources enabled pending repeated evidence; a single check is not
grounds for deleting a source or changing its reported publication time.

## Verification and rollback

230 Python tests run successfully (six optional isolated-PostgreSQL tests skipped
locally), all 24 JavaScript/Reel tests and 21 browser flows pass. Security checks
exercise private DNS, private redirects, host-boundary checks, credentials,
nonstandard ports, HTTPS downgrades, redirect caps/loops, slow streams, response
size bounds, response closure, active image rejection and text cleanup.
Browser checks combine source search/type filters, empty-state/reset behavior
with existing public, owner and offline flows.

No migration is required. Roll back by reverting the code commit and redeploying.
The normal source refresh workflows pick up the source configuration and repair
saved copy through their existing publication path; no new schedule is added.
