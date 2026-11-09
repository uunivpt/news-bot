const { test } = require('node:test');
const assert = require('node:assert/strict');
const { summarize, dashboard } = require('../public/assets/newsroom-ui.js');

const categories = [['all', 'Home'], ['india', 'India'], ['politics', 'Politics'], ['world', 'World']];
const matches = (item, category) => item.category === category || (category === 'politics' && item.political === true);

test('feed overview counts loaded reports and normalizes named publisher identities', () => {
  const items = [
    { id: 1, source: '  News Desk  ', category: 'india' },
    { id: 2, source: 'NEWS DESK', category: 'india', political: true },
    { id: 3, source: 'World Wire', category: 'world' },
    { id: 4, source: '   ', category: 'world' },
    { id: 5, category: 'india' }
  ];
  const original = JSON.stringify(items);
  const result = summarize(items, categories, matches);
  assert.equal(result.reports, 5, 'report totals describe loaded rows, not distinct publishers');
  assert.equal(result.publishers, 2, 'blank or duplicate publisher names must not inflate attribution counts');
  assert.equal(result.desks, 3);
  assert.deepEqual(result.coverage, [
    { key: 'india', label: 'India', count: 3 },
    { key: 'politics', label: 'Politics', count: 1 },
    { key: 'world', label: 'World', count: 2 }
  ]);
  assert.equal(JSON.stringify(items), original, 'overview computation must not rewrite feed data');
});

test('overlapping news desks use the site matcher instead of forcing exclusive categories', () => {
  const result = summarize([{ category: 'india', political: true, source: 'Desk' }], categories, matches);
  assert.equal(result.reports, 1);
  assert.equal(result.desks, 2);
  assert.equal(result.coverage.reduce((count, desk) => count + desk.count, 0), 2);
  const markup = dashboard([{ category: 'india', political: true }], categories, matches, category => '/'+category+'/');
  assert.match(markup, /A report can appear in more than one desk/);
  assert.match(markup, /Counts describe this loaded feed, not the complete archive/);
});

test('an empty feed has zero totals and finite empty coverage meters', () => {
  const result = summarize([], categories, matches);
  assert.equal(result.reports, 0);
  assert.equal(result.publishers, 0);
  assert.equal(result.desks, 0);
  assert.ok(result.coverage.every(desk => desk.count === 0));
  const markup = dashboard([], categories, matches, category => '/'+category+'/');
  assert.equal((markup.match(/<strong>0<\/strong>/g) || []).length, 3);
  assert.equal((markup.match(/--coverage:0%/g) || []).length, 3);
  assert.doesNotMatch(markup, /NaN|Infinity|undefined/);
});

test('dynamic dashboard labels and navigation attributes cannot inject HTML', () => {
  const label = 'News <img src=x onerror=alert(1)> & "updates"';
  const maliciousHref = '/india/?q=" onclick="alert(1)&next=<script>';
  const items = [{ source: '<script>publisher()</script>', category: 'unsafe' }];
  const markup = dashboard(items, [['all', 'Home'], ['unsafe', label]], () => true, () => maliciousHref);
  assert.ok(markup.includes('News &lt;img src=x onerror=alert(1)&gt; &amp; &quot;updates&quot;'));
  assert.ok(markup.includes('href="/india/?q=&quot; onclick=&quot;alert(1)&amp;next=&lt;script&gt;"'));
  assert.doesNotMatch(markup, /<img|<script|href="[^"]*" onclick=/);
  assert.doesNotMatch(markup, /publisher\(\)/, 'publisher text is used for counts, never inserted into dashboard HTML');
});

test('dashboard totals and per-desk coverage change with the supplied feed', () => {
  const short = dashboard([{ source: 'Wire', category: 'india' }], categories, matches, category => '/'+category+'/');
  const longer = dashboard([
    { source: 'Wire', category: 'india' },
    { source: 'Other newsroom', category: 'world' },
    { source: 'WIRE', category: 'world' }
  ], categories, matches, category => '/'+category+'/');
  assert.match(short, /<small>Reports<\/small><strong>1<\/strong>/);
  assert.match(longer, /<small>Reports<\/small><strong>3<\/strong>/);
  assert.match(short, /<small>Named sources<\/small><strong>1<\/strong>/);
  assert.match(longer, /<small>Named sources<\/small><strong>2<\/strong>/);
  assert.match(short, /--coverage:100%/);
  assert.match(longer, /--coverage:67%/);
  assert.ok(longer.includes('href="/world/"'));
});
