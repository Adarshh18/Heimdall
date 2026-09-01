/**
 * useSSE.js — HEIMDALL frontend SSE hook  [FIXED v2]
 *
 * ─────────────────────────────────────────────────────────────
 * ROOT CAUSE of ALL original bugs:
 *   Backend sends  data.event = "layer" | "verdict" | "complete" | ...
 *   Original code switched on data.type — never matched → ALL events dropped
 * ─────────────────────────────────────────────────────────────
 *
 * Backend SSE schema (the data.event field):
 *
 *  "layer"     {gateway, layer, name, status, latency_ms, flags, new_flags,
 *               confidence, attack_type, transforms, reason, tokens_used}
 *               status: RUNNING | PASS | FLAG | BLOCK | SANITIZED | MISS | HIT
 *
 *  "verdict"   {gateway, verdict, confidence, attack_type, flags, latency_ms}
 *               verdict: PASS | BLOCK | SANITIZE
 *
 *  "llm_start" {providers}
 *
 *  "llm_result" {provider, ok, latency_ms, tokens_used, model, text_preview, error}
 *                one event per provider — arrives as each LLM responds
 *
 *  "complete"  {reply, blocked, sanitized, total_latency_ms, llm_responses}
 *               llm_responses: { gemini:{text,ok,latency_ms,tokens_used,...}, groq, mistral }
 *
 *  "error"     {detail}
 *  "done"      {}        — stream closed cleanly
 *  "ping"      {}        — keepalive, ignore
 *  "timeout"   {}        — session TTL expired
 *
 * Layer ID translation:
 *   Backend "L5" (Agentic Decision) → Frontend "AG"
 *   Backend "L0", "O1", "O5" are not in the frontend layer array → skipped
 */
import { useState, useEffect, useRef, useCallback } from "react";
import { useStats } from "../context/StatsContext.jsx";  // for direct recordEvent calls

const BASE_URL = import.meta.env.VITE_HEIMDALL_URL || "/api";

/* ─── Layer IDs in UI — must match LAYER_DEFS in Chat.jsx / Simulation.jsx ── */
const LAYER_IDS = ["L1", "L2", "L3", "L4", "AG", "O2", "O3", "O4"];
const initLayers = () => LAYER_IDS.map(id => ({ id, status: "idle", latency: 0, score: 0 }));

/* Bug #2 fix: backend uses "L5" for agentic, frontend shows it as "AG" */
const BACKEND_TO_FRONTEND_ID = { L5: "AG" };
const mapLayerId = (id) => BACKEND_TO_FRONTEND_ID[id] ?? id;

/**
 * Bug #3 fix: backend never sends a "score" field.
 * Derive 0–1 threat score from whichever signal is available.
 * Priority: confidence > similarity > new_flags/4 > flags/6
 */
function deriveScore(evt) {
  if (typeof evt.confidence === "number") return Math.min(1, evt.confidence);
  if (typeof evt.similarity === "number") return Math.min(1, evt.similarity);
  if (typeof evt.new_flags  === "number") return Math.min(1, evt.new_flags / 4);
  if (typeof evt.flags      === "number") return Math.min(1, evt.flags / 6);
  return 0;
}

/**
 * Map backend status strings to the values LayerRow expects.
 *   SANITIZED → "pass"   (input cleaned but allowed through)
 *   FLAG      → "flag"   (suspicious but not blocked)
 *   RUNNING   → "running"
 *   BLOCK     → "block"
 *   PASS / MISS / HIT / anything else → "pass"
 */
function mapStatus(backendStatus) {
  switch (backendStatus) {
    case "RUNNING":   return "running";
    case "FLAG":      return "flag";
    case "BLOCK":     return "block";
    case "SANITIZED": return "pass";
    default:          return "pass";
  }
}

