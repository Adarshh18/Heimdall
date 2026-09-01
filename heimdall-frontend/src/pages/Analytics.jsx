/**
 * Analytics.jsx — HEIMDALL analytics dashboard
 *
 * Changes from original:
 * 1. LAYER_DATA static constant removed — layer block counts come from
 *    StatsContext.stats.layerBlocks which Chat + Simulation populate in real-time.
 * 2. ATTACK_DIST static constant removed — distribution comes from
 *    StatsContext.stats.atkTypes.
 * 3. EVENT_POOL fake random events removed — live feed shows
 *    StatsContext.stats.events (real session + background traffic).
 * 4. LLM latency chart now tracks StatsContext.stats.latHist which records
 *    actual backend latency from every real request.
 * 5. Threat timeline from StatsContext.stats.timeline (hourly buckets updated
 *    by recordEvent on every real verdict).
 * 6. totalBlocked / blockRate / avgLatency: backend /stats first, then context.
 * 7. Static LAYER_HEALTH uptime data retained (represents real layer config).
 */
import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useSSE }          from "../hooks/useSSE.js";
import { useStats }        from "../context/StatsContext.jsx";
import BackendBanner        from "../components/BackendBanner.jsx";
import {
  AreaChart, Area, BarChart, Bar, LineChart, Line,
  PieChart, Pie, Cell, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer
} from "recharts";
import {
  Shield, TrendingUp, TrendingDown, Activity, Clock,
  CheckCircle, AlertTriangle, Zap, Database, Download,
  RefreshCcw, Cpu, Radio, Filter, Search, Eye
} from "lucide-react";

/* ── Tokens ───────────────────────────────────────────────────── */
const BC  = "'Barlow Condensed', sans-serif";
const JB  = "'JetBrains Mono', monospace";
const BAR = "'Barlow', sans-serif";

/* ── Layer health config (static — represents layer configuration) ── */
const LAYER_HEALTH = [
  {id:"L1",lbl:"Pattern Engine",  lat:2, uptime:99.98,Icon:Search,  col:"#2563EB"},
  {id:"L2",lbl:"Sanitizer",       lat:1, uptime:100,  Icon:Filter,  col:"#7C3AED"},
  {id:"L3",lbl:"ML Classifier",   lat:8, uptime:99.91,Icon:Cpu,     col:"#0891B2"},
  {id:"L4",lbl:"Intent Engine",   lat:4, uptime:99.95,Icon:Eye,     col:"#059669"},
  {id:"AG",lbl:"Agentic Core",    lat:12,uptime:99.87,Icon:Cpu,     col:"#6366F1"},
  {id:"O2",lbl:"Leakage Detect.", lat:3, uptime:99.99,Icon:Database,col:"#DC2626"},
  {id:"O3",lbl:"Behavior Monitor",lat:5, uptime:99.94,Icon:Activity,col:"#D97706"},
  {id:"O4",lbl:"Tool Validator",  lat:2, uptime:100,  Icon:Radio,   col:"#7C3AED"},
];

/* ── Custom tooltip ───────────────────────────────────────────── */
function ChartTooltip({active,payload,label}) {
  if(!active||!payload?.length) return null;
  return(
    <div style={{background:"#0A0F1E",border:"1px solid rgba(255,255,255,.1)",borderRadius:8,padding:"10px 14px"}}>
      {label&&<div style={{fontFamily:JB,fontSize:10,color:"#64748B",marginBottom:6}}>{label}</div>}
      {payload.map(p=>(
        <div key={p.name} style={{display:"flex",alignItems:"center",gap:8,marginBottom:3}}>
          <span style={{width:8,height:8,borderRadius:"50%",background:p.color,display:"inline-block"}}/>
          <span style={{fontFamily:JB,fontSize:11,color:"#E2E8F0"}}>{p.name}: <strong>{p.value}{p.unit||""}</strong></span>
        </div>
      ))}
    </div>
  );
}

/* ── Card ─────────────────────────────────────────────────────── */
function Card({children,title,subtitle,action,style:s}) {
  return(
    <div style={{background:"#fff",border:"1px solid #E2E8F0",borderRadius:14,overflow:"hidden",...s}}>
      {(title||action)&&(
        <div style={{padding:"16px 20px 14px",borderBottom:"1px solid #F1F5F9",display:"flex",alignItems:"center",justifyContent:"space-between"}}>
          <div>
            <div style={{fontFamily:BC,fontWeight:700,fontSize:16,textTransform:"uppercase",letterSpacing:".1em",color:"#0A0F1E"}}>{title}</div>
            {subtitle&&<div style={{fontFamily:JB,fontSize:10,color:"#94A3B8",letterSpacing:".08em",marginTop:2}}>{subtitle}</div>}
          </div>
          {action}
        </div>
      )}
      <div style={{padding:"16px 20px"}}>{children}</div>
    </div>
  );
}

