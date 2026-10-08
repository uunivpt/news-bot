import React from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';

/**
 * Exclusive memorial format for the verified 8 October 2026 Nana Patekar story.
 * Original motion graphics, not repurposed third-party film or social clips.
 */
const WHITE = '#F4F1EC';
const RED = '#D92C35';
const GREY = '#9B9A9A';
const BLACK = '#080809';
const clamp = (n:number) => Math.max(0, Math.min(1, n));
const ease = (n:number) => 1 - Math.pow(1-clamp(n),3);
const reveal = (f:number, at:number, len=22) => ease((f-at)/len);
const fadeOut = (f:number, at:number, len=14) => 1-reveal(f,at,len);
const scene = (f:number, start:number, end:number) =>
  reveal(f,start,14)*fadeOut(f,end-16,16);

const Stagger:React.FC<{children:React.ReactNode; frame:number; at:number; x?:number; y?:number; style?:React.CSSProperties}> =
  ({children,frame,at,x=0,y=50,style}) => {
    const t = reveal(frame,at,18);
    return <div style={{opacity:t,transform:`translate(${(1-t)*x}px,${(1-t)*y}px)`,...style}}>{children}</div>;
  };

export const NanaTribute:React.FC<{DATE:string;SOURCE:string}> = ({DATE,SOURCE}) => {
  const f=useCurrentFrame();
  const bleed=Math.sin(f/85)*14;
  return <AbsoluteFill style={{background:BLACK,color:WHITE,fontFamily:'"Barlow Condensed", sans-serif',overflow:'hidden'}}>
    <AbsoluteFill style={{background:'radial-gradient(ellipse 90% 55% at 51% 44%,#5d182035 0%,transparent 73%),linear-gradient(180deg,#050505 0%,#131014 50%,#030303 100%)'}}/>
    <AbsoluteFill style={{backgroundImage:'linear-gradient(90deg,transparent 0%,#ffffff08 50%,transparent 100%)',backgroundSize:'360px 100%',transform:`translateX(${bleed}px)`,opacity:.65}}/>
    <div style={{position:'absolute',left:72,right:72,top:118,height:2,background:'#ffffff2f'}}/>
    <div style={{position:'absolute',left:72,top:68,color:WHITE,fontSize:32,letterSpacing:4}}>POLITICS<span style={{color:RED}}>HUB</span><span style={{fontSize:20,color:GREY,marginLeft:18}}>.IN</span></div>
    <div style={{position:'absolute',right:72,top:76,color:GREY,fontSize:21,letterSpacing:3}}>08 OCT 2026</div>
    <div style={{position:'absolute',top:155,left:72,width:112,height:5,background:RED,transform:`scaleX(${reveal(f,8,35)})`,transformOrigin:'left'}}/>
    {/* A theatre curtain in light rather than third-party movie footage. */}
    {[0,1].map(i=><div key={i} style={{position:'absolute',top:300,left:i===0?-450:630,width:900,height:1050,opacity:.4,filter:'blur(34px)',
      background:i===0?'linear-gradient(90deg,#3c0b13aa,transparent)':'linear-gradient(270deg,#3c0b13aa,transparent)',
      transform:`translateX(${(i===0?-1:1)*reveal(f,15,100)*135}px)`}}/>)}
    {f<65&&<div style={{position:'absolute',left:72,right:72,top:640,opacity:scene(f,0,63),textAlign:'center'}}>
      <Stagger at={5} frame={f}><div style={{fontSize:30,color:RED,letterSpacing:11}}>IN REMEMBRANCE</div></Stagger>
      <Stagger at={15} frame={f} y={20}><div style={{marginTop:30,fontSize:70,lineHeight:1.1,letterSpacing:2}}>A LIFE IN CINEMA</div></Stagger>
      <div style={{width:100,height:1,background:RED,margin:'56px auto'}}/>
    </div>}
    {f>=45&&f<216&&<div style={{position:'absolute',left:78,right:78,top:450,opacity:scene(f,45,215)}}>
      <Stagger at={48} frame={f}><div style={{fontSize:31,letterSpacing:8,color:RED,marginBottom:54}}>REMEMBERING AN ICON</div></Stagger>
      <Stagger at={60} frame={f} y={88}><div style={{fontSize:192,lineHeight:.83,letterSpacing:-3,fontWeight:700}}>NANA<br/>PATEKAR</div></Stagger>
      <Stagger at={86} frame={f} y={20}><div style={{fontSize:55,letterSpacing:11,color:GREY,marginTop:66}}>1951 — 2026</div></Stagger>
      <Stagger at={100} frame={f}><div style={{width:125,height:6,background:RED,marginTop:50}}/></Stagger>
      <Stagger at={108} frame={f}><div style={{fontSize:36,color:'#DDD',marginTop:30,letterSpacing:2}}>Veteran actor dies aged 75 in Goa</div></Stagger>
    </div>}
    {f>=196&&f<385&&<div style={{position:'absolute',left:78,right:78,top:490,opacity:scene(f,196,385)}}>
      <Stagger at={208} frame={f}><div style={{fontSize:31,color:RED,letterSpacing:8}}>AN ENDURING LEGACY</div></Stagger>
      <Stagger at={228} frame={f} y={76}><div style={{fontSize:107,lineHeight:1.05,marginTop:66}}>A VOICE<br/>THAT LEFT<br/><span style={{color:RED}}>ITS MARK.</span></div></Stagger>
      <Stagger at={248} frame={f} y={40}><div style={{fontSize:37,lineHeight:1.3,color:'#D7D3CF',marginTop:62}}>Parinda  •  Krantiveer<br/>Ab Tak Chhappan  •  Natsamrat</div></Stagger>
      <Stagger at={274} frame={f} y={20}><div style={{fontSize:32,lineHeight:1.2,color:GREY,marginTop:48}}>Across Hindi and Marathi cinema</div></Stagger>
    </div>}
    {f>=358&&f<480&&<div style={{position:'absolute',left:78,right:78,top:590,opacity:scene(f,358,480)}}>
      <Stagger at={367} frame={f}><div style={{fontSize:31,color:RED,letterSpacing:8}}>08 OCTOBER 2026</div></Stagger>
      <Stagger at={382} frame={f} y={40}><div style={{fontSize:77,lineHeight:1.12,marginTop:50}}>INDIAN CINEMA<br/>REMEMBERS<br/>NANA PATEKAR.</div></Stagger>
      <Stagger at={405} frame={f}><div style={{fontSize:36,color:GREY,marginTop:65,lineHeight:1.3}}>A career, a legacy, and performances<br/>remembered by generations.</div></Stagger>
    </div>}
    {f>=462&&<div style={{position:'absolute',left:80,right:80,top:700,opacity:reveal(f,465,18),textAlign:'center'}}>
      <div style={{fontSize:40,letterSpacing:6,color:RED,marginBottom:50}}>IN MEMORIAM</div>
      <div style={{fontSize:86,fontWeight:700}}>NANA PATEKAR</div>
      <div style={{height:3,width:160,background:RED,margin:'60px auto'}}/>
      <div style={{fontSize:48}}>Politics<span style={{color:'#999'}}>Hub</span><span style={{fontSize:25,color:RED}}>.in</span></div>
      <div style={{fontSize:23,color:GREY,marginTop:24,letterSpacing:3}}>WHAT MATTERS, CLEARLY.</div>
    </div>}
    <div style={{position:'absolute',left:72,right:72,bottom:140,height:2,background:'#ffffff34'}}/>
    <div style={{position:'absolute',left:72,bottom:86,fontSize:21,color:GREY,letterSpacing:2}}>SOURCE: {SOURCE.toUpperCase().slice(0,42)}</div>
    <div style={{position:'absolute',right:72,bottom:86,fontSize:20,color:GREY,letterSpacing:2}}>POLITICSHUB.IN</div>
    <div style={{position:'absolute',left:72,bottom:160,width:`${Math.min(100,f/540*100)}%`,maxWidth:936,height:2,background:RED}}/>
  </AbsoluteFill>;
};
