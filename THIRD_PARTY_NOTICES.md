# Third-Party Notices

Last reviewed: 7 October 2026.

This file records direct third-party dependencies and services used by PoliticsHub.in. Upstream license files and current vendor terms control if this notice conflicts with them.

## Runtime and application dependencies

- feedparser 6.0.11 — BSD-style open-source license. Preserve upstream notices when redistribution requires it.
- requests 2.32.5 — Apache License 2.0.
- beautifulsoup4 4.13.5 — MIT.
- psycopg 3.2.10 — LGPL family. Re-check obligations before redistributing a bundled binary or packaged desktop product.
- Flask 3.1.2 — BSD-3-Clause.
- Pillow 11.3.0 — Pillow/HPND-style license.
- gunicorn 23.0.0 — MIT.
- reportlab 5.0.1 — BSD-style license.
- websocket-client 1.8.0 — Apache License 2.0.

## Reel frontend dependencies

- React / React DOM 19.2.0 — MIT.
- TypeScript 5.9.3 — Apache License 2.0.
- @types packages from DefinitelyTyped — MIT.
- Remotion and @remotion packages 4.0.533 — source-available Remotion license, not an OSI-approved open-source license. As of the 30 September 2026 Remotion license FAQ, individuals and organizations of up to three people can generally use the Free License, including commercial automation, subject to the license terms. Re-check eligibility if the team grows or the product changes.
- @fontsource/barlow-condensed — package code under its package license; Barlow Condensed font files are distributed under the SIL Open Font License.
- Inter and Bricolage Grotesque web fonts — use their upstream open font licenses as distributed through Google Fonts.

## External services and APIs

- NewsAPI: production use requires an appropriate paid/production plan; the Developer plan is development-only. Terms also prohibit reproducing or republishing copyrighted material without permission. The NewsAPI source is therefore disabled in production until a suitable license is confirmed.
- NewsData.io: commercial API use is permitted by its published guidance, but it warns against republishing full article content and images. PoliticsHub ingestion is limited to title/short-description/source/date metadata and does not import NewsData images.
- Openverse: the API is used only as a discovery layer. Openverse requires compliance with the underlying work's license and does not guarantee that catalog licensing data is correct. PoliticsHub automated image selection is restricted to CC0/Public Domain Mark results and retains provenance metadata.
- Telegram public channel pages: automated collection is disabled. Telegram's current Content Licensing Terms prohibit scraping, indexing, harvesting or aggregation outside ordinary intended platform use except limited cases; re-enable only with a documented applicable exception or permission.
- Microsoft Phi-4 model: the upstream microsoft/phi-4 model is MIT-licensed. The configured PHI4_ENDPOINT may be operated by a separate inference provider; that provider's own API/hosting terms, privacy terms and data-retention settings must be reviewed before sending source material to it.
- Meta / Instagram Graph API: used to publish to a connected PoliticsHub account. Use remains subject to Meta Platform Terms, Developer Policies, data-use requirements, app review/verification requirements and current API restrictions.
- Cloudinary: used for hosting generated Reel video files. Upload only media for which PoliticsHub has sufficient rights.
- Google AdSense: advertising tags are disabled until an appropriate consent-management configuration is in place. Google requires a certified TCF CMP for personalized ads in the EEA, UK and Switzerland.
- Google Fonts: remote font delivery may expose normal connection metadata such as IP address and user agent to Google; disclosed in the Privacy/Cookie policies.
- Vercel: hosts the public site and may process operational request logs according to its service/privacy terms.
- GitHub Actions: runs newsroom automation and deployment workflows under GitHub's service terms.

## Content and asset policy

Unknown-license publisher photographs, thumbnails and video must not be published merely because they appear in a feed or article page. Public website images require explicit low-risk reuse permission. Reel image automation is restricted to public-domain/CC0-style assets. Where attribution-bearing legacy assets remain, the Reel caption includes recorded creator/license/source metadata.

The file public/politicshub-header.webp is not referenced by the current public code search. Its provenance should be documented or the file removed before any future use.

## Review cadence

Re-check vendor terms, license versions and direct dependencies before major releases, monetization changes, adding a new API, or changing the size/legal structure of the organization.