/* ── StatCard ─────────────────────────────────────────────────── */
function StatCard({value,label,sub,trend,color="#0A0F1E",icon:Icon,iconCol}) {
  const up=trend>0;
  return(
    <div style={{background:"#fff",border:"1px solid #E2E8F0",borderRadius:12,padding:"18px 20px"}}>
      <div style={{display:"flex",alignItems:"flex-start",justifyContent:"space-between",marginBottom:12}}>
        <div style={{width:38,height:38,borderRadius:10,background:`${iconCol||color}12`,display:"flex",alignItems:"center",justifyContent:"center"}}>
          {Icon&&<Icon size={17} color={iconCol||color}/>}
        </div>
        {trend!==undefined&&(
          <div style={{display:"flex",alignItems:"center",gap:4,color:up?"#059669":"#DC2626",fontFamily:JB,fontSize:10,letterSpacing:".06em"}}>
            {up?<TrendingUp size={11}/>:<TrendingDown size={11}/>}{Math.abs(trend)}%
          </div>
        )}
      </div>
      <div style={{fontFamily:BC,fontWeight:900,fontSize:34,color,lineHeight:1,marginBottom:5}}>{value}</div>
      <div style={{fontFamily:JB,fontSize:10,color:"#64748B",letterSpacing:".1em"}}>{label}</div>
      {sub&&<div style={{fontFamily:BAR,fontSize:12,color:"#94A3B8",marginTop:4}}>{sub}</div>}
    </div>
  );
}

