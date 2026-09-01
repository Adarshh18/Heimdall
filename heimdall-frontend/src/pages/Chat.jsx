/**
 * Chat.jsx — HEIMDALL real-time chat interface
 *
 * Changes from original:
 * 1. Calls StatsContext.recordEvent() after every PASS/BLOCK verdict
 *    → Analytics + Home stats update live from real interactions
 * 2. LLM_POOL.texts (hardcoded response strings) removed completely.
 *    LLM panel now shows real backend text or a "backend offline" notice.
 * 3. buildLLM() (hardcoded fallback) removed — when backend is down the
 *    LLM section stays empty rather than showing fake canned text.
 * 4. buildDNA() retained as a shape-fallback for display only (severity /
 *    flags come from attackDNA sent by backend when available).
 * 5. generateAttack() wired to Red Team button — gets a real attack prompt
 *    from the backend instead of picking from a static JS array.
 * 6. Navigation uses the existing useNavigate pattern (unchanged).
 */
import { useState, useEffect, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useSSE }          from "../hooks/useSSE.js";
import BackendBanner        from "../components/BackendBanner.jsx";
import {
  RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  Radar, ResponsiveContainer
} from "recharts";
import {
  Shield, Send, AlertTriangle, CheckCircle, XCircle,
  Zap, Clock, Search, Filter, Cpu, Eye, Database,
  Activity, Radio, Terminal, RotateCcw, ChevronRight
} from "lucide-react";

/* ── Tokens ───────────────────────────────────────────────────── */
const BC  = "'Barlow Condensed', sans-serif";
const JB  = "'JetBrains Mono', monospace";
const BAR = "'Barlow', sans-serif";

/* ── Layer definitions ────────────────────────────────────────── */
const LAYER_DEFS = [
  {id:"L1",label:"Pattern Engine",  group:"G1",color:"#2563EB",Icon:Search,  desc:"Regex & signature matching"},
  {id:"L2",label:"Sanitizer",       group:"G1",color:"#7C3AED",Icon:Filter,  desc:"Input normalization"},
  {id:"L3",label:"ML Classifier",   group:"G1",color:"#0891B2",Icon:Cpu,     desc:"Semantic similarity detection"},
  {id:"L4",label:"Intent Engine",   group:"G1",color:"#059669",Icon:Eye,     desc:"Goal & intent analysis"},
  {id:"AG",label:"Agentic Core",    group:"AG",color:"#6366F1",Icon:Cpu,     desc:"300-token dossier decision"},
  {id:"O2",label:"Leakage Detector",group:"G2",color:"#DC2626",Icon:Database,desc:"PII & exfiltration scan"},
  {id:"O3",label:"Behavior Monitor",group:"G2",color:"#D97706",Icon:Activity,desc:"Response drift analysis"},
  {id:"O4",label:"Tool Validator",  group:"G2",color:"#7C3AED",Icon:Radio,   desc:"Agentic call validation"},
];

/* ── Static prompts for UI hints only (not used as LLM responses) ── */
const SAFE_QS = [
  "What is 2 + 2?",
  "How does HTTPS encryption work?",
  "Explain transformers in AI",
  "Write a haiku about security",
];

/* ── LLM display metadata (name + badge colour only — text comes from backend) ── */
const LLM_META = {
  gemini:  { name:"GEMINI 1.5 FLASH", badge:"#1A73E8" },
  groq:    { name:"LLAMA 3 70B (GROQ)", badge:"#F55036" },
  mistral: { name:"MISTRAL SMALL",     badge:"#FF7000" },
};

/* ── buildDNA — shape-only fallback when backend attackDNA is null ── */
function buildDNA(layer) {
  const cls = layer.id==="L1" ? "DIRECT INJECTION" : layer.id==="L4" ? "IDENTITY OVERRIDE" : "SEMANTIC ATTACK";
  const sev = layer.id==="L1" ? 0.97 : layer.id==="L4" ? 0.89 : 0.84;
  return {
    cls, sev,
    lid:layer.id, llabel:layer.label,
    flags: layer.id==="L1"
      ? ["instruction_override","system_bypass"]
      : layer.id==="L4"
      ? ["identity_manipulation","role_confusion","goal_hijacking"]
      : ["semantic_attack","jailbreak","alignment_exploit"],
    radar:[
      {m:"Injection",    v:layer.id==="L1"?97:68},
      {m:"Intent",       v:layer.id==="L4"?94:62},
      {m:"Jailbreak",    v:layer.id==="L3"?91:74},
      {m:"Exfiltration", v:28},
      {m:"Manipulation", v:layer.id==="L4"?88:55},
      {m:"Tool Abuse",   v:19},
    ],
  };
}

