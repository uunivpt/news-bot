const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const home = fs.readFileSync('public/index.html', 'utf8');
const contact = fs.readFileSync('public/contact.html', 'utf8');

test('homepage exposes substantive, non-padded editorial information', () => {
  const visible = home.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, ' ')
    .replace(/<[^>]*>/g, ' ').replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ').trim().split(' ');
  assert.ok(visible.length >= 650, 'too few visible source words: ' + visible.length);
  assert.match(home, /How to read and verify our news coverage/);
  assert.match(home, /A short source-linked brief is not the same thing as an independently investigated report/);
  assert.match(home, /href="\/guides\/government-notifications.html"/);
});

test('homepage attribution uses an organizational desk, never a fake person', () => {
  assert.match(home, /<meta name="author" content="PoliticsHub News Desk">/);
  assert.match(home, /By PoliticsHub News Desk/);
  const schema = JSON.parse(home.match(/<script type="application\/ld\+json">([^<]+)<\/script>/)[1]);
  const publisher = schema['@graph'].find(node => node['@type'] === 'Organization');
  assert.equal(publisher.email, 'politicshub.in@gmail.com');
  assert.equal(publisher.contactPoint.email, 'politicshub.in@gmail.com');
});

test('the homepage has discoverable contact and grounded social channels', () => {
  assert.match(home, /href="\/contact.html">Contact Us<\/a>/);
  assert.match(home, /mailto:politicshub.in@gmail.com/);
  for (const url of ['https://www.instagram.com/politicshubin/', 'https://t.me/politicshubin']) {
    assert.ok(home.includes(url), url);
    assert.ok(contact.includes(url), url);
  }
});

test('homepage contains a machine-visible consent placeholder but no misleading ad consent', () => {
  assert.match(home, /id="privacyConsent"[^>]+style="display:none"/);
  assert.match(home, /data-consent-choice="essential"/);
  assert.match(home, /do not grant consent to Google advertising/);
  const code = fs.readFileSync('public/assets/site.js', 'utf8');
  assert.match(code, /addEventListener\('load',\(\)=>showConsentBanner\(false\)\)/);
  assert.match(code, /if\(!force&&consentMode\(\)\)return/);
});