/* ─── Main hook ────────────────────────────────────────────────────────────── */
export function useSSE(sessionId) {
  const [layers,    setLayers]  = useState(initLayers);
  const [verdict,   setVerdict] = useState(null);   // null | "PASS" | "BLOCK"
  const [llmData,   setLlmData] = useState(null);   // { gemini:{...}, groq:{...}, mistral:{...} }
  const [attackDNA, setDNA]     = useState(null);   // stays null — pages use buildDNA() fallback
  const [streaming, setStream]  = useState(false);
  const [stats,     setStats]   = useState(null);
  const [backendOk, setBackend] = useState(true);   // false while backend is unreachable

  const esRef           = useRef(null);
  const sessionRef      = useRef(sessionId);
  const llmAccRef       = useRef({});   // accumulates partial llm_result events per provider
  const blockedLayerRef = useRef(null); // which layer triggered BLOCK
  const attackTypeRef   = useRef(null); // from verdict.attack_type
  const latenciesRef    = useRef({});   // per-provider latency from llm_result events
  const failCountRef    = useRef(0);    // consecutive EventSource failures — drives backoff
  const retryTimerRef   = useRef(null); // pending setTimeout for reconnect

  /* Pull recordEvent out of StatsContext so SSE can update stats
     regardless of which page the user is currently on              */
  const { recordEvent } = useStats();
  const recordEventRef  = useRef(recordEvent);
  recordEventRef.current = recordEvent;   // keep ref current without restarting effects

  sessionRef.current = sessionId;

  /* ── Open SSE stream (with exponential backoff) ─────────────────────────── */
  useEffect(() => {
    if (!sessionId) return;
    let destroyed = false;

    function openStream() {
      if (destroyed) return;

      llmAccRef.current    = {};
      blockedLayerRef.current = null;
      attackTypeRef.current   = null;
      latenciesRef.current    = {};

      const url = `${BASE_URL}/stream/${sessionId}`;
      const es  = new EventSource(url);
      esRef.current = es;

      es.onopen = () => {
        failCountRef.current = 0;    // reset backoff on successful connect
        setBackend(true);
      };

      es.onmessage = (rawEvt) => {
        let data;
        try { data = JSON.parse(rawEvt.data); } catch { return; }

        // ────────────────────────────────────────────────────────────────
        // BUG #1 FIX: read data.event (not data.type which never existed)
        // ────────────────────────────────────────────────────────────────
        switch (data.event) {

          /* ── Layer progress ──────────────────────────────────────────── */
          case "layer": {
            // BUG #2 FIX: translate L5 → AG
            const lid    = mapLayerId(data.layer);
            // BUG #8 FIX: skip L0, O1, O5 — not in the frontend layer array
            if (!LAYER_IDS.includes(lid)) break;

            const status = mapStatus(data.status);
            // BUG #3 FIX: derive score from real backend fields
            const score  = deriveScore(data);

            setLayers(prev => prev.map(l =>
              l.id === lid
                ? { ...l, status, latency: data.latency_ms ?? 0, score }
                : l
            ));

            // Track which layer blocked for recordEvent
            if (data.status === "BLOCK") {
              blockedLayerRef.current = lid;
              setVerdict("BLOCK");
            }
            break;
          }

          /* ── Gateway-level verdict ───────────────────────────────────── */
          case "verdict": {
            if (data.attack_type) attackTypeRef.current = data.attack_type;
            if (data.verdict === "BLOCK") setVerdict("BLOCK");
            else setVerdict("PASS");
            break;
          }

          /* ── LLM phase starting ──────────────────────────────────────── */
          case "llm_start":
            break;

          /* ── BUG #5 FIX: accumulate per-provider results ─────────────── */
          case "llm_result": {
            const p = data.provider;
            if (!p) break;
            // Track latencies for recordEvent
            if (data.latency_ms) {
              latenciesRef.current = { ...latenciesRef.current, [p]: data.latency_ms };
            }
            llmAccRef.current = {
              ...llmAccRef.current,
              [p]: {
                text:        data.text_preview ?? "",
                ok:          data.ok           ?? false,
                latency_ms:  data.latency_ms   ?? 0,
                tokens_used: data.tokens_used  ?? 0,
                model:       data.model        ?? "",
                error:       data.error        ?? "",
              },
            };
            setLlmData({ ...llmAccRef.current });
            break;
          }

          /* ── BUG #4 FIX: complete resets streaming + populates full data ─ */
          case "complete": {
            // Full response text replaces text_preview snippets
            if (data.llm_responses) {
              // Also extract latencies from llm_responses for recordEvent
              const lrs = data.llm_responses;
              const lats = {};
              ["gemini","groq","mistral"].forEach(p => {
                if (lrs[p]?.latency_ms) lats[p] = lrs[p].latency_ms;
              });
              if (Object.keys(lats).length) latenciesRef.current = lats;
              setLlmData(data.llm_responses);
            }

            const finalVerdict = data.blocked ? "BLOCK" : "PASS";
            setVerdict(finalVerdict);

            // ── Wire stats into StatsContext directly from SSE ──────────
            // This means stats update even if the user navigated to a
            // different page before this event arrived.
            recordEventRef.current?.({
              verdict:    finalVerdict,
              layer:      blockedLayerRef.current ?? "O4",
              attackType: attackTypeRef.current   ?? null,
              latencies:  latenciesRef.current,
            });

            // BUG #4 FIX: reset streaming so wasStreaming effects fire
            setStream(false);
            break;
          }

          /* ── BUG #6 FIX: lowercase "error" + data.detail not data.message */
          case "error":
            console.error("[useSSE] Server error:", data.detail ?? data.message ?? "unknown");
            setStream(false);
            break;

          case "done":
          case "timeout":
            setStream(false);
            break;

          case "ping":
            break;

          default:
            break;
        }
      };

      es.onerror = () => {
        // Don't log every retry — only first failure and then every 5th
        const n = ++failCountRef.current;
        if (n === 1) {
          console.warn("[useSSE] Backend unreachable — will retry with backoff…");
          setBackend(false);
        }
        es.close();
        esRef.current = null;

        // Stop retrying after 10 consecutive failures — backend is offline
        // The user will see the BackendBanner; they can refresh when ready.
        if (n >= 10) {
          if (n === 10) console.warn("[useSSE] Giving up after 10 failures. Refresh when backend is running.");
          return;
        }

        // Exponential backoff: 1s, 2s, 4s, 8s … capped at 16s
        const delay = Math.min(1000 * Math.pow(2, n - 1), 16000);
        retryTimerRef.current = setTimeout(openStream, delay);
      };
    }

    openStream();

    return () => {
      destroyed = true;
      clearTimeout(retryTimerRef.current);
      esRef.current?.close();
      esRef.current = null;
    };
  }, [sessionId]);

  /* ── Reset all analysis state between requests ─────────────────────────── */
  const reset = useCallback(() => {
    setLayers(initLayers());
    setVerdict(null);
    setLlmData(null);
    setDNA(null);
    llmAccRef.current       = {};
    blockedLayerRef.current = null;
    attackTypeRef.current   = null;
    latenciesRef.current    = {};
  }, []);

  /* ── Send a chat message ─────────────────────────────────────────────────── */
  const sendChat = useCallback(async (message) => {
    if (streaming) return;
    reset();
    setStream(true);

    try {
      const res = await fetch(`${BASE_URL}/chat`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message,
          session_id: sessionRef.current,
        }),
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      // REST response is the sync fallback — SSE events are the live path
      return await res.json();

    } catch (err) {
      console.error("[useSSE] sendChat error:", err);
      setStream(false);
      throw err;
    }
  }, [streaming, reset]);

  /* ── Generate a Red Team attack prompt ──────────────────────────────────── */
  const generateAttack = useCallback(async () => {
    try {
      const res = await fetch(`${BASE_URL}/generate-attack`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionRef.current }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      return data.attack_prompt ?? "";
    } catch (err) {
      console.error("[useSSE] generateAttack error:", err);
      return "";
    }
  }, []);

  /* ── Fetch analytics stats ───────────────────────────────────────────────── */
  const fetchStats = useCallback(async () => {
    try {
      const res  = await fetch(`${BASE_URL}/stats`);
      const data = await res.json();
      setStats(data);
      return data;
    } catch (err) {
      console.error("[useSSE] fetchStats error:", err);
      return null;
    }
  }, []);

  return {
    layers,         // [{ id, status, latency, score }] — one entry per layer
    verdict,        // "PASS" | "BLOCK" | null
    llmData,        // { gemini, groq, mistral } | null
    attackDNA,      // null — Chat.jsx + Simulation.jsx use local buildDNA() fallback
    streaming,      // boolean — true while SSE events are flowing
    backendOk,      // false when backend is unreachable (drives BackendBanner)
    stats,          // Latest /stats response
    sendChat,       // (message: string) => Promise<ChatResponse>
    generateAttack, // () => Promise<string>
    fetchStats,     // () => Promise<stats>
    reset,          // () => void — clears all layer/verdict/llmData state
  };
}