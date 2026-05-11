import { C, PasswordField, SectionCard, SkeletonBlock } from "./shared";
import type { NetworkItem } from "@/types";

export function WifiSection({
  active, ssid, setSsid, password, setPassword, loadingList, uniqueNetworks,
}: {
  active: boolean;
  ssid: string;
  setSsid: (v: string) => void;
  password: string;
  setPassword: (v: string) => void;
  loadingList: boolean;
  uniqueNetworks: NetworkItem[];
}) {
  return (
    <SectionCard id="wifi" title="Wi-Fi" active={active}>
      <div style={{ marginBottom: 12 }}>
        <label htmlFor="ssid" style={{ display: "block", fontSize: 11, color: C.textDim, marginBottom: 5 }}>
          Wi-Fi network
        </label>
        {loadingList ? (
          <SkeletonBlock />
        ) : uniqueNetworks.length > 0 ? (
          <select
            id="ssid"
            value={ssid}
            onChange={(e) => setSsid(e.target.value)}
            style={{
              width: "100%", boxSizing: "border-box",
              background: C.surface, border: `1px solid ${C.border}`,
              borderRadius: 7, padding: "8px 11px",
              fontSize: 12.5, color: C.text, outline: "none", cursor: "pointer",
            }}
          >
            <option value="">Select network</option>
            {uniqueNetworks.map((n) => (
              <option key={n.bssid} value={n.ssid}>{n.ssid}</option>
            ))}
          </select>
        ) : (
          <input
            id="ssid" type="text" value={ssid}
            onChange={(e) => setSsid(e.target.value)}
            placeholder="Enter Wi-Fi name" autoComplete="off"
            style={{
              width: "100%", boxSizing: "border-box",
              background: C.surface, border: `1px solid ${C.border}`,
              borderRadius: 7, padding: "8px 11px",
              fontSize: 12.5, color: C.text, outline: "none",
            }}
          />
        )}
      </div>
      <PasswordField label="Password" id="password" value={password} onChange={setPassword} placeholder="Wi-Fi password" />
    </SectionCard>
  );
}
