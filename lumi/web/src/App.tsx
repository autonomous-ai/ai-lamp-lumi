import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import Setup from "@/pages/Setup";
import Monitor from "@/pages/monitor";
import EditConfig from "@/pages/EditConfig";
import GwConfig from "@/pages/GwConfig";

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Monitor />} />
        <Route path="/setup" element={<Setup />} />
        <Route path="/edit" element={<EditConfig />} />
        <Route path="/gw-config" element={<GwConfig />} />
        <Route path="/dashboard" element={<Navigate to="/" replace />} />
      </Routes>
      <Toaster richColors position="top-center" />
    </BrowserRouter>
  );
}

export default App;
