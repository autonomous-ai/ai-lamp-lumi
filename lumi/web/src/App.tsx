import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import Setup from "@/pages/Setup";
import Monitor from "@/pages/monitor";
import EditConfig from "@/pages/EditConfig";

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Setup />} />
        <Route path="/monitor" element={<Monitor />} />
        <Route path="/edit" element={<EditConfig />} />
        <Route path="/dashboard" element={<Navigate to="/" replace />} />
      </Routes>
      <Toaster richColors position="top-center" />
    </BrowserRouter>
  );
}

export default App;
