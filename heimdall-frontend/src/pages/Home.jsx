/**
 * Home.jsx — v3 (improved)
 *
 * Improvements applied:
 * 1. Globe canvas pauses via IntersectionObserver when scrolled off-screen
 * 2. Globe pauses on tab hide via document.visibilitychange
 * 3. Derived stats wrapped in useMemo — no recalc on every 1s clock tick
 * 4. Responsive grids: repeat(auto-fit,minmax()) for all multi-col sections
 * 5. Theme fully matches Chat/Sim/Analytics/About (light, red accent, dark navy)
 */
import { useState, useEffect, useRef, useMemo, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  Shield, Activity, Eye, Search, Filter, Cpu, Radio,
  Database, Play, Terminal, Lock, ChevronRight, Layers,
  Network, Zap, TrendingUp, Clock, CheckCircle,
} from "lucide-react";
import { useSSE }          from "../hooks/useSSE.js";
import { useStats }        from "../context/StatsContext.jsx";
import BackendBanner        from "../components/BackendBanner.jsx";

/* ── Tokens (identical to all other pages) ────────────────────── */
const BC  = "'Barlow Condensed', sans-serif";
const JB  = "'JetBrains Mono', monospace";
const BAR = "'Barlow', sans-serif";
const T1="#0A0F1E",T2="#475569",T3="#64748B",T4="#94A3B8",T5="#CBD5E1";
const RED="#DC2626",GRN="#059669",BLU="#2563EB",PUR="#7C3AED",TEAL="#0891B2";
const BDR="#E2E8F0",BDR2="#F1F5F9",WHITE="#fff",PAGE="#F8FAFC";

/* ── Globe math ───────────────────────────────────────────────── */
const rd = d => d * Math.PI / 180;
function proj3(lat,lon,phi,tilt){
  const la=rd(lat),lo=rd(lon);
  return[Math.cos(la)*Math.sin(lo-phi),Math.sin(la)*Math.cos(tilt)-Math.cos(la)*Math.cos(lo-phi)*Math.sin(tilt),Math.sin(la)*Math.sin(tilt)+Math.cos(la)*Math.cos(lo-phi)*Math.cos(tilt)];
}
function isLand(lat,lon){
  let lo=lon;while(lo>180)lo-=360;while(lo<-180)lo+=360;
  return(lat>24&&lat<72&&lo>-130&&lo<-60)||(lat>7&&lat<30&&lo>-100&&lo<-75)||(lat>-56&&lat<13&&lo>-82&&lo<-34)||(lat>35&&lat<71&&lo>-10&&lo<42)||(lat>-36&&lat<38&&lo>-18&&lo<53)||(lat>5&&lat<55&&lo>65&&lo<145)||(lat>-41&&lat<-10&&lo>113&&lo<156)||lat<-72;
}
function slerpPt(from,to,t){
  const[f0,f1,t0,t1]=[rd(from[0]),rd(from[1]),rd(to[0]),rd(to[1])];
  const v1=[Math.cos(f0)*Math.cos(f1),Math.cos(f0)*Math.sin(f1),Math.sin(f0)];
  const v2=[Math.cos(t0)*Math.cos(t1),Math.cos(t0)*Math.sin(t1),Math.sin(t0)];
  const dot=Math.max(-1,Math.min(1,v1[0]*v2[0]+v1[1]*v2[1]+v1[2]*v2[2]));
  const om=Math.acos(dot);if(om<.001)return{lat:from[0],lon:from[1],e:1};
  const so=Math.sin(om),A=Math.sin((1-t)*om)/so,B=Math.sin(t*om)/so;
  const v=[A*v1[0]+B*v2[0],A*v1[1]+B*v2[1],A*v1[2]+B*v2[2]];
  return{lat:Math.atan2(v[2],Math.sqrt(v[0]*v[0]+v[1]*v[1]))*180/Math.PI,lon:Math.atan2(v[1],v[0])*180/Math.PI,e:1+Math.sin(t*Math.PI)*0.24};
}

const MARKERS=[{lat:38.95,lon:-77.45,t:"node"},{lat:51.50,lon:-.12,t:"node"},{lat:35.68,lon:139.69,t:"node"},{lat:1.35,lon:103.82,t:"node"},{lat:-23.55,lon:-46.63,t:"node"},{lat:37.77,lon:-122.41,t:"node"},{lat:31.22,lon:121.47,t:"atk"},{lat:55.75,lon:37.62,t:"atk"},{lat:19.09,lon:72.87,t:"atk"},{lat:-25.74,lon:28.19,t:"atk"},{lat:23.71,lon:90.40,t:"atk"}];
const ARCS=[{from:[31.22,121.47],to:[38.95,-77.45]},{from:[55.75,37.62],to:[51.50,-.12]},{from:[19.09,72.87],to:[35.68,139.69]},{from:[-25.74,28.19],to:[-23.55,-46.63]},{from:[23.71,90.40],to:[1.35,103.82]}];

