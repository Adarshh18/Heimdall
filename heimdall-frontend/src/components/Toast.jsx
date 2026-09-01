/**
 * Toast.jsx
 * Lightweight toast notification system.
 * Usage:
 *   const toast = useToast();
 *   toast.success("Analysis complete");
 *   toast.error("Backend offline");
 *   toast.info("Connecting…");
 *   toast.warn("High severity detected");
 */
import { useState, useEffect, useCallback, createContext, useContext, useRef } from "react";
import { CheckCircle, AlertTriangle, XCircle, Info, X } from "lucide-react";

const ToastCtx = createContext(null);

const ICONS = {
  success: CheckCircle,
  error:   XCircle,
  warn:    AlertTriangle,
  info:    Info,
};
const COLORS = {
  success: { bg: "rgba(5,150,105,.07)",   border: "rgba(5,150,105,.22)",  icon: "#059669", text: "#065F46" },
  error:   { bg: "rgba(220,38,38,.06)",   border: "rgba(220,38,38,.22)",  icon: "#DC2626", text: "#991B1B" },
  warn:    { bg: "rgba(217,119,6,.06)",   border: "rgba(217,119,6,.22)",  icon: "#D97706", text: "#92400E" },
  info:    { bg: "rgba(37,99,235,.06)",   border: "rgba(37,99,235,.20)",  icon: "#2563EB", text: "#1E3A5F" },
};

const CSS = `
  @keyframes toastIn  { from { opacity:0; transform:translateX(24px); } to { opacity:1; transform:translateX(0); } }
  @keyframes toastOut { from { opacity:1; transform:translateX(0); }    to { opacity:0; transform:translateX(24px); } }
  .toast-enter { animation: toastIn  .22s cubic-bezier(.34,1.56,.64,1) both; }
  .toast-exit  { animation: toastOut .18s ease both; }
`;

function Toast({ id, type, message, onRemove }) {
  const [exiting, setExiting] = useState(false);
  const { bg, border, icon: iconCol, text } = COLORS[type] || COLORS.info;
  const Icon = ICONS[type] || Info;
  const JB = "'JetBrains Mono',monospace";
  const BAR = "'Barlow',sans-serif";

  const dismiss = useCallback(() => {
    setExiting(true);
    setTimeout(() => onRemove(id), 200);
  }, [id, onRemove]);

  useEffect(() => {
    const t = setTimeout(dismiss, type === "error" ? 6000 : 4000);
    return () => clearTimeout(t);
  }, [dismiss, type]);

  return (
    <div
      className={exiting ? "toast-exit" : "toast-enter"}
      style={{ display: "flex", alignItems: "flex-start", gap: 10, padding: "11px 14px", background: "#fff", border: `1px solid ${border}`, borderLeft: `3px solid ${iconCol}`, borderRadius: 10, boxShadow: "0 4px 16px rgba(0,0,0,.1)", minWidth: 280, maxWidth: 360, pointerEvents: "all" }}
    >
      <Icon size={15} color={iconCol} style={{ flexShrink: 0, marginTop: 1 }} />
      <span style={{ fontFamily: BAR, fontSize: 13, color: "#0F172A", lineHeight: 1.5, flex: 1 }}>{message}</span>
      <button onClick={dismiss} style={{ background: "none", border: "none", cursor: "pointer", padding: 0, flexShrink: 0, marginTop: 1, opacity: .5 }}>
        <X size={13} color="#64748B" />
      </button>
    </div>
  );
}

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const counter = useRef(0);

  const add = useCallback((type, message) => {
    const id = ++counter.current;
    setToasts(p => [...p.slice(-4), { id, type, message }]); // max 5 visible
    return id;
  }, []);

  const remove = useCallback(id => {
    setToasts(p => p.filter(t => t.id !== id));
  }, []);

  const toast = {
    success: (msg) => add("success", msg),
    error:   (msg) => add("error",   msg),
    warn:    (msg) => add("warn",    msg),
    info:    (msg) => add("info",    msg),
  };

  return (
    <ToastCtx.Provider value={toast}>
      <style>{CSS}</style>
      {children}
      {/* Portal-style fixed container */}
      <div style={{ position: "fixed", bottom: 20, right: 20, zIndex: 9999, display: "flex", flexDirection: "column", gap: 8, pointerEvents: "none" }}>
        {toasts.map(t => (
          <Toast key={t.id} {...t} onRemove={remove} />
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export const useToast = () => {
  const ctx = useContext(ToastCtx);
  if (!ctx) throw new Error("useToast must be inside <ToastProvider>");
  return ctx;
};
