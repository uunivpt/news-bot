# PoliticsHub UI and AdSense audit — 13 October 2026

## Changes

- Shared responsive typography, spacing, light/dark surfaces, article layouts and readable footers across public pages. The homepage layout also applies to category pages.
- Subtle hover, image and page transitions, with reduced-motion overrides. Native cursor retained; keyboard focus and skip links are visible.
- Article/static-page section menus now open a keyboard-accessible dialog instead of sending the reader home. Home/section search traps focus, restores the trigger and locks background scrolling.
- Science and Health are included in frontend routing; nonnumeric article fallback links return to the root application.
- Legacy article/story pages no longer call the removed `PH.bindChrome` interface. Standalone Google Analytics tags were removed to match the published privacy notice.
- Flask single-segment routing no longer redirects static HTML files to category 404s. `/admin/` explicitly serves the login UI.
- Article summaries are no longer truncated at 300 characters in the visible page. Machine-readable article dates also receive a readable localized display.
- Newsletter forms show pending feedback, prevent duplicate submissions and recover after failures. Browser delivery checks used intercepted requests; no test email was sent.
- Admin surfaces received mobile control sizes, table scrolling, focus indicators and reduced-motion support. Setup/legacy-console inline scripts moved into external assets so the existing CSP can execute them.
- Updated the service-worker cache version/assets and excluded private admin/console pages from caching.
- Added AdSense verification metadata for the publisher already in ads.txt, plus a first-party Auto ads loader. Ad serving defaults off while approval is pending and requires explicit deployment flags and a separate CMP. See [AdSense setup](ADSENSE_SETUP.md).

## Verification

- Live HTTP audit: homepage, India, Politics, World, Science, Health, archive, About, Privacy, Newsletter, ads.txt, robots.txt, search and newsletter availability endpoint returned 200 after redirects.
- Repository CI command: `python -m unittest discover -s tests -p 'test_*.py'` — 137 tests passed.
- Frontend/ad-loader regressions: `node --test tests/*.test.cjs` — 16 passed. CI now includes both frontend test files.
- Chromium: 31 routes × 360px, 768px and 1440px viewports = 93 checks, with no page JavaScript exceptions or document horizontal overflow. Tested both static and Flask-rendered home, all 10 categories, archive, public information/forms, diagnostics, author, generated article, both standalone stories, legacy story error state and admin login.
- Functional browser checks: home menu open/Escape, search results and focus return, load-more count, article menu open/Escape, dark theme, reduced motion, legacy story navigation, and mocked newsletter success/duplicate-submit behavior.
- Inspected desktop/mobile homepage, mobile article and dark settings screenshots.
- `git diff --check` passed.

## Limits and follow-up

AdSense approval is pending, as confirmed by the owner. Actual ad fill, revenue, Google's account policy status and a certified CMP were not available to test. Ads remain off; activation instructions cover the required account, disclosure, consent, CSP and placement checks.

Authenticated admin operations and real outbound newsletter delivery were not exercised. Private-page styling and public login rendering were checked. Article content and source claims were not independently fact-checked in this UI audit.

Running `pytest` without a test directory also collects the existing manual `scripts/test_instagram_direct.py`, which imports a removed `build_html_reel` function. The supported `tests/` suite and the repository's unittest CI command pass; that unrelated manual Instagram script was not changed.

Changes are prepared on a feature branch for review. This audit does not imply a production deployment.