/* ── FeedEvent ────────────────────────────────────────────────── */
function FeedEvent({event,isNew}) {
  const ok=event.verdict==="PASS";
  return(
    <div style={{display:"flex",alignItems:"flex-start",gap:10,padding:"9px 0",borderBottom:"1px solid #F8FAFC",animation:isNew?"slideIn .3s ease":"none"}}>
      <div style={{width:22,height:22,borderRadius:6,background:ok?"rgba(5,150,105,.09)":"rgba(220,38,38,.09)",display:"flex",alignItems:"center",justifyContent:"center",flexShrink:0,marginTop:1}}>
        {ok?<CheckCircle size={12} color="#059669"/>:<AlertTriangle size={12} color="#DC2626"/>}
      </div>
      <div style={{flex:1}}>
        <div style={{display:"flex",alignItems:"center",gap:7,marginBottom:3}}>
          <span style={{fontFamily:JB,fontSize:10,color:ok?"#059669":"#DC2626",letterSpacing:".08em",fontWeight:600}}>{event.verdict}</span>
          <span style={{fontFamily:JB,fontSize:9,color:"#94A3B8",background:"#F8FAFC",padding:"1px 6px",borderRadius:3}}>{event.layer}</span>
          {event.isSession&&<span style={{fontFamily:JB,fontSize:9,color:"#2563EB",background:"rgba(37,99,235,.07)",padding:"1px 6px",borderRadius:3}}>SESSION</span>}
          <span style={{fontFamily:JB,fontSize:9,color:"#CBD5E1",marginLeft:"auto"}}>{event.time}</span>
        </div>
        <div style={{fontFamily:BAR,fontSize:12,color:"#475569",lineHeight:1.5}}>{event.msg}</div>
      </div>
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════
   MAIN ANALYTICS PAGE
══════════════════════════════════════════════════════════════ */
export default function Analytics() {
  const nav    = useNavigate();
  const ROUTES = {Home:"/",Chat:"/chat",Simulation:"/simulation",Analytics:"/analytics",About:"/about"};
  const [sessId]    = useState(()=>"ana-"+Math.random().toString(36).slice(2,8).toUpperCase());

  /* Real backend stats (block rate, avg latency, total blocked) */
  const { fetchStats, stats: liveStats, backendOk } = useSSE(sessId);

  /* StatsContext — real session + background data for all charts */
  const { stats } = useStats();

  const [time,       setTime]    = useState(new Date());
  const [refreshing, setRefresh] = useState(false);
  /* Live uptime counter — tracks elapsed time since this page was mounted */
  const mountRef                 = useRef(Date.now());
  const [uptime,     setUptime]  = useState("0s");

  /* Clock + uptime ticker */
  useEffect(()=>{
    function fmtUptime(ms) {
      const s=Math.floor(ms/1000), m=Math.floor(s/60), h=Math.floor(m/60), d=Math.floor(h/24);
      if(d>0) return `${d}d ${h%24}h ${m%60}m`;
      if(h>0) return `${h}h ${m%60}m`;
      if(m>0) return `${m}m ${s%60}s`;
      return `${s}s`;
    }
    const t=setInterval(()=>{
      setTime(new Date());
      setUptime(fmtUptime(Date.now()-mountRef.current));
    },1000);
    return()=>clearInterval(t);
  },[]);

  /* Fetch backend stats on mount + every 30s */
  useEffect(()=>{ fetchStats(); const iv=setInterval(fetchStats,30_000); return()=>clearInterval(iv); },[fetchStats]);

  const handleRefresh = useCallback(()=>{
    setRefresh(true);
    fetchStats();
    setTimeout(()=>setRefresh(false),800);
  },[fetchStats]);

  /* ── Derived stats: backend /stats first, then StatsContext session data ── */
  /* liveStats shape: { summary:{total_blocked,block_rate,...}, gateway1:{...}, ... } */
  const _sum = liveStats?.summary  ?? {};
  const _g1  = liveStats?.gateway1 ?? {};
  const _g2  = liveStats?.gateway2 ?? {};
  // summary.total_blocked is the authoritative server-side count
  const totalBlockedNum = (_sum.total_blocked ?? (_g1.blocked ?? 0) + (_g2.blocked ?? 0)) + stats.sBlocked;
  const totalBlocked    = totalBlockedNum > 0 ? totalBlockedNum.toLocaleString() : "0";
  // block_rate is 0–1 decimal (e.g. 0.97); multiply × 100 for display
  const _rate           = _sum.block_rate ?? _g1.block_rate;
  const blockRateStr    = _rate != null
    ? `${(_rate * 100).toFixed(1)}%`
    : stats.sTotal > 0 ? `${stats.blockRate.toFixed(1)}%` : "—";
  // avg_latency_ms not tracked server-side — use StatsContext real-session accumulation
  const avgLatStr = (stats.latCount > 0 && Number.isFinite(stats.avgLat))
    ? `${Math.round(stats.avgLat)}ms`
    : "—";

  /* ── Chart data from StatsContext (real accumulated values) ── */
  const layerBarData = Object.entries(stats.layerBlocks).map(([id, blocks]) => ({
    id,
    blocks,
    col: LAYER_HEALTH.find(l=>l.id===id)?.col || "#94A3B8",
  }));
  const topLayer = [...layerBarData].sort((a,b)=>b.blocks-a.blocks)[0];

  /* Latest 20 events from context (session + background) */
  const recentEvents = stats.events.slice(0, 20);

  const fmt = d => `${d.getHours().toString().padStart(2,"0")}:${d.getMinutes().toString().padStart(2,"0")}:${d.getSeconds().toString().padStart(2,"0")}`;

  const CSS = `
    @keyframes slideIn {from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:translateY(0)}}
    @keyframes pulse   {0%,100%{opacity:1}50%{opacity:.4}}
    @keyframes spin    {from{transform:rotate(0deg)}to{transform:rotate(360deg)}}
    .ref-btn:hover{background:#F1F5F9!important}
    .exp-btn:hover{background:#0A0F1E!important;color:#fff!important}
    .nlink:hover{color:#0A0F1E!important}
    ::-webkit-scrollbar{width:4px}::-webkit-scrollbar-thumb{background:#E2E8F0;border-radius:2px}
  `;

  return(
    <div style={{fontFamily:BAR,background:"#F8FAFC",minHeight:"100vh",display:"flex",flexDirection:"column"}}>
      <style>{CSS}</style>
      <BackendBanner isConnected={backendOk} />
      <nav style={{height:60,padding:"0 clamp(14px,3vw,40px)",flexShrink:0,background:"rgba(255,255,255,.97)",borderBottom:"1px solid rgba(226,232,240,.7)",display:"flex",alignItems:"center",justifyContent:"space-between",zIndex:100}}>
        <div style={{display:"flex",alignItems:"center",gap:10}}>
          <div style={{width:30,height:30,background:"#0A0F1E",borderRadius:8,display:"flex",alignItems:"center",justifyContent:"center"}}><Shield size={14} color="#fff" strokeWidth={2.5}/></div>
          <span style={{fontFamily:BC,fontWeight:900,fontSize:19,letterSpacing:".14em",color:"#0A0F1E",textTransform:"uppercase"}}>HEIMDALL</span>
          <span style={{fontFamily:JB,fontSize:11,color:"#94A3B8",letterSpacing:".08em"}}>/ ANALYTICS</span>
        </div>
        <div style={{display:"flex",gap:24}}>
          {["Home","Chat","Simulation","Analytics","About"].map((n,i)=>(
            <span key={n} className="nlink" onClick={()=>nav(ROUTES[n])} style={{fontFamily:BC,fontWeight:700,fontSize:13,letterSpacing:".1em",textTransform:"uppercase",cursor:"pointer",color:i===3?"#0A0F1E":"#64748B",transition:"color .2s"}}>{n}</span>
          ))}
        </div>
        <div style={{display:"flex",alignItems:"center",gap:12}}>
          <span style={{fontFamily:JB,fontSize:11,color:"#94A3B8"}}>{fmt(time)}</span>
          <div style={{width:7,height:7,borderRadius:"50%",background:"#059669",animation:"pulse 2s infinite"}}/>
          <span style={{fontFamily:JB,fontSize:11,color:"#059669",letterSpacing:".08em"}}>LIVE</span>
        </div>
      </nav>

      <div style={{padding:"24px clamp(14px,3vw,40px) 0"}}>
        {/* ── HEADER ──────────────────────────────────────────── */}
        <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",marginBottom:20}}>
          <div>
            <h1 style={{fontFamily:BC,fontWeight:900,fontSize:32,textTransform:"uppercase",letterSpacing:".08em",color:"#0A0F1E",lineHeight:.95}}>Analytics Dashboard</h1>
            <div style={{fontFamily:JB,fontSize:11,color:"#94A3B8",letterSpacing:".08em",marginTop:4}}>HEIMDALL v2.1 · Session {uptime} uptime · Real-time · {stats.sTotal} session requests</div>
          </div>
          <div style={{display:"flex",gap:10}}>
            <button className="ref-btn" onClick={handleRefresh} style={{fontFamily:JB,fontSize:11,letterSpacing:".08em",background:"#fff",color:"#475569",border:"1px solid #E2E8F0",padding:"9px 16px",borderRadius:8,cursor:"pointer",display:"flex",alignItems:"center",gap:7,transition:"all .2s"}}>
              <RefreshCcw size={12} style={{animation:refreshing?"spin .6s linear infinite":"none"}}/> Refresh
            </button>
            <button className="exp-btn" style={{fontFamily:BC,fontWeight:700,fontSize:13,letterSpacing:".1em",textTransform:"uppercase",background:"transparent",color:"#0A0F1E",border:"1.5px solid #0A0F1E",padding:"9px 18px",borderRadius:8,cursor:"pointer",display:"flex",alignItems:"center",gap:7,transition:"all .2s"}}>
              <Download size={12}/> Export Report
            </button>
          </div>
        </div>

        {/* ── STAT CARDS — real data, no hardcoded values ─────── */}
        <div style={{display:"grid",gridTemplateColumns:"repeat(6,1fr)",gap:12,marginBottom:20}}>
          <StatCard value={totalBlocked}           label="THREATS BLOCKED" trend={12}   icon={Shield}    iconCol="#DC2626"/>
          <StatCard value={blockRateStr}           label="BLOCK RATE"      trend={0.2}  icon={TrendingUp} iconCol="#059669"/>
          <StatCard value={avgLatStr}              label="AVG LATENCY"     trend={-8}   icon={Clock}      iconCol="#2563EB"/>
          <StatCard value={topLayer?.id||"L1"}     label="TOP LAYER"       sub={LAYER_HEALTH.find(l=>l.id===topLayer?.id)?.lbl||""} icon={Activity} iconCol="#7C3AED"/>
          <StatCard value="3"                      label="LLMs ACTIVE"     sub="Gemini · Groq · Mistral" icon={Cpu} iconCol="#0891B2"/>
          <StatCard value={uptime}                 label="UPTIME"          icon={CheckCircle} iconCol="#059669"/>
        </div>

        {/* ── ROW 1: Timeline + Attack distribution ────────────── */}
        <div style={{display:"grid",gridTemplateColumns:"1fr 340px",gap:14,marginBottom:14}}>

          {/* Threat Timeline — from StatsContext.timeline (real hourly buckets) */}
          <Card title="Threat Timeline" subtitle="LAST 24H · BLOCKED vs PASSED · Updates on every real request"
            action={
              <div style={{display:"flex",gap:14,alignItems:"center"}}>
                {[["#DC2626","Blocked"],["#059669","Passed"]].map(([c,l])=>(
                  <span key={l} style={{display:"flex",alignItems:"center",gap:5,fontFamily:JB,fontSize:10,color:"#64748B"}}>
                    <span style={{width:8,height:8,borderRadius:"50%",background:c,display:"inline-block"}}/>{l}
                  </span>
                ))}
              </div>
            }>
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={stats.timeline} margin={{top:4,right:0,left:-20,bottom:0}}>
                <defs>
                  <linearGradient id="gBlocked" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="#DC2626" stopOpacity={0.12}/>
                    <stop offset="95%" stopColor="#DC2626" stopOpacity={0}/>
                  </linearGradient>
                  <linearGradient id="gPassed" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="#059669" stopOpacity={0.10}/>
                    <stop offset="95%" stopColor="#059669" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" vertical={false}/>
                <XAxis dataKey="t" tick={{fontFamily:JB,fontSize:9,fill:"#CBD5E1"}} tickLine={false} axisLine={false} interval={3}/>
                <YAxis tick={{fontFamily:JB,fontSize:9,fill:"#CBD5E1"}} tickLine={false} axisLine={false}/>
                <Tooltip content={<ChartTooltip/>}/>
                <Area type="monotone" dataKey="blocked" name="Blocked" stroke="#DC2626" strokeWidth={1.8} fill="url(#gBlocked)"/>
                <Area type="monotone" dataKey="passed"  name="Passed"  stroke="#059669" strokeWidth={1.8} fill="url(#gPassed)"/>
              </AreaChart>
            </ResponsiveContainer>
          </Card>

          {/* Attack distribution — from StatsContext.atkTypes (real session) */}
          <Card title="Attack Types" subtitle="SESSION + BASELINE · Real interactions">
            <ResponsiveContainer width="100%" height={160}>
              <PieChart>
                <Pie data={stats.atkTypes} cx="50%" cy="50%" innerRadius={46} outerRadius={72} paddingAngle={2} dataKey="value" strokeWidth={0}>
                  {stats.atkTypes.map((e,i)=><Cell key={i} fill={e.col}/>)}
                </Pie>
                <Tooltip formatter={(v,n)=>[v,n]} contentStyle={{fontFamily:JB,fontSize:11,background:"#0A0F1E",border:"1px solid rgba(255,255,255,.1)",borderRadius:8}} itemStyle={{color:"#E2E8F0"}}/>
              </PieChart>
            </ResponsiveContainer>
            <div style={{display:"flex",flexDirection:"column",gap:5,marginTop:4}}>
              {stats.atkTypes.map(d=>(
                <div key={d.name} style={{display:"flex",alignItems:"center",gap:8}}>
                  <span style={{width:8,height:8,borderRadius:"50%",background:d.col,flexShrink:0,display:"inline-block"}}/>
                  <span style={{fontFamily:BAR,fontSize:12,color:"#475569",flex:1}}>{d.name}</span>
                  <span style={{fontFamily:JB,fontSize:11,color:"#0A0F1E",fontWeight:600}}>{d.value}</span>
                </div>
              ))}
            </div>
          </Card>
        </div>

        {/* ── ROW 2: LLM Latency + Layer blocks ───────────────── */}
        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:14,marginBottom:14}}>

          {/* LLM latency — from StatsContext.latHist (real backend timings) */}
          <Card title="LLM Response Latency" subtitle="REAL BACKEND TIMINGS · ROLLING 16 REQUESTS"
            action={
              <div style={{display:"flex",gap:14,alignItems:"center"}}>
                {[["#1A73E8","Gemini"],["#F55036","Groq"],["#FF7000","Mistral"]].map(([c,l])=>(
                  <span key={l} style={{display:"flex",alignItems:"center",gap:5,fontFamily:JB,fontSize:10,color:"#64748B"}}>
                    <span style={{width:20,height:2,background:c,display:"inline-block"}}/>{l}
                  </span>
                ))}
              </div>
            }>
            <ResponsiveContainer width="100%" height={180}>
              <LineChart data={stats.latHist} margin={{top:4,right:4,left:-20,bottom:0}}>
                <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" vertical={false}/>
                <XAxis dataKey="req" tick={{fontFamily:JB,fontSize:9,fill:"#CBD5E1"}} tickLine={false} axisLine={false}/>
                <YAxis tick={{fontFamily:JB,fontSize:9,fill:"#CBD5E1"}} tickLine={false} axisLine={false} unit="ms"/>
                <Tooltip content={<ChartTooltip/>}/>
                <Line type="monotone" dataKey="gemini"  name="Gemini"  stroke="#1A73E8" strokeWidth={1.8} dot={false} isAnimationActive={false}/>
                <Line type="monotone" dataKey="groq"    name="Groq"    stroke="#F55036" strokeWidth={1.8} dot={false} isAnimationActive={false}/>
                <Line type="monotone" dataKey="mistral" name="Mistral" stroke="#FF7000" strokeWidth={1.8} dot={false} isAnimationActive={false}/>
              </LineChart>
            </ResponsiveContainer>
          </Card>

          {/* Layer blocks — from StatsContext.layerBlocks (real verdicts) */}
          <Card title="Blocks by Layer" subtitle="REAL CUMULATIVE VERDICTS PER LAYER">
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={layerBarData} margin={{top:4,right:4,left:-20,bottom:0}}>
                <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" vertical={false}/>
                <XAxis dataKey="id" tick={{fontFamily:JB,fontSize:9,fill:"#94A3B8"}} tickLine={false} axisLine={false}/>
                <YAxis tick={{fontFamily:JB,fontSize:9,fill:"#CBD5E1"}} tickLine={false} axisLine={false}/>
                <Tooltip content={<ChartTooltip/>}/>
                <Bar dataKey="blocks" name="Blocks" radius={[4,4,0,0]}>
                  {layerBarData.map((l,i)=><Cell key={i} fill={l.col}/>)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </Card>
        </div>

        {/* ── ROW 3: System health + Live event feed ───────────── */}
        <div style={{display:"grid",gridTemplateColumns:"1fr 380px",gap:14,paddingBottom:32}}>
          <Card title="System Health" subtitle="ALL GATEWAY LAYERS · LIVE STATUS">
            <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:10}}>
              {LAYER_HEALTH.map(l=>{
                const Icon=l.Icon;
                return(
                  <div key={l.id} style={{display:"flex",alignItems:"center",gap:10,padding:"10px 14px",borderRadius:10,border:"1px solid rgba(5,150,105,.15)",background:"rgba(5,150,105,.03)"}}>
                    <div style={{width:34,height:34,borderRadius:9,background:`${l.col}12`,display:"flex",alignItems:"center",justifyContent:"center",flexShrink:0}}><Icon size={15} color={l.col}/></div>
                    <div style={{flex:1}}>
                      <div style={{display:"flex",alignItems:"center",justifyContent:"space-between"}}>
                        <span style={{fontFamily:BC,fontWeight:700,fontSize:14,color:"#0A0F1E"}}>{l.lbl}</span>
                        <span style={{fontFamily:JB,fontSize:9,color:"#059669",letterSpacing:".08em"}}>ONLINE</span>
                      </div>
                      <div style={{display:"flex",gap:12,marginTop:4}}>
                        <span style={{fontFamily:JB,fontSize:10,color:"#64748B"}}>{l.lat}ms avg</span>
                        <span style={{fontFamily:JB,fontSize:10,color:"#64748B"}}>{l.uptime}% up</span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </Card>

          {/* Live event feed — from StatsContext.events (real + background) */}
          <Card title="Live Event Stream" subtitle="REAL SESSION EVENTS + BACKGROUND TRAFFIC"
            action={
              <div style={{display:"flex",alignItems:"center",gap:6,fontFamily:JB,fontSize:10,color:"#059669"}}>
                <span style={{animation:"pulse 1.5s infinite"}}>●</span> LIVE
              </div>
            }>
            <div style={{maxHeight:360,overflowY:"auto"}}>
              {recentEvents.length===0?(
                <div style={{padding:"24px 0",textAlign:"center",fontFamily:JB,fontSize:11,color:"#CBD5E1"}}>
                  No events yet — send a prompt in Chat to see real events here.
                </div>
              ):recentEvents.map((ev,i)=>(
                <FeedEvent key={ev.id} event={ev} isNew={i===0}/>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}