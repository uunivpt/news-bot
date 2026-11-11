# Source-linked article charts

Articles can include metric cards, an interactive bar chart and an exact-value
table. Canonical pages render the complete figure without JavaScript. The legacy
SPA requests the same escaped renderer; tooltip enhancement needs no chart
library, database write, account, tracking request or third-party browser API.

## Editorial workflow

Add a dataset to `app/data/article-visuals.json` in a reviewed PR. It is bundled
by the existing Vercel `app/data/**` include rule.

1. Select existing internal story IDs in `article_ids`. Public news numbers are
   mapped automatically; story IDs and publication dates are never reassigned.
2. Retrieve permitted numerical data from its original provider. Record the
   provider page, exact data URL, licence, provider update date and retrieval
   date. Retain the response as review evidence. Do not use an image of a chart
   as verification of its values.
3. Supply 2–24 finite numeric observations in the intended order, with unique,
   short labels. Use the same measure, geography, unit and observation basis
   throughout a series. Missing readings are not zero; omit the chart until a
   coherent series is available. Do not compare a morning AQI observation with
   a 4 PM bulletin, mix AQI with PM2.5 concentration, or treat a forecast as an
   observed value.
4. Write a title, series, measure, unit, `difference_unit`, description and note.
   Explain historical context, rounding, revisions and any limitations. The
   latest/previous cards use the final two points; their difference is arithmetic
   in the declared difference unit (percentage points for percentage rates).
5. Set `reviewed: true` only after checking the data and the article association.
   Invalid, unreviewed or conflicting assignments produce no public figure.
   Articles without a matching approved dataset continue as ordinary text.

The registry does not infer charts from article prose or call remote services
while serving a page. New indicators, metric definitions and article associations
still require editorial review. The three existing annual WDI series now refresh
automatically under the source-validation rules below. Corrections to article
copy continue through the existing editorial correction workflow.

## Initial dataset

India GDP growth, World Development Indicators `NY.GDP.MKTP.KD.ZG`, country
`IND`, provider labels 2019–2024. Retrieved 10 November 2026; provider update
8 October 2026. Values retain the precision returned by the linked World Bank
API and are displayed to two decimals. It is historical context for the existing
India GDP/jobs article, not a new GDP estimate or an explanation of employment.
World Bank attribution and CC BY 4.0 link are displayed with the figure.

## Checks

```bash
python -m unittest discover -s tests -p test_article_visuals.py -v
python scripts/article_data_browser_audit.py --output artifacts/article-data
```

The browser audit uses local article/template fixtures and the reviewed dataset.
It checks canonical and SPA reading, source/precision/date preservation,
negative values, keyboard and touch tooltips, mobile/desktop layouts, both
themes, no-JavaScript reading, printing and navigation away from the article.

## Public Data Desk

`/data/` now makes the reviewed catalog discoverable from the homepage, public
navigation and static sitemap. The homepage shows the three latest annual
observations and the existing GDP chart. The desk contains the six newest published annual observations for each
indicator, source links, exact-value tables and keyboard/touch tooltips. Everything
on the desk except the tooltip works without JavaScript. No source API, private
database or Termux process is contacted while serving the charts.

The added World Bank indicators are `FP.CPI.TOTL.ZG` (consumer price inflation,
annual %) and `SL.UEM.TOTL.ZS` (unemployment, % of total labour force, modeled ILO
estimate). Both were retrieved and checked on 10 November 2026 from their linked
World Bank APIs, provider update 8 October 2026, for 2019–2024. Exact reviewed
observations and their provider URLs are preserved in the bundled registry.
These are historical annual observations; unemployment is not a PLFS release.
Changes smaller than 0.005 percentage points use three decimal places, so the
0.001-point unemployment change is not displayed as a zero change.

A `desk_only: true` dataset may have an empty `article_ids` list. It appears on
the public desk without being attached to an unrelated article. Missing,
unreviewed and conflicting entries still fail closed. New charts must keep the
same provenance and editorial checks described above; the screenshot AQI
numbers are not treated as verified observations.

Run `python scripts/data_desk_browser_audit.py` for homepage discovery, three
indicators, responsive layouts, touch/keyboard interactions, no-JavaScript
reading and the summary-request outage fallback.

## Article-specific visual storytelling

The main reader now derives **The story in numbers** from that article’s own
published copy using `app/story_visuals.py`. This is separate from the historical
registry. The unrelated homepage indicator dashboard is no longer promoted.
Existing `/data/` URLs remain available for readers who saved them.

* Named comparisons in the same unit become bar charts, e.g. regional sales in
  rupees/crore or party seat tallies. Figures remain attributed to the report.
* Clearly labelled two-column tables with year rows become line charts.
* Explicit share/distribution data becomes a pie chart only when the reported
  nonnegative percentages total 100. Partial shares remain comparisons; no
  “Other” category or missing remainder is created.
* Standalone quantities and explicitly labelled AQI/Nifty/Sensex figures become
  metric cards with the surrounding article wording. Dates alone are not data.
* Mixed units, mixed indicators, ranges and vague comparisons are not charted.
  Articles without suitable numerical data remain ordinary articles.

Example article copy (retain the actual source and observation context):

```text
Seat tally: Party A: 132 seats; Party B: 99 seats; Party C: 41 seats.

Vote share: Party A: 55%; Party B: 45%.

Year | GDP growth (%)
2022 | 7.6
2023 | 7.2
2024 | 7.1
```

