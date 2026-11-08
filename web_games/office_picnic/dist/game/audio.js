const eventNotes={launch:[523,784],lift:[392,587],vent:[196,294],stall:[164,146],recovery:[294,440],warning:[440,349],impact:[98,73],respawn:[330,494],checkpoint:[392,494,587],district:[440,554,659],landing:[523,659,784,1047],best:[659,784,1047],pitch:[262],release:[220],ui:[330],pause:[294],resume:[392]};
export class Sound{
  constructor(muted=false){this.muted=muted;this.ctx=null;this.paused=false;this.district=0;this.beat=0;this.voices=0;this.last=new Map();}
  async unlock(){
    try{
      if(!this.ctx){const AC=window.AudioContext||window.webkitAudioContext;if(!AC)return;this.ctx=new AC();this.master=this.ctx.createGain();this.master.gain.value=this.muted?0:.26;this.master.connect(this.ctx.destination);this.next=this.ctx.currentTime+.1;this.interval=setInterval(()=>this.schedule(),100);}
      if(this.ctx.state==='suspended'&&!this.paused)await this.ctx.resume();
    }catch{/* Sound availability must never prevent playing. */}
  }
  tone(freq,start,duration,volume=.1,type='sine'){
    if(!this.ctx||this.voices>=24)return;
    const osc=this.ctx.createOscillator(),gain=this.ctx.createGain();osc.type=type;osc.frequency.value=freq;gain.gain.setValueAtTime(0,start);gain.gain.linearRampToValueAtTime(volume,start+.025);gain.gain.exponentialRampToValueAtTime(.0001,start+duration);osc.connect(gain);gain.connect(this.master);osc.start(start);osc.stop(start+duration+.02);this.voices++;osc.onended=()=>{this.voices--;osc.disconnect();gain.disconnect();};
  }
  schedule(){
    if(!this.ctx||this.paused||this.muted||this.ctx.state!=='running')return;
    const now=this.ctx.currentTime;if(this.next<now)this.next=now+.05;
    while(this.next<now+.25){
      const t=this.next,b=this.beat++,root=[130.813,110,146.832,98][Math.floor(b/16)%4];
      if(b%8===0){this.tone(root,t,3,.13);this.tone(root*1.5,t,3,.075);}
      if(this.district>=1&&b%4===2)this.tone(root*2,t,1.2,.06,'triangle');
      if(this.district>=2&&b%2===0)this.tone(root*[4,3,5,3][b%4],t,.65,.045);
      if(this.district>=3&&b%4===0)this.tone(root*.5,t,.9,.1,'triangle');
      if(this.district>=4)this.tone(b%2?880:660,t,.09,.025,'triangle');
      this.next+=.38;
    }
  }
  event(name){
    if(!this.ctx||this.muted||this.paused)return;
    const now=this.ctx.currentTime;if(now-(this.last.get(name)??-10)<.3)return;this.last.set(name,now);
    (eventNotes[name]||eventNotes.ui).forEach((f,i)=>this.tone(f,now+i*.09,name==='impact'?.23:.35,name==='warning'?.11:.12,name==='impact'?'triangle':'sine'));
  }
  setMuted(value){this.muted=value;if(this.master)this.master.gain.setTargetAtTime(value?0:.26,this.ctx.currentTime,.03);}
  setPaused(value){this.paused=value;if(!this.ctx)return;if(value)this.ctx.suspend().catch(()=>{});else{this.next=this.ctx.currentTime+.08;this.ctx.resume().catch(()=>{});}}
}