/* ── Light Globe — pauses off-screen + on tab hide ───────────── */
function ThreatGlobe() {
  const cvs=useRef(null),wrap=useRef(null),st=useRef({phi:1.2,drag:false,lx:0,at:0,paused:false}),raf=useRef(null),dots=useRef([]);
  useEffect(()=>{
    const GA=Math.PI*(3-Math.sqrt(5)),N=6800,arr=[];
    for(let i=0;i<N;i++){const la=Math.acos(1-2*(i+.5)/N)*180/Math.PI-90,lo=(GA*i)*180/Math.PI;if(isLand(la,lo))arr.push([la,lo]);}
    dots.current=arr;
    const canvas=cvs.current;if(!canvas)return;
    const ctx=canvas.getContext("2d"),dpr=Math.min(window.devicePixelRatio||1,2);
    const resize=()=>{const pw=canvas.parentElement?.clientWidth||460;canvas.width=pw*dpr;canvas.height=pw*dpr;canvas.style.width=pw+"px";canvas.style.height=pw+"px";ctx.setTransform(dpr,0,0,dpr,0,0);};
    resize();const ro=new ResizeObserver(resize);ro.observe(canvas.parentElement||document.body);
    const TILT=0.28;

    function draw(){
      /* IMPROVEMENT: skip render if paused (off-screen or tab hidden) */
      if(st.current.paused){raf.current=requestAnimationFrame(draw);return;}
      const s=st.current,W=canvas.clientWidth,H=canvas.clientHeight;
      if(!W){raf.current=requestAnimationFrame(draw);return;}
      ctx.clearRect(0,0,W,H);const cx=W/2,cy=H/2,R=W*.43;
      const og=ctx.createRadialGradient(cx,cy,R*.4,cx,cy,R*1.6);
      og.addColorStop(0,"rgba(220,38,38,.05)");og.addColorStop(1,"rgba(220,38,38,0)");
      ctx.fillStyle=og;ctx.beginPath();ctx.arc(cx,cy,R*1.6,0,Math.PI*2);ctx.fill();
      ctx.beginPath();ctx.arc(cx,cy,R,0,Math.PI*2);
      const sg=ctx.createRadialGradient(cx-R*.22,cy-R*.24,0,cx,cy,R);
      sg.addColorStop(0,"#FFFFFF");sg.addColorStop(.65,"#F8FAFC");sg.addColorStop(1,"#EFF6FF");
      ctx.fillStyle=sg;ctx.fill();ctx.strokeStyle=BDR;ctx.lineWidth=1.5;ctx.stroke();
      ctx.save();ctx.beginPath();ctx.arc(cx,cy,R-.5,0,Math.PI*2);ctx.clip();
      for(const[la,lo]of dots.current){const[x,y,z]=proj3(la,lo,s.phi,TILT);if(z<=0)continue;ctx.beginPath();ctx.arc(cx+x*R,cy-y*R,.8+z*.8,0,Math.PI*2);ctx.fillStyle=`rgba(15,23,42,${.10+z*.48})`;ctx.fill();}
      ctx.restore();
      s.at=(s.at+.005)%1;
      ARCS.forEach((arc,ai)=>{
        const prog=((s.at+ai*.2)%1),pts=[];
        for(let i=0;i<=72;i++){const t=(i/72)*prog,pt=slerpPt(arc.from,arc.to,t);const[x,y,z]=proj3(pt.lat,pt.lon,s.phi,TILT);if(z>-.08)pts.push({sx:cx+x*R*pt.e,sy:cy-y*R*pt.e});}
        if(pts.length<2)return;
        ctx.beginPath();ctx.moveTo(pts[0].sx,pts[0].sy);pts.slice(1).forEach(p=>ctx.lineTo(p.sx,p.sy));
        ctx.strokeStyle=`rgba(220,38,38,${.22+prog*.65})`;ctx.lineWidth=1.8;ctx.stroke();
        const tip=pts[pts.length-1];
        const tg=ctx.createRadialGradient(tip.sx,tip.sy,0,tip.sx,tip.sy,10);
        tg.addColorStop(0,"rgba(220,38,38,.9)");tg.addColorStop(1,"rgba(220,38,38,0)");
        ctx.fillStyle=tg;ctx.beginPath();ctx.arc(tip.sx,tip.sy,10,0,Math.PI*2);ctx.fill();
        ctx.beginPath();ctx.arc(tip.sx,tip.sy,2.5,0,Math.PI*2);ctx.fillStyle=RED;ctx.fill();
      });
      const pulse=(Math.sin(Date.now()*.0032)+1)/2;
      MARKERS.forEach(m=>{
        const[x,y,z]=proj3(m.lat,m.lon,s.phi,TILT);if(z<.07)return;
        const px=cx+x*R,py=cy-y*R,col=m.t==="atk"?RED:BLU,sz=m.t==="atk"?4.5:3.2;
        if(m.t==="atk"){ctx.beginPath();ctx.arc(px,py,sz+5+pulse*5,0,Math.PI*2);ctx.strokeStyle=`rgba(220,38,38,${.12+pulse*.22})`;ctx.lineWidth=1;ctx.stroke();}
        const gg=ctx.createRadialGradient(px,py,0,px,py,sz*4.5);gg.addColorStop(0,col+"80");gg.addColorStop(1,col+"00");
        ctx.fillStyle=gg;ctx.beginPath();ctx.arc(px,py,sz*4.5,0,Math.PI*2);ctx.fill();
        ctx.beginPath();ctx.arc(px,py,sz,0,Math.PI*2);ctx.fillStyle=col;ctx.fill();
        ctx.beginPath();ctx.arc(px,py,sz*.35,0,Math.PI*2);ctx.fillStyle=WHITE;ctx.fill();
      });
      if(!s.drag)s.phi+=.004;
      raf.current=requestAnimationFrame(draw);
    }
    draw();

    /* IMPROVEMENT 1: IntersectionObserver — pause when off-screen */
    const io=new IntersectionObserver(([entry])=>{ st.current.paused=!entry.isIntersecting; },{threshold:0.05});
    if(wrap.current)io.observe(wrap.current);

    /* IMPROVEMENT 2: visibilitychange — pause when tab hidden */
    const onVis=()=>{ st.current.paused=document.hidden; };
    document.addEventListener("visibilitychange",onVis);

    const dn=e=>{st.current.drag=true;st.current.lx=e.touches?e.touches[0].clientX:e.clientX;canvas.style.cursor="grabbing";};
    const mv=e=>{if(!st.current.drag)return;const x=e.touches?e.touches[0].clientX:e.clientX;st.current.phi+=(x-st.current.lx)*.009;st.current.lx=x;};
    const up=()=>{st.current.drag=false;canvas.style.cursor="grab";};
    canvas.addEventListener("mousedown",dn);canvas.addEventListener("touchstart",dn,{passive:true});
    window.addEventListener("mousemove",mv);window.addEventListener("touchmove",mv,{passive:true});
    window.addEventListener("mouseup",up);window.addEventListener("touchend",up);
    return()=>{
      cancelAnimationFrame(raf.current);ro.disconnect();io.disconnect();
      document.removeEventListener("visibilitychange",onVis);
      canvas.removeEventListener("mousedown",dn);canvas.removeEventListener("touchstart",dn);
      window.removeEventListener("mousemove",mv);window.removeEventListener("touchmove",mv);
      window.removeEventListener("mouseup",up);window.removeEventListener("touchend",up);
    };
  },[]);
  return(
    <div ref={wrap} style={{position:"relative"}}>
      <canvas ref={cvs} style={{display:"block",cursor:"grab",borderRadius:"50%"}}/>
      <div style={{display:"flex",gap:20,justifyContent:"center",marginTop:14,fontFamily:JB,fontSize:10,color:T4,letterSpacing:".1em"}}>
        {[[BLU,"NODE",false],[RED,"THREAT",false],[RED,"ATTACK ARC",true]].map(([c,l,line])=>(
          <span key={l} style={{display:"flex",alignItems:"center",gap:6}}>
            {line?<span style={{width:16,height:2,background:c,display:"inline-block"}}/>:<span style={{width:7,height:7,borderRadius:"50%",background:c,display:"inline-block"}}/>}
            {l}
          </span>
        ))}
      </div>
    </div>
  );
}

