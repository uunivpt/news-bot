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

The registry is not a live-data service and does not infer charts from article
prose. A revised series requires a reviewed registry change. Corrections to the
article itself continue through the existing editorial correction workflow.

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
observations and the existing GDP chart. The desk contains all three six-year
charts, source links, exact-value tables and keyboard/touch tooltips. Everything
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
