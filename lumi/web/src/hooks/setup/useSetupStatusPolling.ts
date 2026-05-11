import { useEffect } from "react";
import type { Dispatch, SetStateAction } from "react";
import { getSetupStatus } from "@/lib/api";

export type SetupPhase = "connecting" | "connected" | "failed";

// Two paired pollers driving the post-submit "Setting up…" UI:
//   (1) phase poll — runs while setupWorking, hits the AP IP for phase/lan_ip
//   (2) LAN probe — once we know the LAN IP, probe it from the browser; when
//       reachable (user rejoined home Wi-Fi) navigate there.
export function useSetupStatusPolling({
  setupWorking,
  setupPhase,
  setupLanIP,
  setSetupPhase,
  setSetupLanIP,
  setSetupErrorMsg,
}: {
  setupWorking: boolean;
  setupPhase: SetupPhase;
  setupLanIP: string;
  setSetupPhase: Dispatch<SetStateAction<SetupPhase>>;
  setSetupLanIP: Dispatch<SetStateAction<string>>;
  setSetupErrorMsg: Dispatch<SetStateAction<string>>;
}) {
  // Phase poll: runs against the AP IP, so it works while the user is still
  // on the AP SSID. Once the AP shuts down the polls will fail and we keep
  // the last value.
  useEffect(() => {
    if (!setupWorking) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const s = await getSetupStatus();
        if (cancelled) return;
        if (s.phase === "connected") {
          setSetupPhase("connected");
          if (s.lan_ip) setSetupLanIP(s.lan_ip);
        } else if (s.phase === "failed") {
          setSetupPhase("failed");
          setSetupErrorMsg(s.error || "Wi-Fi setup failed.");
        }
      } catch {
        /* AP likely shutting down — keep last known phase */
      }
    };
    tick();
    const id = setInterval(tick, 2000);
    return () => { cancelled = true; clearInterval(id); };
  }, [setupWorking, setSetupPhase, setSetupLanIP, setSetupErrorMsg]);

  // Best-effort auto-redirect: once we know the LAN IP, probe it from the
  // browser. When reachable (= user has rejoined home Wi-Fi) navigate there.
  useEffect(() => {
    if (setupPhase !== "connected" || !setupLanIP) return;
    let cancelled = false;
    const newURL = `http://${setupLanIP}/`;
    const probe = async () => {
      try {
        await fetch(`${newURL}api/health`, { mode: "no-cors", cache: "no-store" });
        if (!cancelled) window.location.href = newURL;
      } catch {
        /* not reachable yet — user still on AP SSID */
      }
    };
    probe();
    const id = setInterval(probe, 3000);
    return () => { cancelled = true; clearInterval(id); };
  }, [setupPhase, setupLanIP]);
}
