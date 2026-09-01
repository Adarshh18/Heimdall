/**
 * BackendBanner.jsx
 * Renders a sticky banner when the HEIMDALL backend is offline.
 * Placed just below the fixed nav so it doesn't cover content.
 *
 * Usage: <BackendBanner isConnected={isConnected} />
 * isConnected should come from useSSE() or a health-check hook.
 */
import { useState, useEffect } from "react";
import { WifiOff, RefreshCcw, X, Terminal } from "lucide-react";

const JB  = "'JetBrains Mono', monospace";
const BAR = "'Barlow', sans-serif";
const BC  = "'Barlow Condensed', sans-serif";

export default function BackendBanner({ isConnected }) {
  const [dismissed, setDismissed] = useState(false);
  const [blinking, setBlinking] = useState(false);

  // Reset dismissed state when connection recovers
  useEffect(() => {
    if (isConnected) setDismissed(false);
  }, [isConnected]);

  // Blink the dot
  useEffect(() => {
    if (!isConnected) {
      const iv = setInterval(() => setBlinking(p => !p), 900);
      return () => clearInterval(iv);
    }
  }, [isConnected]);

  if (isConnected || dismissed) return null;

  return (
    <div style={{
      position:     "fixed",
      top:          62,        // sits right below the 62px nav
      left:         0,
      right:        0,
      zIndex:       190,
      background:   "rgba(217,119,6,.08)",
      borderBottom: "1px solid rgba(217,119,6,.25)",
      padding:      "8px clamp(16px,3vw,48px)",
      display:      "flex",
      alignItems:   "center",
      gap:          12,
    }}>
      {/* Blinking offline dot */}
      <span style={{ width: 7, height: 7, borderRadius: "50%", background: blinking ? "#D97706" : "rgba(217,119,6,.3)", display: "inline-block", flexShrink: 0, transition: "background .3s" }} />

      <WifiOff size={13} color="#D97706" style={{ flexShrink: 0 }} />

      <span style={{ fontFamily: BAR, fontSize: 13, color: "#92400E", flex: 1 }}>
        Backend offline — running in demo mode.{" "}
        <span style={{ fontFamily: JB, fontSize: 11, color: "#B45309" }}>
          Start the middleware:{" "}
        </span>
        <code style={{ fontFamily: JB, fontSize: 11, background: "rgba(217,119,6,.12)", padding: "1px 6px", borderRadius: 4, color: "#92400E" }}>
          uvicorn heimdall_app:app --port 8000
        </code>
      </span>

      <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
        <button
          onClick={() => window.location.reload()}
          style={{ fontFamily: BC, fontWeight: 700, fontSize: 11, letterSpacing: ".1em", textTransform: "uppercase", background: "rgba(217,119,6,.12)", color: "#92400E", border: "1px solid rgba(217,119,6,.25)", padding: "5px 12px", borderRadius: 6, cursor: "pointer", display: "flex", alignItems: "center", gap: 5, transition: "all .2s" }}
        >
          <RefreshCcw size={10} /> Retry
        </button>
        <button
          onClick={() => setDismissed(true)}
          style={{ background: "none", border: "none", cursor: "pointer", padding: 4, opacity: .5, display: "flex" }}
          aria-label="Dismiss banner"
        >
          <X size={13} color="#92400E" />
        </button>
      </div>
    </div>
  );
}
