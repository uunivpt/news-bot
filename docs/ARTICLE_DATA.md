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
