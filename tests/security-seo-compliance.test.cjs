const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const read = path => fs.readFileSync(path, 'utf8');

test('Vercel emits security headers for cached HTML and every path', () => {
  const configuration = JSON.parse(read('vercel.json'));
  const all = configuration.headers.find(item => item.source === '/(.*)');
  assert.ok(all, 'global response headers absent');
  const headers = Object.fromEntries(all.headers.map(x => [x.key.toLowerCase(), x.value]));
  assert.equal(headers['referrer-policy'], 'strict-origin-when-cross-origin');
  assert.equal(headers['x-content-type-options'], 'nosniff');
  assert.equal(headers['x-frame-options'], 'DENY');
  for (const path of ['/', '/:page.html', '/guides/:name.html', '/maharashtra/']) {
    const route = configuration.headers.find(item => item.source === path);
    assert.ok(route, 'static HTML route missing CSP: ' + path);
    const policy = route.headers.find(header => header.key === 'Content-Security-Policy')?.value || '';
    assert.match(policy, /object-src 'none'/);
    assert.match(policy, /base-uri 'self'/);
    assert.match(policy, /frame-ancestors 'none'/);
    assert.match(policy, /script-src 'self'/);
  }
});

test('non-SPA privacy banner cannot be mistaken for advertising consent', () => {
  const ui = read('public/assets/ui.js');
  assert.match(ui, /data-site-preference="essential"/);
  assert.match(ui, /data-site-preference="preferences"/);
  assert.match(ui, /Google advertising consent is separate/);
  assert.match(ui, /localStorage.setItem\('ph-consent-v1', choice\)/);
  new vm.Script(ui);
});

test('homepage H1 matches visible introductory text', () => {
  const home = read('public/index.html');
  assert.match(home, /<h1 id="news-home-title">Latest India and World News, Politics and Public Affairs<\/h1>/);
  assert.match(home, /Read the latest India and world news, politics and public affairs coverage/);
  assert.doesNotMatch(home, /What to check before sharing a headline/);
  assert.doesNotMatch(home, /How to read and verify our news coverage/);
});

test('a substantial source-first explainer is published, linked and discoverable', () => {
  const guide = read('public/guides/government-notifications.html');
  const body = guide.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, ' ').replace(/<[^>]*>/g, ' ');
  const words = body.trim().split(/\s+/);
  assert.ok(words.length >= 700, 'guide too thin: ' + words.length);
  assert.match(guide, /https:\/\/egazette.gov.in\//);
  assert.match(guide, /https:\/\/www.pib.gov.in\//);
  assert.match(guide, /https:\/\/indiacode.gov.in\//);
  assert.match(read('public/static-sitemap.xml'), /guides\/government-notifications.html/);
  assert.doesNotMatch(guide, /adsbygoogle.js/);
});
