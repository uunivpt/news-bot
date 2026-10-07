import React, {useEffect, useMemo, useState} from 'react';
import '@fontsource/barlow-condensed/700.css';
import {AbsoluteFill, Audio, Img, continueRender, cancelRender, delayRender, staticFile, useCurrentFrame} from 'remotion';
import {fitText} from './layout.mjs';

export type Story = {HEADLINE:string; IMAGE?:string|null; CATEGORY:string; DATE:string; LOCATION:string; SOURCE:string; SUMMARY:string; AUDIO?:boolean; LOGO?:string|null; DEBUG_SAFE?:boolean};
const W=880, LEFT=88, WHITE='#FFFFFF', GREY='#8A8A8A', RED='#FF2D2D';
const asset=(path:string)=>/^(https?:|data:|blob:)/.test(path)?path:staticFile(path.replace(/^\//,''));
const clamp=(n:number)=>Math.min(1,Math.max(0,n));
const ramp=(f:number,start:number,duration:number)=>clamp((f-start)/duration);
const ease=(n:number)=>1-Math.pow(1-clamp(n),3);
const hash=(n:number)=>{const x=Math.sin(n*127.1+311.7)*43758.5453;return x-Math.floor(x);};

// Block captures until the bundled font and optional media have settled.
function useAssets(image?:string|null,logo?:string|null){
  const [handle]=useState(()=>delayRender('Load brand font and optional images'));
  const [ready,setReady]=useState(false);
  const [resolved,setResolved]=useState<{image:string|null;logo:string|null}>({image:null,logo:null});
  useEffect(()=>{let active=true;const effectHandle=delayRender('Resolve updated story assets');setReady(false);
    const loadImage=async(path?:string|null):Promise<string|null>=>{
      if(!path)return null;
      return new Promise(resolve=>{const im=new window.Image();const timer=setTimeout(()=>{im.src='';resolve(null);},8000);im.onload=()=>{clearTimeout(timer);resolve(asset(path));};im.onerror=()=>{clearTimeout(timer);resolve(null);};im.src=asset(path);});
    };
    (async()=>{
      if(document.fonts?.ready) await document.fonts.ready;
      const [img,mark]=await Promise.all([loadImage(image),loadImage(logo)]);
      if(active){setResolved({image:img,logo:mark});setReady(true);continueRender(effectHandle);continueRender(handle);}
    })().catch(err=>cancelRender(err));
    return()=>{active=false;continueRender(effectHandle);};
  },[image,logo,handle]);
  return {ready,...resolved};
}
let measureContext:CanvasRenderingContext2D|null=null;
function measure(text:string,size:number){
  const ctx=measureContext??(measureContext=document.createElement('canvas').getContext('2d')!);
  ctx.font=`700 ${size}px "Barlow Condensed"`;return ctx.measureText(text).width;
}
function TextBlock({text,width=W,height=760,maxSize=136,maxLines=9,kinetic=false,start=120,color=WHITE}:{text:string;width?:number;height?:number;maxSize?:number;maxLines?:number;kinetic?:boolean;start?:number;color?:string}){
  const f=useCurrentFrame();
  const fit=useMemo(()=>fitText(text,width,height,maxSize,maxLines,measure),[text,width,height,maxSize,maxLines]);
  const total=text.trim().split(/\s+/).length; let index=0;
  // All words are present from the first headline frame; a readable base stays visible under each punch.
  return <div data-text-block style={{fontSize:fit.size,lineHeight:1.08,color,fontWeight:700}}>{fit.lines.map((line:string,li:number)=><div key={li} style={{whiteSpace:'pre',position:'relative'}}>{line.split(' ').map((word:string,wi:number)=>{
    const n=index++;const at=start+Math.floor(n/Math.max(1,total-1)*Math.min(90,total*5));
    const p=ramp(f,at,9);const pulse=kinetic&&f>=at&&f<at+9;
    return <React.Fragment key={wi}>{wi>0?' ':''}<span style={{position:'relative',display:'inline-block'}}>{word}{pulse&&<span aria-hidden style={{position:'absolute',left:0,top:0,opacity:(1-p)*.8,transform:`scale(${1.13-.13*ease(p)}) translateY(${(1-p)*-8}px)`,filter:`blur(${(1-p)*2}px)`,transformOrigin:'50% 70%'}}>{word}</span>}</span></React.Fragment>;
  })}</div>)}</div>;
}
function Mark({logo}:{logo:string|null}){return logo?<Img src={logo} style={{width:250,height:250,objectFit:'contain'}}/>:<svg width="250" height="250" viewBox="0 0 250 250" fill="none" aria-label="PH monogram concept">
  <path d="M52 90H198M69 82C72 48 98 31 125 31C152 31 178 48 181 82M125 31V15M115 15H135M52 96V105H198V96" stroke="white" strokeWidth="8"/>
  <path d="M61 187V122H87C119 122 119 160 87 160H62M139 122V187M190 122V187M139 153H190" stroke="white" strokeWidth="12"/>
  <path d="M33 201C83 225 171 225 217 185" stroke="white" strokeWidth="7" strokeLinecap="round"/>
</svg>;}
function Brand({logo,large=false}:{logo:string|null;large?:boolean}){return <div style={{textAlign:'center'}}><Mark logo={logo}/><div style={{fontSize:large?100:86,lineHeight:1,marginTop:20}}>Politics<span style={{color:GREY}}>Hub</span></div><div style={{fontSize:24,color:GREY,letterSpacing:6,marginTop:24}}>INDEPENDENT NEWS</div></div>;}
function Abstract({frame}:{frame:number}){return <AbsoluteFill style={{background:'#000',overflow:'hidden'}}>
  <AbsoluteFill style={{opacity:.26,backgroundImage:'linear-gradient(#363636 1px, transparent 1px),linear-gradient(90deg,#363636 1px,transparent 1px)',backgroundSize:'100px 100px',transform:`perspective(1100px) rotateX(12deg) scale(1.4) translateY(${frame*.18}px)`}}/>
  <AbsoluteFill style={{background:`radial-gradient(ellipse at ${30+Math.sin(frame/90)*25}% 40%,#3339,transparent 65%)`}}/>
  {Array.from({length:34},(_,i)=><div key={i} style={{position:'absolute',left:hash(i)*1080,top:(hash(i+70)*2200-frame*(.25+hash(i+90)) +2200)%2200-140,width:i%7===0?3:2,height:i%7===0?3:2,background:'#aaa',opacity:.1+hash(i+22)*.35}}/>)}
  {[0,1,2].map(i=><div key={i} style={{position:'absolute',width:900,height:2,left:-300+(frame*3+i*380)%1600,top:400+i*390,background:'linear-gradient(90deg,transparent,#aaa5,transparent)',transform:'rotate(-28deg)'}}/>)}
</AbsoluteFill>;}
function Grain({frame}:{frame:number}){return <svg style={{position:'absolute',inset:0,width:'100%',height:'100%',opacity:.045,pointerEvents:'none',mixBlendMode:'screen'}}><filter id="grain"><feTurbulence type="fractalNoise" baseFrequency=".73" numOctaves="2" seed={Math.floor(frame/3)%19}/><feColorMatrix type="saturate" values="0"/></filter><rect width="100%" height="100%" filter="url(#grain)"/></svg>;}
export const Reel:React.FC<Story>=(p)=>{
  const raw=useCurrentFrame(), f=Math.min(raw,510);
  const a=useAssets(p.IMAGE,p.LOGO);
  if(!a.ready)return <AbsoluteFill style={{background:'#000'}}/>;
  const intro=f<45, category=f>=45&&f<120, headline=f>=120&&f<300, summary=f>=300&&f<450, credit=f>=450&&f<480, outro=f>=480;
  const glitch=[45,120,300,450,480].some(at=>f>=at&&f<at+2);
  const shake=intro&&f>=8&&f<20?Math.sin(f*2.3)*6*(1-ramp(f,8,12)):outro&&f<488?Math.sin(f*2)*4*(1-ramp(f,480,8)):0;
  return <AbsoluteFill style={{background:'#000',color:WHITE,fontFamily:'"Barlow Condensed",sans-serif',fontWeight:700,overflow:'hidden'}}>
    <Abstract frame={f}/>
    {a.image&&headline&&<AbsoluteFill style={{transform:`scale(${1.04+ramp(f,120,180)*.1}) translateY(${-ramp(f,120,180)*25}px)`}}><Img src={a.image} style={{width:'100%',height:'100%',objectFit:'cover',filter:'grayscale(1) contrast(1.3) brightness(.52)'}}/><AbsoluteFill style={{background:'linear-gradient(180deg,#000b 0%,#0003 22%,#0009 52%,#000e 80%,#000 100%)'}}/></AbsoluteFill>}
    <AbsoluteFill style={{background:'radial-gradient(ellipse at center,transparent 30%,#000b 100%)'}}/>
    {intro&&<>
      <AbsoluteFill style={{background:`linear-gradient(112deg,transparent ${-50+f*5}%,#ffffff12 ${-42+f*5}%,transparent ${-30+f*5}%)`}}/>
      <div style={{position:'absolute',top:630,left:88,width:880,opacity:ease(ramp(f,5,10)),transform:`translateX(${shake}px) scale(${1.035-.035*ease(ramp(f,8,15))})`}}><Brand logo={a.logo} large/></div>
    </>}
    {(category||headline||summary)&&<>
      <div style={{position:'absolute',left:LEFT,top:292,width:W,transform:category?`translateY(${-28*(1-ease(ramp(f,45,7)))}px) scale(${1+.12*(1-ease(ramp(f,45,7)))})`:'none',transformOrigin:'left top'}}>
        <div style={{display:'inline-block',background:RED,padding:'10px 24px 13px',maxWidth:W}}><TextBlock text={p.CATEGORY.toUpperCase()} width={W-48} height={98} maxSize={38} maxLines={2}/></div>
        <div style={{marginTop:24,color:GREY,opacity:ramp(f,53,10),transform:`translateX(${40*(1-ease(ramp(f,53,10)))}px)`}}><TextBlock text={`${p.DATE}  /  ${p.LOCATION}`} width={W} height={112} maxSize={29} maxLines={3} color={GREY}/></div>
      </div>
    </>}
    {category&&<div style={{position:'absolute',left:LEFT,top:810,width:W,opacity:ease(ramp(f,63,14))}}><div style={{height:1,width:100,background:GREY,marginBottom:32}}/><div style={{fontSize:105,lineHeight:.96}}>WHAT MATTERS,<br/><span style={{color:GREY}}>CLEARLY.</span></div><div style={{fontSize:26,color:GREY,letterSpacing:4,marginTop:40}}>POLITICSHUB.IN</div></div>}
    {headline&&<div style={{position:'absolute',left:LEFT,top:610,width:W,transform:`translateY(${-ramp(f,120,180)*12}px)`}}><TextBlock text={p.HEADLINE} kinetic height={750} maxSize={138}/><div style={{width:90,height:3,background:WHITE,marginTop:38}}/></div>}
    {summary&&<>
      <div style={{position:'absolute',left:LEFT,top:635,fontSize:25,color:GREY,letterSpacing:4}}>THE ESSENTIALS</div>
      <Summary text={p.SUMMARY} frame={f}/>
      {[0,1,2,3].map(i=><div key={i} style={{position:'absolute',left:i%2===0?64:972,top:i<2?590:1250,width:24,height:24,borderLeft:i%2===0?'2px solid #8A8A8A':undefined,borderRight:i%2===1?'2px solid #8A8A8A':undefined,borderTop:i<2?'2px solid #8A8A8A':undefined,borderBottom:i>=2?'2px solid #8A8A8A':undefined}}/>)}
      <div style={{position:'absolute',left:LEFT,top:1380,width:W,height:3,background:'#333'}}><div style={{width:`${ramp(f,300,149)*100}%`,height:3,background:WHITE}}/></div>
    </>}
    {credit&&<div style={{position:'absolute',left:LEFT,top:750,width:W,opacity:ease(ramp(f,450,5))}}><div style={{fontSize:27,color:GREY,letterSpacing:4,marginBottom:28}}>SOURCE / CREDIT</div><TextBlock text={p.SOURCE} height={430} maxSize={70} maxLines={5}/></div>}
    {outro&&<div style={{position:'absolute',left:LEFT,top:570,width:W,textAlign:'center',opacity:ease(ramp(f,480,6)),transform:`translateX(${shake}px)`}}><Brand logo={a.logo} large/><div style={{fontSize:44,marginTop:55}}>What matters, clearly.</div><div style={{fontSize:33,color:GREY,marginTop:26}}>@politicshub.in</div></div>}
    <Grain frame={f}/>
    {glitch&&<><div style={{position:'absolute',top:550+(f%3)*145,left:0,width:'100%',height:5,background:RED,opacity:.8}}/><div style={{position:'absolute',top:1040,left:30,width:880,height:2,background:WHITE,opacity:.5}}/></>}
    {p.DEBUG_SAFE&&<div style={{position:'absolute',left:64,right:64,top:250,bottom:350,border:'2px dashed #8A8A8A',pointerEvents:'none'}}/>}
    {p.AUDIO!==false&&<Audio src={staticFile('pulse.wav')}/>}
  </AbsoluteFill>;
};
function Summary({text,frame}:{text:string;frame:number}){
  const fit=useMemo(()=>fitText(text,W,440,90,3,measure),[text]);
  return <div style={{position:'absolute',left:LEFT,top:745,width:W,fontSize:fit.size,lineHeight:1.08}}>{fit.lines.map((line:string,i:number)=>{const r=ease(ramp(frame,303+i*10,15));return <div key={i} style={{overflow:'hidden',paddingBottom:12,clipPath:`inset(0 ${(1-r)*100}% 0 0)`}}><div style={{transform:`translateY(${(1-r)*20}px)`,whiteSpace:'pre'}}>{line}</div></div>;})}</div>;
}
