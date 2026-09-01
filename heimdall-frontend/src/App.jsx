/**
 * App.jsx — v2 (improved)
 *
 * Improvements:
 * 1. Each page wrapped in ErrorBoundary — crash in one page doesn't kill the app
 * 2. ToastProvider added — toast.success/error/warn/info available everywhere
 * 3. Single font load via FontLoader (unchanged)
 * 4. BackendBanner is NOT global here — each page that uses useSSE owns its own
 *    isConnected state and renders BackendBanner locally (more accurate per-page status)
 */
import { useEffect, Suspense } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Home         from "./pages/Home";
import Chat         from "./pages/Chat";
import Simulation   from "./pages/Simulation";
import Analytics    from "./pages/Analytics";
import About        from "./pages/About";
import { StatsProvider }  from "./context/StatsContext";
import { ToastProvider }  from "./components/Toast";
import ErrorBoundary      from "./components/ErrorBoundary";
import "./styles/tokens.css";

function PageLoader() {
  return (
    <div style={{ height: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "#F8FAFC" }}>
      <div style={{ width: 32, height: 32, border: "2px solid #E2E8F0", borderTopColor: "#0A0F1E", borderRadius: "50%", animation: "spin .7s linear infinite" }} />
    </div>
  );
}

function FontLoader() {
  useEffect(() => {
    if (document.getElementById("heimdall-fonts")) return;
    const link = document.createElement("link");
    link.id   = "heimdall-fonts";
    link.rel  = "stylesheet";
    link.href = "https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@300;400;500;600;700;900&family=Barlow:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500;600&display=swap";
    document.head.appendChild(link);
  }, []);
  return null;
}

const wrapPage = (Page) => (
  <ErrorBoundary>
    <Suspense fallback={<PageLoader />}>
      <Page />
    </Suspense>
  </ErrorBoundary>
);

export default function App() {
  return (
    <StatsProvider>
      <ToastProvider>
        <FontLoader />
        <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <Routes>
            <Route path="/"           element={wrapPage(Home)}/>
            <Route path="/chat"       element={wrapPage(Chat)}/>
            <Route path="/simulation" element={wrapPage(Simulation)}/>
            <Route path="/analytics"  element={wrapPage(Analytics)}/>
            <Route path="/about"      element={wrapPage(About)}/>
          </Routes>
        </BrowserRouter>
      </ToastProvider>
    </StatsProvider>
  );
}
