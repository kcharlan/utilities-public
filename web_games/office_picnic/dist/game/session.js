export function consumeTime(clock,seconds,paused,step){
  if(paused){clock.accumulator=0;return;}
  clock.accumulator+=Math.min(.1,Math.max(0,seconds));
  let count=0;
  while(clock.accumulator>=1/60&&count<6){step();clock.accumulator-=1/60;count++;}
}
export function rebaseNoticeDeadline(deadline,before,after){
  return after<before?after+deadline-before-1:deadline;
}
export function formatTime(seconds){
  const n=Math.max(0,Math.floor(seconds*100+.00001));
  return `${Math.floor(n/6000)}:${String(Math.floor(n/100)%60).padStart(2,'0')}.${String(n%100).padStart(2,'0')}`;
}
export function formatDistance(meters){
  const distance=Math.max(0,meters);
  return distance>=402.336?`${(distance/1609.344).toFixed(2)} mi`:formatFeet(distance);
}
export function formatFeet(meters){return `${Math.round(Math.max(0,meters)/.3048).toLocaleString('en-US')} ft`;}
export function formatVerticalMotion(speed){
  const rate=Math.round(Math.abs(speed)/.3048);
  return rate<2?'→ Level':`${speed>0?'↑ Rising':'↓ Descending'} ${rate} ft/s`;
}
export function formatSpeed(metersPerSecond){return `${Math.round(Math.max(0,metersPerSecond)*2.2369362920544)} mph`;}
export function cameraFor(width,height,p){
  const scale=Math.min(2.7,width/420,height/270),verticalScale=Math.max(scale,height/360),planeX=width*.23;
  return {scale,verticalScale,planeX,left:p.x-planeX/scale,bottom:Math.max(-12,p.y-height*.43/verticalScale),width,height};
}
