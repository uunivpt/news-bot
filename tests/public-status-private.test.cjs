const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('public/assets/site.js', 'utf8');
const feedNotice = source.slice(source.indexOf('function updateFeedStatus(){'), source.indexOf("\ndocument.addEventListener('error'", source.indexOf('function updateFeedStatus(){')));

function noticeHarness(mode, existing = false) {
  const nodes = new Map();
  function element(tag) {
    return {
      tag, children: [], textContent: '',
      setAttribute(name, value) { this[name] = value; },
      append(node) { this.children.push(node); },
      prepend(node) { nodes.set(node.id, node); this.children.unshift(node); },
      before(node) { nodes.set(node.id, node); },
      replaceChildren() { this.children = []; },
      remove() { nodes.delete(this.id); }
    };
  }
  if (existing) { const box = element('div'); box.id = 'feedStatus'; nodes.set(box.id, box); }
  const main = element('main'); main.id = 'app';
  const context = vm.createContext({
    S: {mode},
    document: {getElementById: id => nodes.get(id), createElement: element, querySelector: () => main},
    refreshLatest: async () => {}
  });
  vm.runInContext(feedNotice, context);
  vm.runInContext('updateFeedStatus()', context);
  return {context, nodes};
}

test('healthy news delivery removes any public service notice', () => {
  for (const mode of ['api', 'snapshot']) {
    for (const existing of [false, true]) {
      const {nodes} = noticeHarness(mode, existing);
      assert.equal(nodes.has('feedStatus'), false, mode + ' must not show backend status');
    }
  }
});

test('loading and unavailable-story notices explain only what readers can do', () => {
  const loading = noticeHarness('loading').nodes.get('feedStatus');
  assert.equal(loading.children[0].textContent, 'Loading the latest stories…');
  assert.equal(loading.children.length, 1, 'loading does not offer a duplicate retry');
  for (const mode of ['cache', 'cached', 'empty']) {
    const notice = noticeHarness(mode).nodes.get('feedStatus');
    const text = notice.children.map(node => node.textContent).join(' ');
    assert.match(text, /previously loaded stories|Stories are temporarily unavailable/);
    assert.match(text, /Refresh news/);
    assert.doesNotMatch(text, /GitHub|Termux|database|PostgreSQL|API|system status/i);
  }
});

test('legacy settings status links expose reader preferences without service diagnostics', () => {
  const app = {innerHTML: ''};
  const settings = source.slice(source.indexOf('function settings(sub){'), source.indexOf('\nfunction render('));
  const context = vm.createContext({
    document: {documentElement: {dataset: {theme: 'light'}}},
    setActive() {}, preferencesAllowed: () => false, $: () => app
  });
  vm.runInContext(settings, context);
  vm.runInContext("settings('status')", context);
  assert.match(app.innerHTML, /Appearance/);
  assert.match(app.innerHTML, /Privacy choices/);
  assert.doesNotMatch(app.innerHTML, /System status|News API|News storage|News snapshot|GitHub|Termux/);
});

test('public footers and legacy debug entry no longer publish system status', () => {
  for (const file of ['index.html', 'about.html', 'contact.html', 'editorial-policy.html', 'corrections.html']) {
    const html = fs.readFileSync('public/'+file, 'utf8');
    assert.doesNotMatch(html, /href="(?:\/debug\.html|#\/settings\/status)"|System Status/i, file);
  }
  const debug = fs.readFileSync('public/debug.html', 'utf8');
  assert.match(debug, /http-equiv="refresh" content="0;url=\/admin\/"/);
  assert.doesNotMatch(debug, /assets\/status\.js|id="checks"|System status|api\//i);
});
