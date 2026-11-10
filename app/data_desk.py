"""Public statistical context built exclusively from the reviewed chart registry."""
from html import escape
from .article_visuals import catalog, number, render

LABELS = {
 'india-gdp-growth-2019-2024': 'GDP growth',
 'india-consumer-price-inflation-2019-2024': 'Consumer price inflation',
 'india-unemployment-2019-2024': 'Unemployment · ILO estimate',
}


def cards():
    parts = []
    for data in catalog():
        latest = data['points'][-1]
        parts.append(f'''<a class="data-index" href="/data/#{escape(data['id'])}">
<span>{escape(LABELS.get(data['id'], data['measure']))}</span>
<strong>{escape(number(latest['value']) + data['unit'])}</strong>
<small>{escape(latest['label'])} · latest in this series</small>
<span class="data-index-source">World Bank · Annual observations <b aria-hidden="true">↗</b></span></a>''')
    return '<div class="data-index-grid">' + ''.join(parts) + '</div>' if parts else ''


def highlights():
    data = catalog()
    return cards() + ('<div class="data-home-feature">' + render(data[0]) + '</div>' if data else '')


def page(origin):
    data = catalog()
    nav = ''.join(f'<a href="#{escape(d["id"])}">{escape(LABELS.get(d["id"],d["title"]))}</a>' for d in data)
    figures = ''.join('<div class="data-desk-figure" id="' + escape(d['id']) + '">' + render(d) + '</div>' for d in data)
    if not figures:
        figures = '<p>Reviewed datasets are temporarily unavailable. Please check back shortly.</p>'
    return f'''<!doctype html><html lang="en" data-theme="light"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>India Data Desk — GDP, inflation &amp; employment | PoliticsHub.in</title>
<meta name="description" content="Explore India GDP growth, consumer price inflation and unemployment with source-linked historical charts, exact values and observation dates.">
<link rel="canonical" href="{escape(origin)}/data/"><link rel="icon" href="/favicon.svg">
<link rel="stylesheet" href="/assets/site.css?v=phui23"><link rel="stylesheet" href="/assets/polish.css?v=phui30">
<link rel="stylesheet" data-article-data-style href="/assets/article-data.css?v=2">
<script src="/assets/ui.js?v=datadesk1" defer></script><script type="module" src="/assets/article-data.js?v=2"></script>
</head><body><header id="hd"><div class="top"><a class="logo" href="/"><img src="/favicon.svg" alt="PoliticsHub.in"></a><a class="data-home-link" href="/">Back to the newsroom ↗</a></div></header>
<main class="wrap data-desk"><div class="data-desk-intro"><p class="article-data-eyebrow">POLITICSHUB / THE DATA DESK</p>
<h1>Understand the numbers.<br><em>See the context.</em></h1><p>Explore the indicators behind the headlines. Original sources, clear definitions and exact values, together in one place.</p>
<div class="data-desk-scope"><span>India · 2019–2024</span><span>Annual historical observations</span><span>Reviewed 10 Nov 2026</span></div></div>
{cards()}<p class="data-desk-disclosure">These are the latest available observations in the reviewed six-year series, not live readings. Provider update and retrieval dates appear with each chart. The unemployment series is a modeled ILO estimate.</p>
<nav class="data-desk-nav" aria-label="Jump to an indicator">{nav}</nav>{figures}
<aside class="data-desk-method"><h2>How to read this desk</h2><p>Compare values within each chart. GDP growth, inflation and unemployment measure different things and should not be combined into a single score. Changes in rates are percentage points. Bar charts include zero; negative GDP growth appears below it.</p><p>Hover, tap or focus a bar to inspect a value. Expand the data table for the provider’s original precision. Historical datasets are checked before publication and can be revised by the source.</p><p><a href="/editorial-policy.html">Editorial policy</a> · <a href="/corrections.html">Request a correction</a></p></aside></main>
<footer><div class="wrap"><p>PoliticsHub.in · What matters, clearly.</p><p><a href="/">Latest stories</a> · <a href="/sources.html">Sources</a> · <a href="/contact.html">Contact</a></p></div></footer></body></html>'''
