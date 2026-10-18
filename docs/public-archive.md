# Public news archive

The active Neon project is still the only write destination. Earlier Neon
projects remain untouched. Search and public article routes also read
`app/data/public-archive.json.gz`, a bundle of previously published public feed
records. This is separate from the rolling homepage feed.

Initial recovery on 2026-10-18 recovered 3,845 distinct source URLs from 510 Git
versions of `public/news-data.json`, including September records. Both older
Neon projects returned quota errors, so this recovery cannot establish that
all records in those databases were recovered. It contains only records that
were present in the public backups, with their saved bodies, IDs and dates.

To reproduce recovery with full Git history:

```sh
PYTHONPATH=. python scripts/recover_public_archive.py
```

The offline feed retains old and new published records before rotating its
140-story feed, and commits the archive alongside the feed. Vercel explicitly
bundles the archive with the Python API. Only allowlisted public fields are
retained. The primary database overrides saved records by both ID and URL;
unpublished primary records suppress archived copies. To remove an archived
record without a primary record, remove it from the archive in a reviewed
change; do not rerun historical recovery over intentional removals.

Search matches title, summaries, saved article body and source. It filters the
category before paginating with `limit` and `offset`; `X-Search-Total` reports
the match count. Similar headlines on different dates remain separate. The
browser's Load more stories button fetches subsequent pages. Existing SEO
quality gates still apply to sitemaps and the curated archive page.