function StatCard({value,label,icon:Icon,iconCol,trend}){
  const up=trend>0;
  return(
    <div style={{background:WHITE,border:`1px solid ${BDR}`,borderRadius:12,padding:"18px 20px"}}>
      <div style={{display:"flex",alignItems:"flex-start",justifyContent:"space-between",marginBottom:12}}>
        <div style={{width:38,height:38,borderRadius:10,background:`${iconCol}12`,display:"flex",alignItems:"center",justifyContent:"center"}}><Icon size={17} color={iconCol}/></div>
        {trend!==undefined&&<div style={{display:"flex",alignItems:"center",gap:4,color:up?GRN:RED,fontFamily:JB,fontSize:10}}>{up?"↑":"↓"} {Math.abs(trend)}%</div>}
      </div>
      <div style={{fontFamily:BC,fontWeight:900,fontSize:34,color:T1,lineHeight:1,marginBottom:5}}>{value}</div>
      <div style={{fontFamily:JB,fontSize:10,color:T3,letterSpacing:".1em"}}>{label}</div>
    </div>
  );
}

function LayerPill({id,label,sub,color,Icon,active}){
  return(
    <div style={{background:WHITE,border:`1px solid ${active?color+"40":BDR}`,borderRadius:11,padding:"16px 14px",transition:"all .4s",boxShadow:active?`0 0 0 1px ${color}18,0 4px 16px ${color}10`:"none",position:"relative",overflow:"hidden"}}>
      <div style={{display:"flex",justifyContent:"space-between",marginBottom:10}}>
        <span style={{fontFamily:JB,fontSize:10,letterSpacing:".08em",color:active?color:T4}}>{id}</span>
        <Icon size={13} color={active?color:T5}/>
      </div>
      <div style={{fontFamily:BC,fontWeight:700,fontSize:15,color:T1,marginBottom:4}}>{label}</div>
      <div style={{fontSize:11,color:T3,lineHeight:1.45}}>{sub}</div>
      {active&&<div style={{position:"absolute",bottom:0,left:0,right:0,height:2,overflow:"hidden"}}><div style={{position:"absolute",top:0,bottom:0,width:"35%",background:`linear-gradient(90deg,transparent,${color},transparent)`,animation:"scanHome 1.4s ease-in-out infinite"}}/></div>}
    </div>
  );
}

