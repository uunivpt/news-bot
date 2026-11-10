const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const site = fs.readFileSync('public/assets/site.js', 'utf8');
const newsStart = site.indexOf('function newsPhoto(item){');
const newsEnd = site.indexOf('function img(item){', newsStart);
assert.ok(newsStart >= 0 && newsEnd > newsStart);
const newsPhoto = vm.runInNewContext(site.slice(newsStart, newsEnd) + '\nnewsPhoto', {URL});
const row = {
  image: 'https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Rahul_Gandhi.jpg/1200px-Rahul_Gandhi.jpg',
  image_source: 'wikimedia-commons',
  image_license: 'cc-by-sa-4.0',
  image_credit: 'Press photographer',
  image_source_url: 'https://commons.wikimedia.org/wiki/File:Rahul_Gandhi.jpg',
  image_license_url: 'https://creativecommons.org/licenses/by-sa/4.0/',
};
test('licensed Commons photo is permitted only with complete provenance', () => {
  assert.equal(newsPhoto(row), row.image);
  for (const [field, bad] of [
    ['image_source', 'unknown'], ['image_license', 'unknown'],
    ['image_source_url', 'https://example.com/fake'], ['image_credit', ''],
    ['image_license_url', 'javascript:alert(1)'], ['image', 'https://other.example/photo.jpg'],
  ]) assert.equal(newsPhoto({...row, [field]:bad}), '', field);
});
test('event photo claims are never made about Commons archive photographs', () => {
  const home=fs.readFileSync('public/assets/editorial-home.js','utf8');
  assert.match(home,/Archive photo — not this event/);
  assert.match(site,/Illustrative archive photo — not a photo of the reported event/);
  assert.match(site,/File source/);
  assert.match(site,/License/);
});