The parser is deliberately conservative; it does not promise to understand every
sentence containing a number. It never imports unrelated World Bank observations
into a new article, calls an AI model, or writes to the story. HTML/table content,
Devanagari digits, escaped labels, exact reported table values and source links
are supported. Existing explicitly reviewed registry associations still work.
Canonical pages and the SPA share the server extractor and renderer. The SPA
chart endpoint resolves the corresponding existing public article and refuses
pending/rejected copy, including when the requesting reader is an administrator.
Its story-dependent response is private/no-store so subsequent edits cannot
leave a separately cached graph behind. Publication and editing workflows are
unchanged.

Run `python scripts/story_visuals_browser_audit.py` for bar, pie, line, index-card,
no-data, mobile/desktop, dark-mode, tooltip, exact-table, no-JavaScript and SPA
navigation checks. Fixtures are never published as real news.

## Downloading the figures

Each available article figure and reviewed Data Desk series offers **Download
figures (CSV)**. The ordinary download link works on canonical pages, legacy SPA
articles and without JavaScript; it requires no account or preference storage.

The UTF-8 CSV contains the same observations as the figure, units, measure,
report context and source attribution. Reviewed datasets retain full stored
provider precision, original data/licence links, provider update date and source
check date. Article figures retain reported numeric tokens (including Marathi
digits normalized by the existing extractor), the original publication field and
canonical article link. Source-check dates are not article publication dates.
An article export does not grant a new licence: original publisher rights apply.

`/api/data-desk/<dataset-id>/csv` exports only the validated registry catalog.
`/api/article-visuals/<article-id>/csv` resolves the existing public article and
uses the same conservative extractor as its figure. Omitted ranges and estimates
do not reappear as exact values. Missing figures and unpublished copy produce no
article-derived attachment, including for signed-in editors. Reviewed registry
downloads contain only the independently public dataset. Exports make no provider requests
or database writes and are private/no-store so edited figures cannot leave a
stale download behind. Spreadsheet formula-like text is escaped as text; validated
negative numeric observations retain their numeric value. Only figure context is
included; the raw article-body field and private editorial fields are not added.

Run `python -m unittest discover -s tests -p test_figure_downloads.py -v` and the
article-data, story-visuals and data-desk browser audits for download acceptance.


## Automatic annual-series refresh (10 November 2026)

The previous API URLs ended at 2024. An unrestricted check of the same WDI
source (source ID 2, India/IND) found published 2025 observations:

| Indicator | 2025 source value | Display |
| --- | ---: | ---: |
| GDP growth, `NY.GDP.MKTP.KD.ZG` | 7.56666179284244 | 7.57% |
| CPI inflation, `FP.CPI.TOTL.ZG` | 2.39884954182294 | 2.40% |
| Unemployment, modeled ILO, `SL.UEM.TOTL.ZS` | 4.219 | 4.22% |

All three responses reported `lastupdated: 2026-10-08`; independently retrieved
10 November 2026. Provider update date and observation year are different fields.
The six-point window now spans 2020–2025. IDs ending in `2019-2024` are stable
link/association identifiers, not the current observation range. Headings and
scope labels no longer hard-code that range.

Run `python scripts/refresh_economic_data.py` to check these exact sources:

- https://api.worldbank.org/v2/country/IND/indicator/NY.GDP.MKTP.KD.ZG?format=json&per_page=100&source=2
- https://api.worldbank.org/v2/country/IND/indicator/FP.CPI.TOTL.ZG?format=json&per_page=100&source=2
- https://api.worldbank.org/v2/country/IND/indicator/SL.UEM.TOTL.ZS?format=json&per_page=100&source=2

The `Refresh annual economic data` Actions workflow checks every six hours
(00:27, 06:27, 12:27, 18:27 UTC; 05:57, 11:57, 17:57, 23:57 IST), and can be
manually dispatched. GitHub schedules are best-effort and require the workflow on
the default branch. It publishes verified changes to main, using the existing
Vercel Git integration to deploy them. Public data endpoints cache for at most
five minutes after deployment. A new annual reading or historical revision is
published after the next successful check/deployment; instant or uninterrupted
provider availability is not promised.

Checks validate complete pagination, exact country/indicator/source identity,
release/observation dates, duplicate years, finite numeric rates and percentage
bounds. Null/unreleased years never become zero. Results are sorted by provider
year, retaining the six newest non-null observations at full source precision.
Older provider releases or a response whose newest observation predates the
stored newest observation are rejected. Historical
revisions within the displayed window are refreshed too. Publication dates and
article associations are preserved; an article's annual context can advance
independently of the original article text.

Each failed series retains its last good values and its last successful check
date. Other independently verified series can still update. Failures leave the
workflow visibly failed. The public desk and chart show successful check dates;
a check older than two calendar days displays an overdue warning saying a newer
release may be available. A recent check of an older observation is not called a
new observation. Each day records its successful verification date once; identical
checks on that date generate no commit/deployment. New values can publish within
the same day. This is separate from the news publication gates, and shares their
writer concurrency group to avoid push races.

These are annual WDI statistics. They do not replace MoSPI's latest quarterly GDP,
monthly CPI or PLFS unemployment releases, and the ILO modeled unemployment
measure must never be silently substituted for a PLFS survey result. News stories
and charts extracted from their published text retain their original reported
period; refreshing context must not rewrite historical reporting as current news.

Checks:

```bash
python -m unittest discover -s tests -p test_economic_data.py -v
python -m unittest discover -s tests -p test_article_visuals.py -v
python -m unittest discover -s tests -p test_data_desk.py -v
python scripts/data_desk_browser_audit.py --output artifacts/data-desk
python scripts/article_data_browser_audit.py --output artifacts/article-data
```

Frozen 2024 observations under `tests/fixtures/` exercise exact precision,
negative growth and tiny unemployment changes without tying automated refreshes
to last year's test expectations. Browser audits verify the actual bundled series.
