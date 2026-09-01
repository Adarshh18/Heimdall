/**
 * ErrorBoundary.jsx
 * Wraps each page so a crash in one component never whites out the entire app.
 */
import { Component } from "react";
import { Shield, RotateCcw, AlertTriangle } from "lucide-react";

const T1   = "#0A0F1E";
const T3   = "#64748B";
const RED  = "#DC2626";
const BDR  = "#E2E8F0";
const BC   = "'Barlow Condensed', sans-serif";
const JB   = "'JetBrains Mono', monospace";
const BAR  = "'Barlow', sans-serif";

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, info: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, info) {
    this.setState({ info });
    console.error("[HEIMDALL ErrorBoundary]", error, info);
  }

  render() {
    if (!this.state.hasError) return this.props.children;

    const { error, info } = this.state;
    const componentStack = info?.componentStack?.trim().split("\n").slice(0, 5).join("\n");

    return (
      <div style={{ fontFamily: BAR, background: "#F8FAFC", minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", padding: 32 }}>
        <div style={{ maxWidth: 560, width: "100%", background: "#fff", border: `1px solid ${BDR}`, borderRadius: 16, overflow: "hidden" }}>
          {/* Header */}
          <div style={{ padding: "20px 24px", background: "rgba(220,38,38,.04)", borderBottom: `1px solid rgba(220,38,38,.14)`, display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{ width: 40, height: 40, background: "rgba(220,38,38,.1)", borderRadius: 10, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
              <AlertTriangle size={20} color={RED} />
            </div>
            <div>
              <div style={{ fontFamily: BC, fontWeight: 700, fontSize: 18, textTransform: "uppercase", letterSpacing: ".06em", color: RED }}>Component Error</div>
              <div style={{ fontFamily: JB, fontSize: 10, color: T3, marginTop: 2 }}>HEIMDALL caught a render error — other pages are unaffected</div>
            </div>
          </div>

          {/* Body */}
          <div style={{ padding: "20px 24px" }}>
            <div style={{ fontFamily: JB, fontSize: 11, color: RED, background: "rgba(220,38,38,.04)", border: "1px solid rgba(220,38,38,.12)", borderRadius: 8, padding: "10px 14px", marginBottom: 16, lineHeight: 1.6, wordBreak: "break-word" }}>
              {error?.message || "Unknown render error"}
            </div>

            {componentStack && (
              <details style={{ marginBottom: 20 }}>
                <summary style={{ fontFamily: JB, fontSize: 10, color: T3, cursor: "pointer", letterSpacing: ".08em", marginBottom: 6 }}>COMPONENT STACK</summary>
                <pre style={{ fontFamily: JB, fontSize: 10, color: T3, background: "#F8FAFC", border: `1px solid ${BDR}`, borderRadius: 6, padding: "10px 12px", overflow: "auto", lineHeight: 1.7, margin: 0 }}>{componentStack}</pre>
              </details>
            )}

            <div style={{ display: "flex", gap: 10 }}>
              <button
                onClick={() => this.setState({ hasError: false, error: null, info: null })}
                style={{ fontFamily: BC, fontWeight: 700, fontSize: 13, letterSpacing: ".1em", textTransform: "uppercase", background: T1, color: "#fff", border: "none", padding: "10px 20px", borderRadius: 8, cursor: "pointer", display: "flex", alignItems: "center", gap: 8 }}
              >
                <RotateCcw size={12} /> Retry
              </button>
              <button
                onClick={() => window.location.reload()}
                style={{ fontFamily: BC, fontWeight: 600, fontSize: 13, letterSpacing: ".1em", textTransform: "uppercase", background: "transparent", color: T3, border: `1.5px solid ${BDR}`, padding: "10px 18px", borderRadius: 8, cursor: "pointer" }}
              >
                Reload Page
              </button>
            </div>
          </div>

          <div style={{ padding: "12px 24px", background: "#F8FAFC", borderTop: `1px solid ${BDR}`, display: "flex", alignItems: "center", gap: 8 }}>
            <Shield size={11} color={T3} />
            <span style={{ fontFamily: JB, fontSize: 10, color: T3 }}>All other HEIMDALL pages continue to function normally</span>
          </div>
        </div>
      </div>
    );
  }
}
