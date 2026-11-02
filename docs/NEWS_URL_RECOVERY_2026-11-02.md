# News URL and archive recovery — 2 November 2026

## Cause and recovery

The rolling public feed and bundled archive did not contain historical records still present in Search Console. The old databases were not used by the GitHub-feed production runtime. A 503 notice was therefore shown for those IDs, despite their records still existing in historical Neon projects.

Recovered public snapshot history (1,162 snapshots) and read only already-published, public-source, non-Telegram stories from the three existing Neon projects. No project was modified, no historical tables were imported into politics 3, and no private admin fields were exported. Current nonpublished overrides were respected: 262 archived copies were excluded. The resulting deployment archive contains 16,707 stories, including the screenshot's ID 17484337268349.

## Stable public numbers and routes

Each internal ID receives a deterministic 12-digit public news number. It is stored in archive/feed exports and projected into public/admin APIs. Number collisions fail publication rather than serving an ambiguous article. Existing database primary keys are preserved; old IDs are retained as aliases when the same source record changes identity.

Canonical paths are /category/number. Both historical slug paths and raw internal-ID paths issue 301 redirects to the canonical path. Titles can be edited without changing the number. Category edits can change the category prefix; legacy category links still resolve by identity and redirect. The current www host remains the site's established canonical host.

Public articles display News No. Admin lists show the same number, numeric queue search resolves it, and read-only recovery search can find archived records by number. An authenticated owner can restore an absent public archive record to the existing database, with CSRF protection, before editing it in the existing inspector. Restoration does not establish fact checking or ad eligibility. It refuses to overwrite a live version.

The Vercel admin bridge still requires the phone backend to run compatible repository code and be reachable. We cannot authenticate as the user or certify the private live editor from an anonymous public request. Local automated checks cover owner search, restoration, duplicate refusal and missing-CSRF rejection.

## Indexing

Sitemaps now use numeric canonical paths. Existing quality/noindex rules remain: public availability is separate from editorial/search eligibility. Google chooses whether and when to index a URL; removal of noindex from every thin or withheld page would not establish quality or approval.

The GSC Wizard connector refused list_sites with payment_required/subscription_required. Search Console inspection and sitemap submission were not performed through this connector. A running trial or active GSC Wizard subscription and connected Google account are required; reconnect only if account authorization also needs renewal.

## Verification

All 16,707 archive numbers resolved locally; sampled archived pages returned 200 with the database unavailable. Explicit regression tests cover legacy category/slug redirects, numeric canonical rendering, identity persistence across title changes, ID aliases, collision refusal, owner archive restoration and CSRF enforcement. Full-suite and live deployment outcomes are reported separately.
