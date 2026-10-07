import React from 'react';
import {Composition,registerRoot} from 'remotion';
import {Reel,Story} from './Reel';
const defaults:Story={HEADLINE:'The story behind the headline. Clearly explained.',IMAGE:null,CATEGORY:'EXPLAINED',DATE:'07 OCT 2026',LOCATION:'INDIA',SOURCE:'PoliticsHub.in • Template demonstration',SUMMARY:'The essential facts. The context that matters. Independent reporting, made clear.',AUDIO:true};
const Root:React.FC=()=> <Composition id="PoliticsHubReel" component={Reel} durationInFrames={540} fps={30} width={1080} height={1920} defaultProps={defaults}/>;
registerRoot(Root);
