const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const site = fs.readFileSync('public/assets/site.js', 'utf8');
const escapeLine = site.split('\\n').find(line => line.startsWith('const esc='));
const formatLine = site.split('\\n').find(line => line.startsWith('const articleInline='));
assert.ok(escapeLine && formatLine, 'Formatting helper should exist on the reader page');
const articleInline = vm.runInNewContext(escapeLine + '\\n' + formatLine + '\\narticleInline');

test('SPA reader renders markdown bold within article paragraphs', () => {
  assert.equal(articleInline('**Washington, November 9, 2026:** A car crash was reported.'),
    '<strong>Washington, November 9, 2026:</strong> A car crash was reported.');
  assert.equal(articleInline('Report by **Secret Service**.'), 'Report by <strong>Secret Service</strong>.');
  assert.match(site, /<p>\\$\\{articleInline\\(p\\)\\}<\\/p>/);
  assert.match(site, /<p class="dek">\\$\\{articleInline\\(it\\.summary\\)\\}<\\/p>/);
});
test('formatting never permits raw HTML injection', () => {
  assert.equal(articleInline('**A & B** <img src=x onerror=alert(1)>'),
    '<strong>A &amp; B</strong> &lt;img src=x onerror=alert(1)&gt;');
  assert.equal(articleInline('**** and **not closed'), '**** and **not closed');
  assert.equal(articleInline('** bold**'), '** bold**');
});
