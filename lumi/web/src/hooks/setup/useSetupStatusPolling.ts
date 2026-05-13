import { useEffect } from "react";
import type { Dispatch, SetStateAction } from "react";
import { getSetupStatus } from "@/lib/api";

export type SetupPhase = "connecting" | "connected" | "failed";

// Three paired pollers driving the post-submit "Setting up…" UI:
//   (1) phase poll — runs while setupWorking, hits the AP IP for phase/lan_ip
//   (2) LAN probe — once we know the LAN IP, probe it from the browser; when
//       reachable (user rejoined home Wi-Fi) navigate there.
//   (3) mDNS probe — primary auto-redirect path. The LAN-IP channel almost
//       always fails in practice (AP shuts down before its lan_ip propagates
//       to the FE poll), so we also probe `lumi-XXXX.local` directly. When
//       the user's computer rejoins home Wi-Fi, mDNS resolves and we redirect.
export function useSetupStatusPolling({
  setupWorking,
  setupPhase,
  setupLanIP,
  lumiMdnsHost,
  setSetupPhase,
  setSetupLanIP,
  setSetupErrorMsg,
}: {
  setupWorking: boolean;
  setupPhase: SetupPhase;
  setupLanIP: string;
  lumiMdnsHost: string;
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

  // mDNS probe — the primary auto-redirect channel since the LAN-IP one
  // rarely fires in real AP→STA transitions. Carries the current pathname +
  // search across, so any URL params from Lumi (llm_api_key, device_id, …)
  // remain in scope on the new host even though the lamp already persisted
  // them via the form submit. Manual button in Setup.tsx renders unconditionally
  // as the safety net if mDNS is blocked on the network.
  useEffect(() => {
    if (setupPhase !== "connected" || !lumiMdnsHost) return;
    let cancelled = false;
    const base = `http://${lumiMdnsHost}.local`;
    const newURL = `${base}${window.location.pathname}${window.location.search}`;
    const probe = async () => {
      try {
        await fetch(`${base}/api/health`, { mode: "no-cors", cache: "no-store" });
        if (!cancelled) window.location.href = newURL;
      } catch {
        /* mDNS not resolvable yet — user still on AP, or network blocks mDNS */
      }
    };
    probe();
    const id = setInterval(probe, 3000);
    return () => { cancelled = true; clearInterval(id); };
  }, [setupPhase, lumiMdnsHost]);

  // Pre-submit canonical URL upgrade: when user lands on the AP IP
  // (192.168.100.1) we silently bounce to `http://lumi-XXXX.local/…` once we
  // know the hostname AND the .local name is reachable from the current
  // network. On the AP itself avahi runs on the lamp so the same multicast
  // reaches both peers — resolution is almost instant on Windows/macOS/iOS.
  // Benefit: the URL stays the same through the AP→STA wifi switch, so when
  // the user rejoins home Wi-Fi the browser reloads the same .local URL and
  // mDNS transparently maps it to the lamp's new LAN IP — no manual click.
  // Android Chrome (no native mDNS) just sees probes fail and stays on the
  // AP IP — current behavior, no regression.
  useEffect(() => {
    if (!lumiMdnsHost) return;
    if (typeof window === "undefined") return;
    if (window.location.hostname !== "192.168.100.1") return;
    let cancelled = false;
    const base = `http://${lumiMdnsHost}.local`;
    const target = `${base}${window.location.pathname}${window.location.search}`;
    const probe = async () => {
      try {
        await fetch(`${base}/api/health`, { mode: "no-cors", cache: "no-store" });
        if (!cancelled) window.location.replace(target);
      } catch {
        /* mDNS not resolvable from this client (Android Chrome, blocked LAN) */
      }
    };
    probe();
    const id = setInterval(probe, 5000);
    return () => { cancelled = true; clearInterval(id); };
  }, [lumiMdnsHost]);
}
