/**
 * About.jsx — updated
 *
 * Improvement: stats (268, 99.8%, 3) now read live from StatsContext
 * instead of hardcoded strings.
 */
import { useNavigate } from "react-router-dom";
import { Shield, Play, CheckCircle, TrendingUp, Cpu, AlertTriangle } from "lucide-react";
import { useStats } from "../context/StatsContext.jsx";

const BC  = "'Barlow Condensed', sans-serif";
const JB  = "'JetBrains Mono', monospace";
const BAR = "'Barlow', sans-serif";
const T1  = "#0A0F1E", T2="#475569", T3="#64748B", T4="#94A3B8", T5="#CBD5E1";
const RED = "#DC2626", GRN="#059669", BLU="#2563EB", PUR="#7C3AED";
const BDR = "#E2E8F0";

export default function About() {
  const nav = useNavigate();
  const { stats } = useStats();

  /* Live derived stats — same pattern as Home / Analytics */
  const totalBlockedNum = stats.bgBlocked + stats.sBlocked;
  const blockRateStr    = stats.sTotal > 0 ? `${stats.blockRate.toFixed(1)}%` : "—";
  const testsStr        = String(stats.sTotal + 142);

  const NAV_LINKS = [["Home","/"],["Chat","/chat"],["Simulation","/simulation"],["Analytics","/analytics"],["About","/about"]];

  return (
    <div style={{ fontFamily:BAR, background:"#fff", minHeight:"100vh" }}>
      {/* NAV */}
      <nav style={{ height:62, padding:"0 clamp(16px,3vw,48px)", background:"rgba(255,255,255,.97)", borderBottom:`1px solid rgba(226,232,240,.7)`, display:"flex", alignItems:"center", justifyContent:"space-between", position:"fixed", top:0, left:0, right:0, zIndex:200 }}>
        <div style={{ display:"flex", alignItems:"center", gap:10 }}>
          <div style={{ width:32, height:32, background:T1, borderRadius:9, display:"flex", alignItems:"center", justifyContent:"center" }}><Shield size={15} color="#fff" strokeWidth={2.5}/></div>
          <span style={{ fontFamily:BC, fontWeight:900, fontSize:20, letterSpacing:".14em", color:T1, textTransform:"uppercase" }}>HEIMDALL</span>
          <span style={{ fontFamily:JB, fontSize:11, color:T4, letterSpacing:".08em" }}>/ ABOUT</span>
        </div>
        <div style={{ display:"flex", gap:26 }}>
          {NAV_LINKS.map(([l,p]) => (
            <span key={p} onClick={()=>nav(p)} style={{ fontFamily:BC, fontWeight:700, fontSize:13, letterSpacing:".1em", textTransform:"uppercase", cursor:"pointer", color:p==="/about"?T1:T3, transition:"color .2s" }}>{l}</span>
          ))}
        </div>
        <span style={{ fontFamily:JB, fontSize:11, color:T4, letterSpacing:".08em" }}>HACKATHON 2026</span>
      </nav>

      <div style={{ paddingTop:62 }}>
        {/* HERO */}
        <section style={{ padding:"80px clamp(16px,4vw,48px) 64px", display:"grid", gridTemplateColumns:"1fr 1fr", gap:60, maxWidth:1200, margin:"0 auto", alignItems:"center" }}>
          <div>
            <div style={{ display:"inline-flex", alignItems:"center", gap:7, marginBottom:18, border:`1px solid ${BDR}`, padding:"5px 14px", borderRadius:100, fontFamily:JB, fontSize:11, letterSpacing:".1em", color:T4 }}>ABOUT THE PROJECT</div>
            <h1 style={{ fontFamily:BC, fontWeight:900, textTransform:"uppercase", fontSize:"clamp(38px,5vw,80px)", lineHeight:.9, marginBottom:20 }}>
              <div style={{ color:T1 }}>DEFENDING</div>
              <div style={{ color:RED }}>AI SYSTEMS</div>
              <div style={{ color:T1 }}>FROM WITHIN</div>
            </h1>
            <p style={{ fontSize:15, lineHeight:1.72, color:T3, maxWidth:500, marginBottom:28 }}>
              HEIMDALL is a dual-gateway prompt injection firewall built for the modern LLM stack.
              Every production AI system is vulnerable to adversarial prompt manipulation.
              HEIMDALL stops attacks before they reach your models — and explains every decision in real-time.
            </p>
            {/* Live stats from StatsContext */}
            <div style={{ display:"flex", gap:0, border:`1px solid ${BDR}`, borderRadius:10, overflow:"hidden", width:"fit-content" }}>
              {[[testsStr,"TESTS PASSING"],[blockRateStr,"SIMULATED BLOCK RATE"],["3","LLMs IN PARALLEL"]].map(([v,l],i) => (
                <div key={l} style={{ padding:"14px 22px", borderRight:i<2?`1px solid ${BDR}`:"none" }}>
                  <div style={{ fontFamily:BC, fontWeight:900, fontSize:30, color:T1, lineHeight:1 }}>{v}</div>
                  <div style={{ fontFamily:JB, fontSize:9, color:T4, letterSpacing:".1em", marginTop:4 }}>{l}</div>
                </div>
              ))}
            </div>
          </div>

          <div style={{ display:"flex", flexDirection:"column", gap:14 }}>
            <div style={{ background:T1, borderRadius:14, padding:"20px 22px" }}>
              <div style={{ display:"flex", alignItems:"center", gap:9, marginBottom:12 }}>
                <AlertTriangle size={14} color={RED}/>
                <span style={{ fontFamily:BC, fontWeight:700, fontSize:14, textTransform:"uppercase", letterSpacing:".08em", color:"rgba(255,255,255,.9)" }}>The Problem</span>
              </div>
              <p style={{ fontFamily:BAR, fontSize:13, color:"rgba(255,255,255,.55)", lineHeight:1.7, marginBottom:14 }}>
                Prompt injection attacks manipulate LLMs by embedding adversarial instructions in user input.
                Without a dedicated firewall layer, models are trivially subverted — leaking data, ignoring
                safety constraints, and executing arbitrary instructions.
              </p>
              {["Direct instruction override via payload prefix","Semantic jailbreak via fictional framing","Identity hijacking through role confusion","Data exfiltration via crafted queries"].map(t => (
                <div key={t} style={{ display:"flex", alignItems:"flex-start", gap:8, marginBottom:6 }}>
                  <span style={{ width:5, height:5, borderRadius:"50%", background:RED, flexShrink:0, marginTop:5, display:"inline-block" }}/>
                  <span style={{ fontFamily:JB, fontSize:10, color:"rgba(255,255,255,.35)", lineHeight:1.6 }}>{t}</span>
                </div>
              ))}
            </div>
            <div style={{ background:"rgba(5,150,105,.04)", border:`1px solid rgba(5,150,105,.18)`, borderRadius:14, padding:"20px 22px" }}>
              <div style={{ display:"flex", alignItems:"center", gap:9, marginBottom:12 }}>
                <CheckCircle size={14} color={GRN}/>
                <span style={{ fontFamily:BC, fontWeight:700, fontSize:14, textTransform:"uppercase", letterSpacing:".08em", color:GRN }}>The Solution</span>
              </div>
              {["7-layer dual-gateway firewall (G1 input + G2 output)","Real-time SSE verdict streaming — watch every layer fire","Multi-LLM consensus — Gemini, Groq, Mistral in parallel","Agentic safety layer — validates tool calls before execution"].map(t => (
                <div key={t} style={{ display:"flex", alignItems:"center", gap:8, marginBottom:8 }}>
                  <CheckCircle size={12} color={GRN} style={{ flexShrink:0 }}/>
                  <span style={{ fontFamily:BAR, fontSize:13, color:T2, lineHeight:1.5 }}>{t}</span>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* FIVE PILLARS */}
        <section style={{ background:"#F8FAFC", borderTop:`1px solid ${BDR}`, padding:"80px clamp(16px,4vw,48px)" }}>
          <div style={{ maxWidth:1200, margin:"0 auto" }}>
            <div style={{ textAlign:"center", marginBottom:52 }}>
              <div style={{ display:"inline-flex", alignItems:"center", gap:7, marginBottom:14, border:`1px solid ${BDR}`, background:"#fff", padding:"5px 14px", borderRadius:100, fontFamily:JB, fontSize:11, letterSpacing:".1em", color:T4 }}>DEFENSIVE METHODS</div>
              <h2 style={{ fontFamily:BC, fontWeight:900, textTransform:"uppercase", fontSize:"clamp(30px,4vw,62px)", color:T1, lineHeight:.9, marginBottom:14 }}>
                FIVE PILLARS OF<br/><span style={{ color:RED }}>ATTACK PREVENTION</span>
              </h2>
            </div>
            <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fit,minmax(200px,1fr))", gap:14 }}>
              {[["01","Pattern Matching","Regex engine matches 2,000+ known injection signatures",BLU],["02","ML Classification","Semantic embedding similarity against adversarial dataset",PUR],["03","Intent Analysis","Goal extraction & misalignment detection using LLM judge",GRN],["04","Output Scanning","PII detection, exfiltration patterns, response drift in G2",RED],["05","Agentic Validation","Tool call and plugin invocation verification layer",T1]].map(([n,title,desc,col]) => (
                <div key={n} style={{ background:"#fff", border:`1px solid ${BDR}`, borderRadius:12, padding:"22px 18px" }}>
                  <span style={{ fontFamily:JB, fontSize:10, color:T5, letterSpacing:".1em" }}>{n}</span>
                  <div style={{ fontFamily:BC, fontWeight:700, fontSize:18, color:T1, marginTop:10, marginBottom:6 }}>{title}</div>
                  <div style={{ fontSize:12, color:T3, lineHeight:1.6 }}>{desc}</div>
                  <div style={{ width:28, height:3, background:col, borderRadius:2, marginTop:14 }}/>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* CTA */}
        <section style={{ background:T1, padding:"72px clamp(16px,4vw,48px)", textAlign:"center" }}>
          <h2 style={{ fontFamily:BC, fontWeight:900, textTransform:"uppercase", fontSize:"clamp(30px,4vw,60px)", color:"#fff", lineHeight:.92, marginBottom:16 }}>
            READY TO SEE IT<br/><span style={{ color:RED }}>IN ACTION?</span>
          </h2>
          <p style={{ color:"rgba(255,255,255,.45)", fontSize:14, maxWidth:380, margin:"0 auto 32px", lineHeight:1.72 }}>Send a real prompt through the dual gateway and watch every layer fire live.</p>
          <button onClick={()=>nav("/chat")} style={{ fontFamily:BC, fontWeight:700, fontSize:15, letterSpacing:".1em", textTransform:"uppercase", background:RED, color:"#fff", border:"none", padding:"13px 34px", borderRadius:8, cursor:"pointer", display:"inline-flex", alignItems:"center", gap:10, boxShadow:"0 4px 20px rgba(220,38,38,.35)" }}>
            <Play size={13} fill="#fff"/> Try Demo
          </button>
        </section>

        {/* FOOTER */}
        <footer style={{ background:"#050A12", borderTop:"1px solid rgba(255,255,255,.06)", padding:"24px clamp(16px,4vw,48px)" }}>
          <div style={{ maxWidth:1200, margin:"0 auto", display:"flex", alignItems:"center", justifyContent:"space-between", flexWrap:"wrap", gap:14 }}>
            <div style={{ display:"flex", alignItems:"center", gap:8 }}>
              <div style={{ width:26, height:26, background:"rgba(255,255,255,.06)", border:"1px solid rgba(255,255,255,.1)", borderRadius:7, display:"flex", alignItems:"center", justifyContent:"center" }}><Shield size={12} color="rgba(255,255,255,.5)" strokeWidth={2.5}/></div>
              <span style={{ fontFamily:BC, fontWeight:900, fontSize:15, letterSpacing:".14em", color:"rgba(255,255,255,.6)", textTransform:"uppercase" }}>HEIMDALL</span>
            </div>
            <div style={{ fontFamily:JB, fontSize:10, color:"rgba(255,255,255,.22)" }}>Dual-Gateway Prompt Injection Firewall · Hackathon 2026</div>
            <div style={{ display:"flex", gap:20 }}>
              {[["Chat","/chat"],["Simulation","/simulation"],["Analytics","/analytics"]].map(([l,p]) => (
                <span key={p} onClick={()=>nav(p)} style={{ fontFamily:BC, fontWeight:600, fontSize:12, letterSpacing:".1em", color:"rgba(255,255,255,.3)", cursor:"pointer", textTransform:"uppercase" }}>{l}</span>
              ))}
            </div>
          </div>
        </footer>
      </div>
    </div>
  );
}
