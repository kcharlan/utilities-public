export const PHYSICS = Object.freeze({dt:1/60, gravity:9.81, drag:0.003, sink:0.65, stallSpeed:9, recoverySpeed:13, maxSpeed:32, climbPitch:0.46, divePitch:-0.55, turnRate:1.6});
export const clamp=(v,min,max)=>Math.max(min,Math.min(max,v));
export function createPlane({x=0,y=130,speed=26,pitch=-0.05}={}) {
  return {x,y,speed,pitch,stalled:false,vx:0,vy:0};
}
export function advancePlane(p,held,air={lift:0,wind:0},dt=PHYSICS.dt) {
  const c=PHYSICS;
  if(p.speed<c.stallSpeed) p.stalled=true;
  if(p.stalled&&p.speed>=c.recoverySpeed&&!held) p.stalled=false;
  const target=p.stalled?-0.65:held?c.climbPitch:c.divePitch;
  p.pitch += clamp(target-p.pitch,-c.turnRate*dt,c.turnRate*dt);
  p.speed=clamp(p.speed+(-c.gravity*Math.sin(p.pitch)-c.drag*p.speed*p.speed)*dt,4,c.maxSpeed);
  p.vx=Math.max(5,p.speed*Math.cos(p.pitch)+(air.wind||0));
  p.vy=p.speed*Math.sin(p.pitch)-c.sink+(p.stalled&&held?0:(air.lift||0));
  if(p.stalled&&held)p.vy=Math.min(-c.sink,p.vy);
  p.x+=p.vx*dt; p.y+=p.vy*dt;
  return p;
}
