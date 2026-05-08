import { useEffect, useState } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import Setup from "@/pages/Setup";
import Monitor from "@/pages/monitor";
import EditConfig from "@/pages/EditConfig";
import GwConfig from "@/pages/GwConfig";
import { checkInternet } from "@/lib/api";

// Setup gate: provisioned (online) → continue mode (Voice/Face enroll, TTS
// preview), else initial mode (offline form for AP setup). `#force` in the
// URL hash (e.g. /setup#force) forces initial mode for testing.
function SetupGate() {
  const force = typeof window !== "undefined" && window.location.hash === "#force";
  const [provisioned, setProvisioned] = useState<boolean | null>(force ? false : null);
  useEffect(() => {
    if (force) return;
    checkInternet()
      .then((ok) => setProvisioned(!!ok))
      .catch(() => setProvisioned(false));
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