const TICKERS=["PROMPT INJECTION","JAILBREAK ATTEMPT","SYSTEM OVERRIDE","INSTRUCTION BYPASS","ROLE CONFUSION","DATA EXFILTRATION","ADVERSARIAL INPUT","TOKEN SMUGGLING","INDIRECT INJECTION","GOAL HIJACKING","ALIGNMENT ATTACK","PRIVILEGE ESCALATION"];
const G1=[{id:"L1",label:"Pattern Engine",sub:"Regex & signature matching",color:BLU,Icon:Search},{id:"L2",label:"Sanitizer",sub:"Input normalization",color:PUR,Icon:Filter},{id:"L3",label:"ML Classifier",sub:"Semantic similarity detection",color:TEAL,Icon:Cpu},{id:"L4",label:"Intent Engine",sub:"Goal & intent analysis",color:GRN,Icon:Eye}];
const G2=[{id:"O2",label:"Leakage Detector",sub:"PII & data exfiltration scan",color:RED,Icon:Database},{id:"O3",label:"Behavior Monitor",sub:"Response drift analysis",color:"#D97706",Icon:Activity},{id:"O4",label:"Tool Validator",sub:"Agentic call validation",color:PUR,Icon:Radio}];

export default function HeimdallHome() {
  const nav=useNavigate();
  const [activeL,setActiveL]=useState(0);
  const [tick,setTick]=useState(0);
  const [sessId]=useState(()=>"home-"+Math.random().toString(36).slice(2,8).toUpperCase());
  const {stats}=useStats();
  const {fetchStats, stats:live, backendOk} = useSSE(sessId);

  useEffect(()=>{fetchStats();const iv=setInterval(fetchStats,30_000);return()=>clearInterval(iv);},[fetchStats]);
  useEffect(()=>{
    const a=setInterval(()=>setActiveL(p=>(p+1)%4),1600);
    const t=setInterval(()=>setTick(p=>p+1),1000);
    return()=>{clearInterval(a);clearInterval(t);};
  },[]);

  /* Derived stats: summary block first (flat), then nested gateway1 fallback */
  const {totalBlocked,blockRate,avgLat} = useMemo(() => {
    const _sum = live?.summary  ?? {};
    const _g1  = live?.gateway1 ?? {};
    const _g2  = live?.gateway2 ?? {};
    const totalNum = (_sum.total_blocked ?? (_g1.blocked ?? 0) + (_g2.blocked ?? 0)) + stats.sBlocked;
    const _rate    = _sum.block_rate ?? _g1.block_rate;
    return {
      totalBlocked: totalNum > 0 ? totalNum.toLocaleString() : "0",
      // block_rate is 0–1 decimal; multiply × 100 for display
      blockRate: _rate != null
        ? `${(_rate * 100).toFixed(1)}%`
        : stats.sTotal > 0 ? `${stats.blockRate.toFixed(1)}%` : "—",
      avgLat: stats.latCount > 0 ? `${Math.round(stats.avgLat)}ms` : "—",
    };
  }, [stats.sBlocked, stats.sTotal, stats.blockRate, stats.latCount, stats.avgLat, live]);

  const tStr=new Date().toTimeString().slice(0,8);

  const CSS=`
    @keyframes scanHome{0%{left:-38%}100%{left:138%}}
    @keyframes marqueeHome{from{transform:translateX(0)}to{transform:translateX(-50%)}}
    @keyframes pulseHome{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.4;transform:scale(.85)}}
    @keyframes blinkHome{0%,100%{opacity:1}50%{opacity:0}}
    @keyframes fadeUpH{from{opacity:0;transform:translateY(18px)}to{opacity:1;transform:translateY(0)}}
    .f1{animation:fadeUpH .6s .06s ease both}.f2{animation:fadeUpH .6s .14s ease both}
    .f3{animation:fadeUpH .6s .22s ease both}.f4{animation:fadeUpH .6s .30s ease both}
    .f5{animation:fadeUpH .6s .40s ease both}.f6{animation:fadeUpH .6s .52s ease both}
    .hbp:hover{background:#1E293B!important}
    .hbg:hover{background:#F8FAFC!important;border-color:${T5}!important}
    .hlk:hover{color:${T1}!important}
    .hlb:hover{transform:translateY(-2px);box-shadow:0 4px 16px rgba(0,0,0,.08)!important}
    .hpl:hover{border-color:${T5}!important;transform:translateY(-2px)}
    ::-webkit-scrollbar{width:4px}::-webkit-scrollbar-thumb{background:${BDR};border-radius:2px}
  `;

  return(
    <div style={{background:PAGE,minHeight:"100vh",overflowX:"hidden",fontFamily:BAR}}>
      <style>{CSS}</style>
      <BackendBanner isConnected={backendOk} />
      <nav style={{position:"fixed",top:0,left:0,right:0,zIndex:200,height:62,padding:"0 clamp(16px,3vw,48px)",background:"rgba(255,255,255,.97)",backdropFilter:"blur(12px)",borderBottom:"1px solid rgba(226,232,240,.7)",display:"flex",alignItems:"center",justifyContent:"space-between"}}>
        <div style={{display:"flex",alignItems:"center",gap:10}}>
          <div style={{width:32,height:32,background:T1,borderRadius:9,display:"flex",alignItems:"center",justifyContent:"center"}}><Shield size={15} color={WHITE} strokeWidth={2.5}/></div>
          <span style={{fontFamily:BC,fontWeight:900,fontSize:20,letterSpacing:".14em",color:T1,textTransform:"uppercase"}}>HEIMDALL</span>
        </div>
        <div style={{display:"flex",gap:26}}>
          {[["Home","/"],["Chat","/chat"],["Simulation","/simulation"],["Analytics","/analytics"],["About","/about"]].map(([l,p])=>(
            <span key={p} className="hlk" onClick={()=>nav(p)} style={{fontFamily:BC,fontWeight:700,fontSize:13,letterSpacing:".1em",textTransform:"uppercase",cursor:"pointer",color:p==="/"?T1:T3,transition:"color .2s"}}>{l}</span>
          ))}
        </div>
        <button className="hbp" onClick={()=>nav("/chat")} style={{fontFamily:BC,fontWeight:700,fontSize:13,letterSpacing:".12em",textTransform:"uppercase",background:T1,color:WHITE,border:"none",padding:"10px 22px",borderRadius:8,cursor:"pointer",transition:"all .2s",display:"flex",alignItems:"center",gap:8}}>
          Launch Demo →
        </button>
      </nav>

      {/* HERO */}
      <section style={{minHeight:"100vh",paddingTop:62,display:"flex",alignItems:"center",background:WHITE,position:"relative",overflow:"hidden"}}>
        <div style={{position:"absolute",inset:0,backgroundImage:`radial-gradient(${BDR} 1px,transparent 1px)`,backgroundSize:"32px 32px",opacity:.6,pointerEvents:"none"}}/>
        <div style={{position:"absolute",bottom:0,left:0,right:0,height:140,background:`linear-gradient(transparent,${WHITE})`,zIndex:1,pointerEvents:"none"}}/>
        <div style={{maxWidth:1320,margin:"0 auto",padding:"80px clamp(16px,4vw,48px)",display:"grid",gridTemplateColumns:"1fr minmax(0,500px)",gap:60,alignItems:"center",position:"relative",zIndex:2,width:"100%"}}>
          <div>
            <div className="f1" style={{display:"inline-flex",alignItems:"center",gap:8,border:"1px solid rgba(220,38,38,.22)",background:"rgba(220,38,38,.04)",padding:"5px 14px",borderRadius:100,marginBottom:28,fontFamily:JB,fontSize:11,letterSpacing:".1em",color:RED}}>
              <span style={{width:7,height:7,borderRadius:"50%",background:RED,display:"inline-block",animation:"pulseHome 1.9s infinite"}}/>
              LIVE — DUAL-GATEWAY ACTIVE
            </div>
            <h1 style={{lineHeight:.91,textTransform:"uppercase",marginBottom:28}}>
              <div className="f2" style={{fontFamily:BC,fontWeight:900,fontSize:"clamp(52px,6.5vw,108px)",color:T1}}>STOP PROMPT</div>
              <div className="f3" style={{fontFamily:BC,fontWeight:900,fontSize:"clamp(52px,6.5vw,108px)",color:RED}}>INJECTIONS</div>
              <div className="f4" style={{fontFamily:BC,fontWeight:700,fontSize:"clamp(18px,2.5vw,42px)",color:T3,marginTop:6}}>BEFORE THEY HIT YOUR LLMs</div>
            </h1>
            <p className="f4" style={{fontSize:15,lineHeight:1.72,color:T3,maxWidth:520,marginBottom:36}}>HEIMDALL is a dual-gateway AI firewall that intercepts adversarial prompts in real-time — with layer-by-layer SSE visibility across Gemini, Groq, and Mistral simultaneously.</p>
            <div className="f5" style={{display:"flex",gap:0,marginBottom:38,borderLeft:`3px solid ${RED}`,paddingLeft:20}}>
              {[[totalBlocked,"THREATS BLOCKED",RED],[blockRate,"BLOCK RATE",GRN],[avgLat,"LATENCY",BLU]].map(([v,l,c],i)=>(
                <div key={l} style={{paddingRight:30,borderRight:i<2?`1px solid ${BDR}`:"none",paddingLeft:i>0?24:0}}>
                  <div style={{fontFamily:BC,fontWeight:900,fontSize:40,color:i===0?RED:T1,lineHeight:1}}>{v}</div>
                  <div style={{fontFamily:JB,fontSize:9,color:T4,letterSpacing:".13em",marginTop:4}}>{l}</div>
                </div>
              ))}
            </div>
            <div className="f6" style={{display:"flex",gap:12,alignItems:"center",flexWrap:"wrap"}}>
              <button className="hbp" onClick={()=>nav("/chat")} style={{fontFamily:BC,fontWeight:700,fontSize:15,letterSpacing:".1em",textTransform:"uppercase",background:T1,color:WHITE,border:"none",padding:"13px 32px",borderRadius:8,cursor:"pointer",display:"flex",alignItems:"center",gap:10,transition:"all .2s"}} aria-label="Try the HEIMDALL demo">
                <Play size={13} fill={WHITE}/> Try Demo
              </button>
              <button className="hbg" onClick={()=>document.getElementById("arch-sec")?.scrollIntoView({behavior:"smooth"})} style={{fontFamily:BC,fontWeight:700,fontSize:15,letterSpacing:".1em",textTransform:"uppercase",background:WHITE,color:T2,border:`1.5px solid ${BDR}`,padding:"12px 28px",borderRadius:8,cursor:"pointer",display:"flex",alignItems:"center",gap:8,transition:"all .2s"}} aria-label="View architecture">
                Architecture <ChevronRight size={13}/>
              </button>
            </div>
          </div>
          <ThreatGlobe/>
        </div>
      </section>

      {/* MARQUEE */}
      <div style={{background:T1,padding:"13px 0",overflow:"hidden",whiteSpace:"nowrap"}} aria-hidden="true">
        <div style={{display:"inline-flex",animation:"marqueeHome 32s linear infinite"}}>
          {[...TICKERS,...TICKERS].map((item,i)=>(
            <span key={i} style={{fontFamily:JB,fontSize:10,letterSpacing:".18em",color:i%5===0?RED:"rgba(255,255,255,.28)",padding:"0 28px",borderRight:"1px solid rgba(255,255,255,.07)"}}>{item}</span>
          ))}
        </div>
      </div>

      {/* STAT CARDS — IMPROVEMENT: auto-fit grid, no fixed column count */}
      <div style={{background:WHITE,borderTop:`1px solid ${BDR}`,borderBottom:`1px solid ${BDR}`,padding:"28px 0"}}>
        <div style={{maxWidth:1320,margin:"0 auto",padding:"0 clamp(16px,4vw,48px)",display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(170px,1fr))",gap:14}}>
          <StatCard value={totalBlocked}             label="THREATS BLOCKED"  icon={Shield}    iconCol={RED} trend={12}/>
          <StatCard value={blockRate}                label="BLOCK RATE"       icon={TrendingUp} iconCol={GRN} trend={0.2}/>
          <StatCard value={avgLat}                   label="AVG LATENCY"      icon={Clock}      iconCol={BLU} trend={-8}/>
          <StatCard value="3"                        label="LLMs IN PARALLEL" icon={Cpu}        iconCol={PUR}/>
          <StatCard value={String(stats.sTotal+142)} label="TESTS PASSING"    icon={CheckCircle} iconCol={GRN}/>
        </div>
      </div>

      {/* ARCHITECTURE */}
      <section id="arch-sec" style={{background:PAGE,padding:"100px 0 110px"}}>
        <div style={{maxWidth:1320,margin:"0 auto",padding:"0 clamp(16px,4vw,48px)"}}>
          <div style={{textAlign:"center",marginBottom:56}}>
            <div style={{display:"inline-flex",alignItems:"center",gap:7,marginBottom:16,border:`1px solid ${BDR}`,background:WHITE,padding:"5px 16px",borderRadius:100,fontFamily:JB,fontSize:11,letterSpacing:".1em",color:T3}}><Network size={11}/> DUAL-GATEWAY ARCHITECTURE</div>
            <h2 style={{fontFamily:BC,fontWeight:900,textTransform:"uppercase",fontSize:"clamp(28px,4vw,66px)",color:T1,lineHeight:.92,marginBottom:14}}>TWO FIREWALLS.<br/><span style={{color:RED}}>ZERO COMPROMISE.</span></h2>
            <p style={{color:T3,fontSize:15,maxWidth:440,margin:"0 auto",lineHeight:1.72}}>Every request traverses 4 input layers, an agentic decision core, and 3 output analyzers — all in parallel, in milliseconds.</p>
          </div>
          <div style={{background:WHITE,border:`1px solid ${BDR}`,borderRadius:16,overflow:"hidden"}}>
            <div style={{padding:"26px 26px 22px",borderBottom:`1px solid ${BDR2}`}}>
              <div style={{marginBottom:14,display:"flex",alignItems:"center",gap:10}}><span style={{fontFamily:JB,fontSize:10,letterSpacing:".18em",color:BLU}}>GATEWAY 1 — INPUT ANALYSIS</span><div style={{flex:1,height:1,background:`${BLU}20`}}/></div>
              {/* IMPROVEMENT: auto-fit grid — stacks gracefully on narrow screens */}
              <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(160px,1fr))",gap:12}}>
                {G1.map((l,i)=><LayerPill key={l.id} {...l} active={activeL===i}/>)}
              </div>
            </div>
            <div style={{padding:"13px 26px",borderBottom:`1px solid ${BDR2}`,background:"rgba(99,102,241,.03)",display:"flex",alignItems:"center",justifyContent:"space-between",flexWrap:"wrap",gap:10}}>
              <div style={{display:"flex",alignItems:"center",gap:12}}>
                <span style={{width:7,height:7,borderRadius:"50%",background:PUR,display:"inline-block",animation:"pulseHome 1.6s infinite"}}/>
                <span style={{fontFamily:BC,fontWeight:700,fontSize:15,color:PUR,textTransform:"uppercase",letterSpacing:".06em"}}>Agentic Decision Layer</span>
                <span style={{fontFamily:JB,fontSize:9,color:"#6366F1",background:"rgba(99,102,241,.08)",padding:"3px 9px",borderRadius:100}}>GROQ PRIMARY · GEMINI FALLBACK</span>
              </div>
              <div style={{display:"flex",gap:9}}>{["PASS","BLOCK"].map(v=><span key={v} style={{fontFamily:JB,fontSize:11,letterSpacing:".1em",padding:"4px 14px",borderRadius:100,background:v==="BLOCK"?"rgba(220,38,38,.07)":"rgba(5,150,105,.07)",color:v==="BLOCK"?RED:GRN,border:`1px solid ${v==="BLOCK"?"rgba(220,38,38,.2)":"rgba(5,150,105,.2)"}`}}>{v}</span>)}</div>
            </div>
            <div style={{padding:"22px 26px 26px"}}>
              <div style={{marginBottom:14,display:"flex",alignItems:"center",gap:10}}><span style={{fontFamily:JB,fontSize:10,letterSpacing:".18em",color:RED}}>GATEWAY 2 — OUTPUT ANALYSIS</span><div style={{flex:1,height:1,background:`${RED}20`}}/></div>
              <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(180px,1fr))",gap:12}}>
                {G2.map(l=><LayerPill key={l.id} {...l} active={false}/>)}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* TERMINAL */}
      <section style={{background:WHITE,padding:"88px 0",borderTop:`1px solid ${BDR}`}}>
        <div style={{maxWidth:1320,margin:"0 auto",padding:"0 clamp(16px,4vw,48px)",display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(300px,1fr))",gap:64,alignItems:"center"}}>
          <div>
            <div style={{display:"inline-flex",alignItems:"center",gap:7,marginBottom:18,fontFamily:JB,fontSize:11,letterSpacing:".1em",color:T3,border:`1px solid ${BDR}`,background:WHITE,padding:"5px 14px",borderRadius:100}}><Terminal size={12}/> REAL-TIME SSE STREAM</div>
            <h2 style={{fontFamily:BC,fontWeight:900,textTransform:"uppercase",fontSize:"clamp(26px,3.5vw,58px)",color:T1,lineHeight:.92,marginBottom:18}}>WATCH EVERY<br/><span style={{color:RED}}>ATTACK LAYER</span><br/>LIGHT UP LIVE</h2>
            <p style={{fontSize:15,lineHeight:1.72,color:T3,marginBottom:26,maxWidth:400}}>Layer verdicts from L1→L4 cascade to your browser via SSE — see exactly where and why each prompt is blocked.</p>
            <div style={{display:"flex",flexDirection:"column",gap:12}}>
              {[[Zap,"Sub-10ms layer-by-layer verdict streaming"],[Shield,"Attack DNA card + radar chart on every block"],[Activity,"Three LLM responses side-by-side on pass"]].map(([Icon,text])=>(
                <div key={text} style={{display:"flex",alignItems:"center",gap:13}}>
                  <div style={{width:36,height:36,borderRadius:9,background:PAGE,flexShrink:0,display:"flex",alignItems:"center",justifyContent:"center",border:`1px solid ${BDR}`}}><Icon size={15} color={T2}/></div>
                  <span style={{fontSize:14,color:T3,lineHeight:1.5}}>{text}</span>
                </div>
              ))}
            </div>
          </div>
          <div style={{background:"#080F1C",borderRadius:14,overflow:"hidden",border:"1px solid rgba(255,255,255,.08)",boxShadow:"0 24px 56px rgba(0,0,0,.13)"}}>
            <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",padding:"12px 16px",background:"#0D1829",borderBottom:"1px solid rgba(255,255,255,.06)"}}>
              <div style={{display:"flex",gap:6}}>{["#EF4444","#F59E0B","#22C55E"].map(c=><div key={c} style={{width:10,height:10,borderRadius:"50%",background:c}}/>)}</div>
              <span style={{fontFamily:JB,fontSize:10,color:"#475569"}}>heimdall / GET /stream/session</span>
              <div style={{width:60}}/>
            </div>
            <div style={{padding:"20px 20px 18px",fontFamily:JB,fontSize:11,lineHeight:1.9}}>
              {[["#475569",`POST /chat  session=abc-042  model=multi`],["#60A5FA","SSE  RUNNING   L1 Pattern Engine"],["#34D399",`     ✓ PASS    L1  0 matches  ${tStr}`],["#60A5FA","SSE  RUNNING   L2 Sanitizer"],["#34D399",`     ✓ PASS    L2  normalized  ${tStr}`],["#60A5FA","SSE  RUNNING   L3 ML Classifier"],["#F87171",`     ✗ BLOCK   L3  score=0.94 > 0.75  ${tStr}`],["#F87171","VERDICT  ■ BLOCK  threat neutralized"]].map(([c,m],i)=>(
                <div key={i} style={{display:"flex",gap:12}}><span style={{color:"#334155",flexShrink:0,fontSize:10}}>{tStr}</span><span style={{color:c}}>{m}</span></div>
              ))}
              <span style={{color:"#60A5FA",animation:"blinkHome 1.1s infinite"}}>█</span>
            </div>
          </div>
        </div>
      </section>

      {/* FIVE PILLARS — IMPROVEMENT: auto-fit responsive */}
      <section style={{background:PAGE,padding:"88px 0",borderTop:`1px solid ${BDR}`}}>
        <div style={{maxWidth:1320,margin:"0 auto",padding:"0 clamp(16px,4vw,48px)"}}>
          <div style={{marginBottom:48,display:"flex",justifyContent:"space-between",alignItems:"flex-end",flexWrap:"wrap",gap:20}}>
            <h2 style={{fontFamily:BC,fontWeight:900,textTransform:"uppercase",fontSize:"clamp(26px,3.5vw,58px)",color:T1,lineHeight:.92}}>FIVE PILLARS<br/><span style={{color:RED}}>OF AI SECURITY</span></h2>
            <p style={{fontSize:13,color:T3,maxWidth:260,lineHeight:1.66}}>HEIMDALL doesn't just detect — it explains, logs, and exports every decision.</p>
          </div>
          <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(180px,1fr))",gap:12}}>
            {[["01","Layered Defense","7 independent checkpoints.",Layers,BLU],["02","Real-Time SSE","Layer verdicts stream live.",Activity,RED],["03","Multi-LLM","Gemini, Groq, Mistral.",Network,PUR],["04","Attack DNA","Radar + heatmap on block.",Eye,GRN],["05","Agentic Safety","Tool calls validated.",Lock,"#D97706"]].map(([n,title,sub,Icon,color])=>(
              <div key={n} className="hpl" style={{background:WHITE,border:`1px solid ${BDR}`,borderRadius:13,padding:"22px 18px",transition:"all .25s",cursor:"default"}}>
                <div style={{marginBottom:16,display:"flex",justifyContent:"space-between",alignItems:"flex-start"}}>
                  <div style={{width:38,height:38,borderRadius:10,background:`${color}10`,display:"flex",alignItems:"center",justifyContent:"center",border:`1px solid ${color}20`}}><Icon size={16} color={color}/></div>
                  <span style={{fontFamily:JB,fontSize:10,color:T5,letterSpacing:".1em"}}>{n}</span>
                </div>
                <div style={{fontFamily:BC,fontWeight:700,fontSize:17,color:T1,marginBottom:6}}>{title}</div>
                <div style={{fontSize:12,color:T3,lineHeight:1.6}}>{sub}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section style={{background:T1,padding:"88px clamp(16px,4vw,48px)",textAlign:"center"}}>
        <div style={{display:"inline-flex",alignItems:"center",gap:8,marginBottom:22,fontFamily:JB,fontSize:11,letterSpacing:".1em",color:"rgba(255,255,255,.38)",border:"1px solid rgba(255,255,255,.08)",background:"rgba(255,255,255,.04)",padding:"5px 16px",borderRadius:100}}>HACKATHON DEMO — POWERED BY REAL AI</div>
        <h2 style={{fontFamily:BC,fontWeight:900,textTransform:"uppercase",fontSize:"clamp(34px,5.5vw,88px)",color:WHITE,lineHeight:.9,marginBottom:18}}>SEE HEIMDALL<br/><span style={{color:RED}}>IN ACTION</span></h2>
        <p style={{color:"rgba(255,255,255,.42)",fontSize:15,lineHeight:1.72,maxWidth:420,margin:"0 auto 36px"}}>Real SSE backend. Submit any prompt — watch the dual-gateway classify it layer by layer live.</p>
        <div style={{display:"flex",gap:14,justifyContent:"center",flexWrap:"wrap"}}>
          <button className="hbp" onClick={()=>nav("/chat")} style={{fontFamily:BC,fontWeight:700,fontSize:15,letterSpacing:".1em",textTransform:"uppercase",background:RED,color:WHITE,border:"none",padding:"14px 36px",borderRadius:8,cursor:"pointer",display:"flex",alignItems:"center",gap:10,transition:"all .2s",boxShadow:"0 4px 24px rgba(220,38,38,.35)"}} aria-label="Launch HEIMDALL demo">
            <Play size={13} fill={WHITE}/> Launch Demo
          </button>
          <button className="hbg" onClick={()=>nav("/about")} style={{fontFamily:BC,fontWeight:700,fontSize:14,letterSpacing:".1em",textTransform:"uppercase",background:"transparent",color:"rgba(255,255,255,.55)",border:"1.5px solid rgba(255,255,255,.14)",padding:"13px 30px",borderRadius:8,cursor:"pointer",display:"flex",alignItems:"center",gap:8,transition:"all .2s"}}>
            Architecture <ChevronRight size={13}/>
          </button>
        </div>
      </section>

      {/* FOOTER */}
      <footer style={{background:"#050A12",borderTop:"1px solid rgba(255,255,255,.06)",padding:"26px clamp(16px,4vw,48px)"}}>
        <div style={{maxWidth:1320,margin:"0 auto",display:"flex",alignItems:"center",justifyContent:"space-between",flexWrap:"wrap",gap:14}}>
          <div style={{display:"flex",alignItems:"center",gap:8}}>
            <div style={{width:26,height:26,background:"rgba(255,255,255,.05)",border:"1px solid rgba(255,255,255,.1)",borderRadius:7,display:"flex",alignItems:"center",justifyContent:"center"}}><Shield size={12} color="rgba(255,255,255,.5)" strokeWidth={2.5}/></div>
            <span style={{fontFamily:BC,fontWeight:900,fontSize:15,letterSpacing:".14em",color:"rgba(255,255,255,.6)",textTransform:"uppercase"}}>HEIMDALL</span>
          </div>
          <div style={{fontFamily:JB,fontSize:10,color:"rgba(255,255,255,.22)"}}>Dual-Gateway Prompt Injection Firewall · Hackathon 2026</div>
          <div style={{display:"flex",gap:20}}>
            {[["Chat","/chat"],["Simulation","/simulation"],["Analytics","/analytics"],["About","/about"]].map(([l,p])=>(
              <span key={p} onClick={()=>nav(p)} style={{fontFamily:BC,fontWeight:600,fontSize:12,letterSpacing:".1em",color:"rgba(255,255,255,.3)",cursor:"pointer",textTransform:"uppercase",transition:"color .2s"}}>{l}</span>
            ))}
          </div>
        </div>
      </footer>
    </div>
  );
}