/* ── CSS ──────────────────────────────────────────────────────── */
const STYLES = `
  @keyframes pulse   {0%,100%{opacity:1;transform:scale(1)}50%{opacity:.38;transform:scale(.82)}}
  @keyframes blink   {0%,100%{opacity:1}50%{opacity:0}}
  @keyframes scan    {0%{left:-38%}100%{left:138%}}
  @keyframes slideIn {from{opacity:0;transform:translateX(-6px)}to{opacity:1;transform:translateX(0)}}
  @keyframes popIn   {from{opacity:0;transform:scale(.94) translateY(6px)}to{opacity:1;transform:scale(1) translateY(0)}}
  @keyframes fadeUp  {from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
  @keyframes spin    {from{transform:rotate(0)}to{transform:rotate(360deg)}}

  .layer-row{animation:slideIn .25s ease}
  .verdict  {animation:popIn .4s cubic-bezier(.34,1.56,.64,1)}
  .llm-card {animation:fadeUp .4s ease}
  .dna-card {animation:popIn .5s ease}
  .msg-in   {animation:slideIn .25s ease}

  .qbtn:hover  {background:#F1F5F9!important;border-color:#CBD5E1!important}
  .send:hover  {background:#1E293B!important}
  .rtbtn:hover {background:rgba(220,38,38,.07)!important}
  .nlink:hover {color:#0A0F1E!important}
  .rsbtn:hover {color:#475569!important}

  textarea:focus{outline:none!important;border-color:#334155!important;box-shadow:0 0 0 3px rgba(15,23,42,.06)!important}
  ::-webkit-scrollbar{width:4px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:#E2E8F0;border-radius:2px}
`;

/* ── LayerRow ─────────────────────────────────────────────────── */
function LayerRow({ layer }) {
  const {id,label,color,Icon,status,latency} = layer;
  const idle=status==="idle", run=status==="running";
  const pass=status==="pass",  blk=status==="block", flag=status==="flag";
  // flag = amber warning (suspicious but not blocked); blk = red (hard block)
  const stCol = idle?"#CBD5E1" : run?color : pass?"#059669" : blk?"#DC2626" : flag?"#D97706" : "#CBD5E1";
  const borderCol = blk?"rgba(220,38,38,.28)" : flag?"rgba(217,119,6,.28)" : pass?"rgba(5,150,105,.22)" : run?`${color}30` : "#E2E8F0";
  const bgCol     = blk?"rgba(220,38,38,.04)"  : flag?"rgba(251,191,36,.04)" : pass?"rgba(5,150,105,.03)" : run?"rgba(255,255,255,.9)" : "rgba(248,250,252,.6)";
  const barBg     = pass?"#E8FDF5" : blk?"#FEF2F2" : flag?"#FFFBEB" : "#F1F5F9";
  return (
    <div className="layer-row" style={{display:"flex",alignItems:"center",gap:10,padding:"10px 14px",borderRadius:9,border:`1px solid ${borderCol}`,background:bgCol,transition:"all .35s"}}>
      <span style={{fontFamily:JB,fontSize:10,letterSpacing:".08em",color:stCol,width:22,flexShrink:0}}>{id}</span>
      <Icon size={13} color={stCol} style={{flexShrink:0}}/>
      <span style={{fontFamily:BC,fontWeight:700,fontSize:14,color:idle?"#94A3B8":"#0F172A",flex:1,letterSpacing:".04em"}}>{label}</span>
      <div style={{flex:2,height:3,background:barBg,borderRadius:2,overflow:"hidden",position:"relative"}}>
        {run &&<div style={{position:"absolute",top:0,bottom:0,width:"36%",animation:"scan 1.05s ease-in-out infinite",background:`linear-gradient(90deg,transparent,${color},transparent)`}}/>}
        {pass&&<div style={{width:"100%",height:"100%",background:"#059669",borderRadius:2}}/>}
        {blk &&<div style={{width:"100%",height:"100%",background:"#DC2626",borderRadius:2}}/>}
        {flag&&<div style={{width:"66%",height:"100%",background:"#D97706",borderRadius:2}}/>}
      </div>
      <span style={{fontFamily:JB,fontSize:10,letterSpacing:".08em",color:stCol,width:60,textAlign:"right",flexShrink:0}}>
        {idle?"——":run?<span style={{animation:"blink 1s infinite"}}>SCAN…</span>:pass?"✓ PASS":blk?"✗ BLOCK":"⚑ FLAG"}
      </span>
      <span style={{fontFamily:JB,fontSize:10,color:"#94A3B8",width:34,textAlign:"right",flexShrink:0}}>
        {(pass||blk||flag)?`${latency}ms`:run?<span style={{color,animation:"pulse 1s infinite"}}>…</span>:""}
      </span>
    </div>
  );
}

