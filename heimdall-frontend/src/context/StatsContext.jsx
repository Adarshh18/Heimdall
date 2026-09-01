/**
 * StatsContext.jsx — v2 (improved)
 *
 * Improvements:
 * 1. Events capped at 200 (was unbounded → memory leak over long sessions)
 * 2. bgBlocked + layerBlocks + atkTypes persisted to localStorage
 * 3. State hydrated from localStorage on first mount
 */
import { createContext, useContext, useState, useEffect, useCallback } from "react";

const StatsCtx = createContext(null);

/* All baselines start at zero — populated only by real recordEvent() calls */
const BASELINE_LAYER_BLOCKS = { L1:0, L2:0, L3:0, L4:0, AG:0, O2:0, O3:0, O4:0 };
const BASELINE_ATK = [
  { name:"Prompt Injection", value:0, col:"#DC2626" },
  { name:"Jailbreak",        value:0, col:"#D97706" },
  { name:"Role Override",    value:0, col:"#7C3AED" },
  { name:"Indirect Inj.",    value:0, col:"#0891B2" },
  { name:"Data Exfil.",      value:0, col:"#059669" },
];
/* v2 → v3: bumped to discard any old fake-baseline values in the browser */
const LS_KEY = "heimdall_stats_v3";

function loadPersisted() {
  try { const r = localStorage.getItem(LS_KEY); return r ? JSON.parse(r) : null; }
  catch { return null; }
}
function savePersisted(bgBlocked, layerBlocks, atkTypes) {
  try { localStorage.setItem(LS_KEY, JSON.stringify({ bgBlocked, layerBlocks, atkTypes })); }
  catch { /* quota / private mode */ }
}

/* Timeline starts at zero — filled by real recordEvent() calls */
const mkTimeline = () => Array.from({ length:24 }, (_,i) => {
  const h = (new Date().getHours() - 23 + i + 24) % 24;
  return { t:`${h.toString().padStart(2,"0")}:00`, blocked:0, passed:0 };
});
/* Latency history starts at zero — filled by real recordEvent() calls */
const mkLatHist = () => Array.from({ length:16 }, (_,i) => ({
  req:i+1, gemini:0, groq:0, mistral:0,
}));

/* BG_POOL removed — fake background events disabled.
   The live event feed now shows only real session events from recordEvent(). */

export function StatsProvider({ children }) {
  const p = loadPersisted();
  const [s, setS] = useState({
    bgBlocked:   0,            // always zero — no fake baseline counter
    sTotal:0, sBlocked:0, sPassed:0,
    layerBlocks: p?.layerBlocks ?? { ...BASELINE_LAYER_BLOCKS },
    atkTypes:    p?.atkTypes    ?? BASELINE_ATK.map(a => ({ ...a })),
    events:[], latHist:mkLatHist(), timeline:mkTimeline(),
    latSum:0, latCount:0, avgLat:0, blockRate:0,
  });

  useEffect(() => { savePersisted(s.bgBlocked, s.layerBlocks, s.atkTypes); }, [s.bgBlocked, s.layerBlocks, s.atkTypes]);
  /* bgBlocked auto-increment interval removed — was generating fake counts
     BG_POOL random event interval removed — was injecting fake live events  */

  const recordEvent = useCallback(({ verdict, layer, attackType, latencies }) => {
    setS(prev => {
      const lb = { ...prev.layerBlocks };
      if (layer) lb[layer] = (lb[layer]||0)+1;
      const at = prev.atkTypes.map(a => attackType&&a.name.toLowerCase().includes(attackType.toLowerCase().slice(0,6)) ? {...a,value:a.value+1} : a);
      const ev = { id:Date.now(), verdict, layer:layer||"O4", attack:attackType, msg:verdict==="BLOCK" ? `${attackType||"Attack"} blocked at ${layer||"AG"}` : "Query passed all layers", time:new Date().toTimeString().slice(0,8), isNew:true, isSession:true };
      // Guard: only include a provider's latency if it's a finite positive number
      const validLat = latencies
        ? [latencies.gemini, latencies.groq, latencies.mistral].filter(v => Number.isFinite(v) && v > 0)
        : [];
      const lat = validLat.length > 0 ? validLat.reduce((a,b)=>a+b,0)/validLat.length : null;
      const lSum  = lat != null ? prev.latSum + lat : prev.latSum;
      const lCnt  = lat != null ? prev.latCount + 1 : prev.latCount;
      const gemL  = Number.isFinite(latencies?.gemini)  && latencies.gemini  > 0 ? latencies.gemini  : 0;
      const groqL = Number.isFinite(latencies?.groq)    && latencies.groq    > 0 ? latencies.groq    : 0;
      const mistL = Number.isFinite(latencies?.mistral) && latencies.mistral > 0 ? latencies.mistral : 0;
      const lh = [...prev.latHist.slice(1), { req:prev.latHist[prev.latHist.length-1].req+1, gemini:gemL, groq:groqL, mistral:mistL }];
      const hr = new Date().getHours();
      const tl = prev.timeline.map(t => parseInt(t.t)===hr ? {...t, blocked:verdict==="BLOCK"?t.blocked+1:t.blocked, passed:verdict==="PASS"?t.passed+1:t.passed} : t);
      const sT=prev.sTotal+1, sB=verdict==="BLOCK"?prev.sBlocked+1:prev.sBlocked, sP=verdict==="PASS"?prev.sPassed+1:prev.sPassed;
      return { ...prev, sTotal:sT, sBlocked:sB, sPassed:sP, layerBlocks:lb, atkTypes:at,
        events:[ev,...prev.events.slice(0,199)],
        latHist:lh, timeline:tl, latSum:lSum, latCount:lCnt,
        avgLat: lCnt > 0 ? lSum/lCnt : prev.avgLat,
        blockRate: sT > 0 ? parseFloat(((sB/sT)*100).toFixed(1)) : prev.blockRate };
    });
  }, []);

  return <StatsCtx.Provider value={{ stats:s, recordEvent }}>{children}</StatsCtx.Provider>;
}

export const useStats = () => {
  const ctx = useContext(StatsCtx);
  if (!ctx) throw new Error("useStats must be inside <StatsProvider>");
  return ctx;
};