const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const site = fs.readFileSync('public/assets/site.js', 'utf8');
const homepage = fs.readFileSync('public/assets/editorial-home.js', 'utf8');
const homeHtml = fs.readFileSync('public/index.html', 'utf8');

test('public publisher attribution survives direct normalization and cached rehydration', () => {
  const start = site.indexOf('function norm(a,i){');
  const end = site.indexOf('\nconst pick=', start);
  assert.ok(start >= 0 && end > start);
  const norm = new Function('newsCategory','newsPhoto', site.slice(start, end) + '\nreturn norm;')(
    category => category, () => ''
  );
  const one = norm({id:1,category:'india',title:'India public-affairs update',
                    source_name:'Original Publisher',summary:'Attributed summary'});
  assert.equal(one.source,'Original Publisher');
  assert.equal(one.summary,'Attributed summary');
});

test('exact repeated headlines are merged across independent feed IDs', () => {
  const start = site.indexOf('function norm(a,i){');
  const end = site.indexOf('\nconst pick=', start);
  const norm = new Function('newsCategory','newsPhoto',site.slice(start,end)+'\nreturn norm;')(cat=>cat,()=> '');
  const from = site.indexOf('function mergeFeeds(a,b){');
  const to = site.indexOf('\nasync function load(',from);
  assert.ok(from>=0 && to>from);
  const merge = new Function('norm','ts',site.slice(from,to)+'\nreturn mergeFeeds;')(
    norm, value=>Date.parse(value)||0
  );
  const rows=[
    {id:1,category:'india',title:'India regional civic policy announcement',source_name:'Publisher A',published_at:'2026-11-07T12:00:00Z'},
    {id:2,category:'india',title:'India regional civic policy announcement',source_name:'Publisher B',published_at:'2026-11-08T12:00:00Z'},
    {id:3,category:'world',title:'India regional civic policy announcement',source_name:'Publisher C',published_at:'2026-11-08T12:00:00Z'}
  ];
  const result=merge(rows,[]);
  assert.equal(result.length,2);
  assert.ok(result.some(row=>row.category==='india'&&row.source==='Publisher B'));
  assert.ok(result.some(row=>row.category==='world'&&row.source==='Publisher C'));
});

test('news UI does not label source-only excerpts as full original reports', () => {
  new vm.Script(site);
  new vm.Script(homepage);
  assert.match(homepage,/Read source-linked brief/);
  assert.match(homepage,/ph14-source-label/);
  assert.match(site,/Source-linked brief based on reporting from the named publisher/);
  assert.match(homeHtml,/<script\b[^>]*\bsrc="\/assets\/editorial-home\.js(?:\?[^"]*)?"/);
});