/* ── VerdictBadge ─────────────────────────────────────────────── */
function VerdictBadge({ verdict }) {
  const ok = verdict==="PASS";
  return (
    <div className="verdict" style={{display:"flex",alignItems:"center",gap:14,padding:"16px 20px",borderRadius:12,background:ok?"rgba(5,150,105,.055)":"rgba(220,38,38,.055)",border:`1.5px solid ${ok?"rgba(5,150,105,.22)":"rgba(220,38,38,.22)"}`}}>
      <div style={{width:42,height:42,borderRadius:"50%",background:ok?"#059669":"#DC2626",display:"flex",alignItems:"center",justifyContent:"center",flexShrink:0}}>
        {ok?<CheckCircle size={22} color="#fff" strokeWidth={2.5}/>:<XCircle size={22} color="#fff" strokeWidth={2.5}/>}
      </div>
      <div>
        <div style={{fontFamily:BC,fontWeight:900,fontSize:30,textTransform:"uppercase",color:ok?"#059669":"#DC2626",lineHeight:1,letterSpacing:".06em"}}>{ok?"PASS":"BLOCK"}</div>
        <div style={{fontFamily:JB,fontSize:11,color:"#64748B",marginTop:3,letterSpacing:".07em"}}>
          {ok?"All 7 layers cleared — 3 LLM responses ready below":"Adversarial prompt intercepted and neutralized by HEIMDALL"}
        </div>
      </div>
    </div>
  );
}

/* ── LLMPanel — text from real backend only ──────────────────── */
function LLMPanel({ name, badge, text, lat, tok, delay=0 }) {
  return (
    <div className="llm-card" style={{flex:1,border:"1px solid #E2E8F0",borderRadius:12,overflow:"hidden",display:"flex",flexDirection:"column",animationDelay:`${delay}s`}}>
      <div style={{padding:"11px 14px",background:"#F8FAFC",borderBottom:"1px solid #E2E8F0",display:"flex",alignItems:"center",justifyContent:"space-between"}}>
        <span style={{fontFamily:JB,fontSize:10,fontWeight:600,background:badge,color:"#fff",padding:"2px 9px",borderRadius:5,letterSpacing:".06em"}}>{name}</span>
        <div style={{display:"flex",gap:10,alignItems:"center"}}>
          {lat>0&&<span style={{fontFamily:JB,fontSize:11,color:"#059669",display:"flex",alignItems:"center",gap:4}}><Clock size={10}/> {lat}ms</span>}
          {tok>0&&<span style={{fontFamily:JB,fontSize:11,color:"#94A3B8"}}>{tok}t</span>}
        </div>
      </div>
      <div style={{padding:"14px",fontSize:13,color:"#334155",lineHeight:1.68,flex:1}}>
        {text || <span style={{color:"#94A3B8",fontStyle:"italic"}}>Response pending…</span>}
      </div>
    </div>
  );
}

