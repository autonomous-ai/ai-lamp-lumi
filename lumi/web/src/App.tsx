import { useEffect, useState } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import Setup from "@/pages/Setup";
import Monitor from "@/pages/monitor";
import EditConfig from "@/pages/EditConfig";
import GwConfig from "@/pages/GwConfig";
import { checkInternet, getSetupStatus } from "@/lib/api";

// Setup gate: provisioned (online) → continue mode (Voice/Face enroll, TTS
// preview), else initial mode (offline form for AP setup). When the user
// lands on the AP IP (192.168.4.1) but the lamp already has a real LAN IP
// (e.g. they bookmarked the AP URL after first setup), bounce them to the
// LAN address so the rest of the page works. `#force` in the URL hash
// forces initial mode for testing.
function SetupGate() {
  const force = typeof window !== "undefined" && window.location.hash === "#force";
  const [provisioned, setProvisioned] = useState<boolean | null>(force ? false : null);
  useEffect(() => {
    if (force) return;
    let cancelled = false;
    (async () => {
      const ok = await checkInternet().catch(() => false);
      if (cancelled) return;
      if (!ok) { setProvisioned(false); return; }
      // Online: see if we should redirect to the actual LAN IP first.
      try {
        const s = await getSetupStatus();
        if (cancelled) return;
        const here = window.location.hostname;
        if (s.lan_ip && s.lan_ip !== here) {
          window.location.replace(`http://${s.lan_ip}${window.location.pathname}${window.location.search}`);
          return;
        }
      } catch { /* keep showing continue mode if status endpoint fails */ }
      if (!cancelled) setProvisioned(true);
    })();
    return () => { cancelled = true; };
  }, [force]);
  if (provisioned === null) return null;
  return <Setup mode={provisioned ? "continue" : "initial"} />;
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<SetupGate />} />
        <Route path="/monitor" element={<Monitor />} />
        <Route path="/setup" element={<SetupGate />} />
        <Route path="/edit" element={<EditConfig />} />
        <Route path="/gw-config" element={<GwConfig />} />
        <Route path="/dashboard" element={<Navigate to="/monitor" replace />} />
      </Routes>
      <Toaster richColors position="top-center" />
    </BrowserRouter>
  );
}

export default App;
