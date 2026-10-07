import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {bundle} from '@remotion/bundler';
import {selectComposition,renderMedia,renderStill} from '@remotion/renderer';

const root=fileURLToPath(new URL('../',import.meta.url));
const propsPath=path.resolve(process.argv[2]||path.join(root,'story.json'));
const output=path.resolve(process.argv[3]||path.join(root,'out/reel.mp4'));
const p=JSON.parse(fs.readFileSync(propsPath,'utf8'));
for(const key of ['HEADLINE','CATEGORY','DATE','LOCATION','SOURCE','SUMMARY'])if(typeof p[key]!=='string'||!p[key].trim())throw Error(`${key} must be a nonempty string`);
for(const key of ['IMAGE','LOGO'])if(p[key]!=null&&typeof p[key]!=='string')throw Error(`${key} must be a URL, public-relative path, local file, or null`);
for(const key of ['AUDIO','DEBUG_SAFE'])if(p[key]!==undefined&&typeof p[key]!=='boolean')throw Error(`${key} must be a boolean`);

const mimeFor=(file)=>({'.png':'image/png','.webp':'image/webp','.gif':'image/gif','.svg':'image/svg+xml'}[path.extname(file).toLowerCase()]||'image/jpeg');
const normalizeAsset=(value)=>{
  if(!value||/^(https?:|data:|blob:)/.test(value))return value||null;
  const local=path.resolve(value);
  if(!fs.existsSync(local)||!fs.statSync(local).isFile())return value;
  return `data:${mimeFor(local)};base64,${fs.readFileSync(local).toString('base64')}`;
};
p.IMAGE=normalizeAsset(p.IMAGE);
p.LOGO=normalizeAsset(p.LOGO);
if(p.HEADLINE.length>220||p.SUMMARY.length>240)console.warn('Long copy: all text will fit, but may be too small or too fast to read. Editorial target: headline <= 140 chars, summary <= 180 chars.');
fs.mkdirSync(path.dirname(output),{recursive:true});
const serveUrl=process.env.REMOTION_SERVE_URL||await bundle({entryPoint:path.join(root,'src/index.tsx')});
const browserExecutable=process.env.CHROME_PATH||undefined;
const composition=await selectComposition({serveUrl,id:'PoliticsHubReel',inputProps:p,browserExecutable});
if(output.endsWith('.png')){
 await renderStill({serveUrl,composition,inputProps:p,output,browserExecutable,frame:Number(process.env.FRAME||180)});
}else{
 await renderMedia({serveUrl,composition,inputProps:p,outputLocation:output,codec:'h264',audioCodec:'aac',pixelFormat:'yuv420p',crf:18,browserExecutable,concurrency:Number(process.env.RENDER_CONCURRENCY||2),onProgress:({progress})=>{const pct=Math.round(progress*100);if(pct%10===0)process.stdout.write(`\rRendering ${pct}%`);}});
}
console.log(`\nSaved ${output}`);