/* ── AttackDNA ────────────────────────────────────────────────── */
function AttackDNA({ data }) {
  return (
    <div className="dna-card" style={{border:"1px solid rgba(220,38,38,.2)",borderRadius:12,overflow:"hidden"}}>
      <div style={{background:"#080F1C",padding:"14px 18px",display:"flex",alignItems:"center",justifyContent:"space-between"}}>
        <div style={{display:"flex",alignItems:"center",gap:9}}>
          <AlertTriangle size={15} color="#F87171"/>
          <span style={{fontFamily:BC,fontWeight:700,fontSize:17,color:"#fff",textTransform:"uppercase",letterSpacing:".08em"}}>Attack DNA</span>
        </div>
        <span style={{fontFamily:JB,fontSize:11,letterSpacing:".1em",color:"#F87171",background:"rgba(220,38,38,.18)",padding:"3px 11px",borderRadius:100,border:"1px solid rgba(220,38,38,.3)"}}>{data.cls}</span>
      </div>
      <div style={{padding:"18px",display:"grid",gridTemplateColumns:"1fr 1fr",gap:20}}>
        <div>
          <div style={{fontFamily:JB,fontSize:10,color:"#64748B",letterSpacing:".1em",marginBottom:8}}>THREAT VECTOR ANALYSIS</div>
          <ResponsiveContainer width="100%" height={180}>
            <RadarChart data={data.radar} margin={{top:4,right:16,bottom:4,left:16}}>
              <PolarGrid stroke="rgba(220,38,38,.14)" radialLines={false}/>
              <PolarAngleAxis dataKey="m" tick={{fontFamily:JB,fontSize:9,fill:"#64748B"}}/>
              <PolarRadiusAxis domain={[0,100]} tick={false} axisLine={false}/>
              <Radar dataKey="v" stroke="#DC2626" fill="#DC2626" fillOpacity={0.14} strokeWidth={1.6}/>
            </RadarChart>
          </ResponsiveContainer>
        </div>
        <div style={{display:"flex",flexDirection:"column",gap:14}}>
          <div style={{fontFamily:JB,fontSize:10,color:"#64748B",letterSpacing:".1em"}}>DETECTION DETAILS</div>
          <div>
            <div style={{fontFamily:JB,fontSize:10,color:"#94A3B8",marginBottom:5}}>SEVERITY</div>
            <div style={{display:"flex",alignItems:"center",gap:8}}>
              <div style={{flex:1,height:7,background:"#F1F5F9",borderRadius:4,overflow:"hidden"}}>
                <div style={{width:`${data.sev*100}%`,height:"100%",background:"#DC2626",borderRadius:4,transition:"width .8s cubic-bezier(.34,1,.64,1)"}}/>
              </div>
              <span style={{fontFamily:JB,fontSize:12,color:"#DC2626",fontWeight:600,flexShrink:0}}>{(data.sev*100).toFixed(0)}%</span>
            </div>
          </div>
          <div>
            <div style={{fontFamily:JB,fontSize:10,color:"#94A3B8",marginBottom:6}}>TRIGGERED AT</div>
            <div style={{display:"flex",alignItems:"center",gap:8,background:"rgba(220,38,38,.05)",border:"1px solid rgba(220,38,38,.16)",borderRadius:8,padding:"9px 12px"}}>
              <span style={{fontFamily:JB,fontSize:12,color:"#DC2626",letterSpacing:".08em",fontWeight:600}}>{data.lid}</span>
              <span style={{fontFamily:BC,fontWeight:700,fontSize:15,color:"#0F172A"}}>{data.llabel}</span>
            </div>
          </div>
          <div>
            <div style={{fontFamily:JB,fontSize:10,color:"#94A3B8",marginBottom:7}}>FLAGS MATCHED</div>
            <div style={{display:"flex",flexWrap:"wrap",gap:6}}>
              {data.flags.map(f=>(
                <span key={f} style={{fontFamily:JB,fontSize:10,letterSpacing:".05em",background:"rgba(220,38,38,.07)",color:"#DC2626",padding:"2px 9px",borderRadius:4,border:"1px solid rgba(220,38,38,.14)"}}>{f}</span>
              ))}
            </div>
          </div>
          <button style={{marginTop:"auto",fontFamily:BC,fontWeight:700,fontSize:13,letterSpacing:".1em",textTransform:"uppercase",background:"transparent",color:"#64748B",border:"1px solid #E2E8F0",padding:"8px 14px",borderRadius:7,cursor:"pointer",display:"flex",alignItems:"center",gap:6,alignSelf:"flex-start",transition:"all .2s"}}>
            Export PDF <ChevronRight size={12}/>
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── Bubble ───────────────────────────────────────────────────── */
function Bubble({ role, content, verdict, blocked }) {
  const isUser=role==="user";
  return (
    <div className="msg-in" style={{display:"flex",flexDirection:"column",alignItems:isUser?"flex-end":"flex-start",gap:4}}>
      {isUser?(
        <div style={{background:"#0A0F1E",color:"#fff",borderRadius:"12px 12px 3px 12px",padding:"9px 14px",maxWidth:"90%",fontFamily:BAR,fontSize:13,lineHeight:1.58}}>{content}</div>
      ):(
        <div style={{background:blocked?"rgba(220,38,38,.05)":"rgba(5,150,105,.05)",border:`1px solid ${blocked?"rgba(220,38,38,.15)":"rgba(5,150,105,.15)"}`,borderRadius:"12px 12px 12px 3px",padding:"8px 12px",maxWidth:"90%",fontFamily:JB,fontSize:11,letterSpacing:".06em",color:blocked?"#DC2626":"#059669"}}>
          {blocked?`✗ BLOCKED by ${verdict}`:"✓ PASSED — 3 LLM responses ready"}
        </div>
      )}
      <span style={{fontFamily:JB,fontSize:10,color:"#CBD5E1"}}>{isUser?"YOU":"HEIMDALL"} · now</span>
    </div>
  );
}

/* ── GroupHead ────────────────────────────────────────────────── */
function GroupHead({ label, color }) {
  return (
    <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:8}}>
      <span style={{fontFamily:JB,fontSize:10,letterSpacing:".16em",color}}>{label}</span>
      <div style={{flex:1,height:1,background:`${color}22`}}/>
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════
   MAIN CHAT PAGE
══════════════════════════════════════════════════════════════ */
export default function Chat() {
  const [messages,  setMessages]  = useState([]);
  const [input,     setInput]     = useState("");
  const [dna,       setDna]       = useState(null);
  const [phase,     setPhase]     = useState("idle");
  const [sessId]                  = useState(()=>"sess-"+Math.random().toString(36).slice(2,8).toUpperCase());
  const msgEnd      = useRef(null);
  const taRef       = useRef(null);
  const wasStreaming = useRef(false);
  const nav = useNavigate();
  const ROUTES = {Home:"/",Chat:"/chat",Simulation:"/simulation",Analytics:"/analytics",About:"/about"};

  /* StatsContext — recordEvent is now called inside useSSE on the "complete"
     event, so stats update regardless of which page the user navigates to.
     Chat.jsx no longer needs to call recordEvent itself.                     */

  /* Real backend SSE hook */
  const {
    layers:     hookLayers,
    verdict,
    llmData:    rawLlmData,
    attackDNA,
    streaming,
    backendOk,
    sendChat:   hookSend,
    generateAttack,
    reset:      hookReset,
  } = useSSE(sessId);

  /* Merge visual metadata from LAYER_DEFS with runtime status from hook */
  const layers = LAYER_DEFS.map(def => ({
    ...def,
    ...(hookLayers.find(l=>l.id===def.id) || {status:"idle",latency:0}),
  }));

  /**
   * Normalise backend llmData → shape LLMPanel expects.
   * Text always comes from the real backend response.
   * Falls back to empty string (shows "Response pending…") if missing.
   */
  const llmData = rawLlmData ? {
    gemini:  { ...LLM_META.gemini,  text:rawLlmData.gemini?.text  || "", lat:rawLlmData.gemini?.latency_ms  ?? rawLlmData.gemini?.lat  ?? 0, tok:rawLlmData.gemini?.tokens  ?? rawLlmData.gemini?.tok  ?? 0 },
    groq:    { ...LLM_META.groq,    text:rawLlmData.groq?.text    || "", lat:rawLlmData.groq?.latency_ms    ?? rawLlmData.groq?.lat    ?? 0, tok:rawLlmData.groq?.tokens    ?? rawLlmData.groq?.tok    ?? 0 },
    mistral: { ...LLM_META.mistral, text:rawLlmData.mistral?.text || "", lat:rawLlmData.mistral?.latency_ms ?? rawLlmData.mistral?.lat ?? 0, tok:rawLlmData.mistral?.tokens ?? rawLlmData.mistral?.tok ?? 0 },
  } : null;

  /* Auto-scroll */
  useEffect(()=>{ msgEnd.current?.scrollIntoView({behavior:"smooth"}); },[messages]);

  const reset = useCallback(()=>{ hookReset(); setDna(null); setPhase("idle"); },[hookReset]);

  /* React to SSE stream completing */
  useEffect(()=>{
    if(wasStreaming.current && !streaming && verdict!==null){
      setPhase("done");
      if(verdict==="BLOCK"){
        const bl = layers.find(l=>l.status==="block");
        /* Prefer backend-supplied DNA; fall back to local shape */
        if(bl) setDna(attackDNA ?? buildDNA(bl));
        setMessages(prev=>[...prev,{role:"system",content:"",id:Date.now(),blocked:true,verdict:bl?`${bl.id} ${bl.label}`:"BLOCK"}]);
      } else {
        setMessages(prev=>[...prev,{role:"system",content:"",id:Date.now(),blocked:false,verdict:"PASS"}]);
      }
    }
    wasStreaming.current = streaming;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  },[streaming]);

  /* Phase updates while streaming */
  useEffect(()=>{
    if(!streaming) return;
    const g2active = layers.some(l=>["O2","O3","O4"].includes(l.id)&&l.status!=="idle");
    if     (g2active)   setPhase("g2");
    else if(rawLlmData) setPhase("llm");
    else                setPhase("g1");
  },[streaming,layers,rawLlmData]);

  const sendMsg = useCallback(async(msg)=>{
    if(streaming) return;
    reset();
    setMessages(prev=>[...prev,{role:"user",content:msg,id:Date.now()}]);
    setPhase("g1");
    try { await hookSend(msg); }
    catch(e){ console.error("[Chat]",e); setPhase("done"); }
  },[streaming,reset,hookSend]);

  const handleSend = useCallback(()=>{ const t=input.trim(); if(!t||streaming) return; setInput(""); sendMsg(t); },[input,streaming,sendMsg]);

  /* Red Team: use real backend-generated attack prompt */
  const handleRT = useCallback(async()=>{
    if(streaming) return;
    try {
      const prompt = await generateAttack();
      if(prompt){ setInput(prompt); setTimeout(()=>taRef.current?.focus(),50); }
    } catch { /* generateAttack logs its own errors */ }
  },[streaming,generateAttack]);

  const handleKey = useCallback(e=>{ if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();handleSend();} },[handleSend]);

  const g1 = layers.filter(l=>l.group==="G1");
  const ag = layers.find(l=>l.group==="AG");
  const g2 = layers.filter(l=>l.group==="G2");

  return (
    <div style={{fontFamily:BAR,background:"#fff",display:"flex",flexDirection:"column",height:"100vh",overflow:"hidden"}}>
      <style>{STYLES}</style>
      <BackendBanner isConnected={backendOk} />
      <nav style={{height:62,padding:"0 clamp(16px,3vw,40px)",flexShrink:0,background:"rgba(255,255,255,.97)",borderBottom:"1px solid rgba(226,232,240,.7)",display:"flex",alignItems:"center",justifyContent:"space-between",zIndex:100}}>
        <div style={{display:"flex",alignItems:"center",gap:10}}>
          <div style={{width:32,height:32,background:"#0A0F1E",borderRadius:9,display:"flex",alignItems:"center",justifyContent:"center"}}><Shield size={15} color="#fff" strokeWidth={2.5}/></div>
          <span style={{fontFamily:BC,fontWeight:900,fontSize:20,letterSpacing:".14em",color:"#0A0F1E",textTransform:"uppercase"}}>HEIMDALL</span>
          <span style={{fontFamily:JB,fontSize:11,color:"#94A3B8",letterSpacing:".08em"}}>/ CHAT</span>
        </div>
        <div style={{display:"flex",gap:26}}>
          {["Home","Chat","Simulation","Analytics","About"].map((n,i)=>(
            <span key={n} className="nlink" onClick={()=>nav(ROUTES[n])} style={{fontFamily:BC,fontWeight:700,fontSize:13,letterSpacing:".1em",textTransform:"uppercase",cursor:"pointer",color:i===1?"#0A0F1E":"#64748B",transition:"color .2s"}}>{n}</span>
          ))}
        </div>
        <div style={{display:"flex",alignItems:"center",gap:10}}>
          <span style={{fontFamily:JB,fontSize:11,color:"#94A3B8"}}>{sessId}</span>
          <div style={{width:7,height:7,borderRadius:"50%",background:streaming?"#F59E0B":phase==="done"&&verdict?(verdict==="PASS"?"#059669":"#DC2626"):"#E2E8F0",animation:streaming?"pulse .9s infinite":"none",transition:"background .4s"}}/>
        </div>
      </nav>

      {/* ── BODY ──────────────────────────────────────────────── */}
      <div style={{display:"flex",flex:1,overflow:"hidden"}}>

        {/* LEFT: conversation */}
        <div style={{width:320,flexShrink:0,borderRight:"1px solid #E2E8F0",display:"flex",flexDirection:"column",background:"#F8FAFC"}}>
          <div style={{padding:"16px 18px 12px",borderBottom:"1px solid #E2E8F0",display:"flex",alignItems:"center",justifyContent:"space-between"}}>
            <div>
              <div style={{fontFamily:BC,fontWeight:700,fontSize:16,textTransform:"uppercase",letterSpacing:".1em",color:"#0A0F1E"}}>Conversation</div>
              <div style={{fontFamily:JB,fontSize:10,color:"#94A3B8",letterSpacing:".08em",marginTop:2}}>{sessId}</div>
            </div>
            {messages.length>0&&(
              <button className="rsbtn" onClick={()=>{reset();setMessages([]);}} style={{display:"flex",alignItems:"center",gap:5,background:"none",border:"none",cursor:"pointer",fontFamily:JB,fontSize:10,color:"#CBD5E1",letterSpacing:".08em",transition:"color .2s"}}>
                <RotateCcw size={11}/> CLEAR
              </button>
            )}
          </div>
          <div style={{flex:1,overflowY:"auto",padding:"16px 18px",display:"flex",flexDirection:"column",gap:14}}>
            {messages.length===0?(
              <div style={{textAlign:"center",padding:"40px 12px"}}>
                <Terminal size={28} color="#E2E8F0" style={{margin:"0 auto 14px"}}/>
                <div style={{fontFamily:JB,fontSize:11,color:"#CBD5E1",letterSpacing:".1em",marginBottom:10}}>NO MESSAGES YET</div>
                <div style={{fontFamily:BAR,fontSize:13,color:"#94A3B8",lineHeight:1.65}}>Send a safe prompt or use Red Team mode to fire an attack vector.</div>
              </div>
            ):messages.map(m=><Bubble key={m.id} role={m.role} content={m.content} verdict={m.verdict} blocked={m.blocked}/>)}
            <div ref={msgEnd}/>
          </div>
          <div style={{padding:"14px 18px 18px",borderTop:"1px solid #E2E8F0",background:"#fff"}}>
            {messages.length===0&&(
              <div style={{display:"flex",flexWrap:"wrap",gap:6,marginBottom:10}}>
                {SAFE_QS.map(q=>(
                  <button key={q} className="qbtn" onClick={()=>{setInput(q);taRef.current?.focus();}} style={{fontFamily:JB,fontSize:10,color:"#475569",background:"#F8FAFC",border:"1px solid #E2E8F0",padding:"4px 10px",borderRadius:6,cursor:"pointer",letterSpacing:".04em",transition:"all .2s"}}>{q}</button>
                ))}
              </div>
            )}
            <textarea ref={taRef} value={input} onChange={e=>setInput(e.target.value)} onKeyDown={handleKey} disabled={streaming} rows={3} placeholder="Type a prompt… (Enter to send)" style={{width:"100%",border:"1px solid #E2E8F0",borderRadius:10,padding:"10px 12px",fontFamily:BAR,fontSize:13,color:"#0F172A",resize:"none",lineHeight:1.58,background:streaming?"#F8FAFC":"#fff",transition:"all .2s"}}/>
            <div style={{display:"flex",gap:8,marginTop:9}}>
              <button className="rtbtn" onClick={handleRT} disabled={streaming} style={{fontFamily:BC,fontWeight:700,fontSize:12,letterSpacing:".1em",textTransform:"uppercase",background:"transparent",color:"#DC2626",border:"1px solid rgba(220,38,38,.2)",padding:"9px 14px",borderRadius:8,display:"flex",alignItems:"center",gap:5,cursor:"pointer",opacity:streaming?.45:1,transition:"all .2s"}}>
                <Zap size={11} fill="#DC2626"/> Red Team
              </button>
              <button className="send" onClick={handleSend} disabled={!input.trim()||streaming} style={{flex:1,fontFamily:BC,fontWeight:700,fontSize:14,letterSpacing:".1em",textTransform:"uppercase",background:"#0A0F1E",color:"#fff",border:"none",padding:"10px",borderRadius:8,display:"flex",alignItems:"center",justifyContent:"center",gap:8,cursor:input.trim()&&!streaming?"pointer":"not-allowed",opacity:input.trim()&&!streaming?1:.45,transition:"all .2s"}}>
                {streaming?<><span style={{animation:"blink 1s infinite"}}>●</span> Processing…</>:<>Send <Send size={13}/></>}
              </button>
            </div>
          </div>
        </div>

        {/* RIGHT: analysis panel */}
        <div style={{flex:1,overflowY:"auto",padding:"22px 26px",display:"flex",flexDirection:"column",gap:18}}>
          <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",flexShrink:0}}>
            <div>
              <div style={{fontFamily:BC,fontWeight:900,fontSize:22,textTransform:"uppercase",letterSpacing:".08em",color:"#0A0F1E"}}>Real-Time Analysis</div>
              <div style={{fontFamily:JB,fontSize:11,color:"#94A3B8",letterSpacing:".07em",marginTop:2}}>
                {phase==="idle" &&"Waiting for input — send a prompt to begin"}
                {phase==="g1"  &&"→ Gateway 1 input analysis running via SSE…"}
                {phase==="llm" &&"→ Querying Gemini · Groq · Mistral in parallel…"}
                {phase==="g2"  &&"→ Gateway 2 output analysis running via SSE…"}
                {phase==="done"&&verdict==="PASS"  &&"✓ All 7 layers cleared — safe to deliver"}
                {phase==="done"&&verdict==="BLOCK" &&"✗ Adversarial prompt intercepted and neutralized"}
              </div>
            </div>
            {streaming&&<div style={{display:"flex",alignItems:"center",gap:7,fontFamily:JB,fontSize:11,color:"#F59E0B"}}><span style={{animation:"pulse .8s infinite"}}>●</span> STREAMING SSE</div>}
          </div>
          <div><GroupHead label="GATEWAY 1 — INPUT ANALYSIS" color="#60A5FA"/><div style={{display:"flex",flexDirection:"column",gap:7}}>{g1.map(l=><LayerRow key={l.id} layer={l}/>)}</div></div>
          <div><GroupHead label="AGENTIC DECISION LAYER" color="#A78BFA"/>{ag&&<LayerRow layer={ag}/>}</div>
          {llmData&&(
            <div>
              <GroupHead label="LLM RESPONSES — PARALLEL" color="#34D399"/>
              <div style={{display:"flex",gap:12}}>
                <LLMPanel {...llmData.gemini}  delay={0}  />
                <LLMPanel {...llmData.groq}    delay={0.1}/>
                <LLMPanel {...llmData.mistral} delay={0.2}/>
              </div>
            </div>
          )}
          <div><GroupHead label="GATEWAY 2 — OUTPUT ANALYSIS" color="#F87171"/><div style={{display:"flex",flexDirection:"column",gap:7}}>{g2.map(l=><LayerRow key={l.id} layer={l}/>)}</div></div>
          {verdict&&<VerdictBadge verdict={verdict}/>}
          {dna&&<AttackDNA data={dna}/>}
          {phase==="idle"&&messages.length===0&&(
            <div style={{display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",flex:1,padding:"40px 20px",textAlign:"center",border:"1.5px dashed #E2E8F0",borderRadius:16,minHeight:280}}>
              <div style={{width:56,height:56,borderRadius:14,background:"#F8FAFC",display:"flex",alignItems:"center",justifyContent:"center",marginBottom:18}}><Terminal size={24} color="#CBD5E1"/></div>
              <div style={{fontFamily:BC,fontWeight:700,fontSize:19,textTransform:"uppercase",letterSpacing:".08em",color:"#0A0F1E",marginBottom:10}}>Gateway Ready</div>
              <div style={{fontFamily:BAR,fontSize:14,color:"#64748B",lineHeight:1.7,maxWidth:360}}>Send any prompt to watch all 7 layers process it in real-time via SSE. Every layer fires an event as it completes — PASS or BLOCK.</div>
              <div style={{display:"flex",gap:10,marginTop:22,flexWrap:"wrap",justifyContent:"center"}}>
                {[["Try a safe prompt →",false],["Fire a Red Team attack →",true]].map(([hint,isRT])=>(
                  <button key={hint} onClick={()=>isRT?handleRT():(setInput(SAFE_QS[0]),taRef.current?.focus())} style={{fontFamily:JB,fontSize:11,color:isRT?"#DC2626":"#475569",background:isRT?"rgba(220,38,38,.05)":"#F8FAFC",border:`1px solid ${isRT?"rgba(220,38,38,.18)":"#E2E8F0"}`,padding:"7px 14px",borderRadius:8,cursor:"pointer",letterSpacing:".04em"}}>{hint}</button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}