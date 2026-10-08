import {test} from 'node:test';import assert from 'node:assert/strict';import {fitText} from '../src/layout.mjs';
const measure=(s,z)=>[...s].length*z*.55;
for(const text of ['One word','A complete headline with several words','Very long headline '.repeat(100),'A'.repeat(1000),'मराठी बातमी आणि संपूर्ण संदर्भ'])test('Retains every character: '+text.slice(0,25),()=>{const r=fitText(text,880,750,138,9,measure);assert.equal(r.lines.join('').replace(/\s/g,''),text.replace(/\s/g,''));assert.ok(r.lines.length*r.size*1.08<=750.01);assert.ok(r.lines.every(l=>measure(l,r.size)<=880.01));});
test('Summary fits three lines without clipping',()=>{const r=fitText('The full summary must be preserved. '.repeat(25),880,440,90,3,measure);assert.ok(r.lines.length<=3);assert.ok(r.lines.every(l=>measure(l,r.size)<=880.01));});

import {readFileSync} from 'node:fs';
test('The first 1.5 seconds have a source-backed headline hook',()=>{
  const reel=readFileSync(new URL('../src/Reel.tsx',import.meta.url),'utf8');
  const start=reel.indexOf('{intro&&<>');
  const intro=reel.slice(start,reel.indexOf('</>}',start));
  assert.ok(start>=0);
  assert.match(intro,/data-opening-hook/);
  assert.ok(intro.includes('text={p.HEADLINE}'));
  assert.doesNotMatch(intro,/NEWS THAT/);
});
