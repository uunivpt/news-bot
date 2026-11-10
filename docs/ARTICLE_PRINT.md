# Branded news print / PDF edition

The reader's **Print** button and the browser's **Print → Save as PDF** share
`public/assets/article-print.css` and `article-print.js`. The page starts with
the PoliticsHub logo/wordmark on the left, an explicitly labelled print time in
IST on the right, and the existing tagline beneath. The original source
publication timestamp remains with the headline and byline.

The browser print event temporarily places the article body immediately after
the heading. Images are contained rather than cropped and capped at 30 mm;
figures retain their values, source and readable axes. Article-sized
`break-inside: avoid` rules are relaxed, while individual figures and card rows
stay together. Long body paragraphs can flow across pages with widow/orphan
control. Navigation, sharing controls and unopened data-table controls are
omitted. Expanded data tables remain included. The screen DOM order is restored
after printing, including when the dialog is cancelled.

A4 is the default CSS page size. Native page-margin boxes supply the running
brand, timestamp, website tagline and page numbers; Chromium uses these instead
of its automatic title/date/URL header/footer. The first page has the larger
masthead, with no duplicate margin timestamp. Without JavaScript, canonical
pages still include the masthead and the correctly labelled source publication
time. No user account details or private metadata are added to the printout.

The shared chrome loads this helper for SPA articles; canonical article HTML
includes the stylesheet and fallback branding directly. Print animations and
dark backgrounds are reset without changing the screen layout or stored article.

## Validate

```sh
# Playwright Chromium and poppler-utils must be installed.
python scripts/article_print_browser_audit.py --output artifacts/article-print
```

The audit generates actual PDFs with browser headers enabled and background
graphics disabled, then uses `pdfinfo`/`pdftotext` to inspect pagination and text
positions. It covers a short illustrated report with a chart, a four-page report,
Marathi, an alternate browser timezone, dark mode, large reading text, A4/Letter,
SPA articles, no-JavaScript fallback, and restored screen order. Its source
articles and images are isolated fixtures, not published news.
