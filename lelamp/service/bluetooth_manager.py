"""Bluetooth manager — bluetoothctl wrapper for BT audio (headset) routing.

Persists the user's active headset MAC across restarts so reboot keeps
the private-mode preference.
"""

import json
import logging
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("lelamp.bluetooth")

_STATE_DIR = Path(os.environ.get("LELAMP_BT_STATE_DIR", "/var/lib/lelamp"))
_STATE_FILE = _STATE_DIR / "bluetooth.json"

SCAN_TIMEOUT_S = 30
_DEVICE_LINE_RE = re.compile(r"^Device ([0-9A-F:]{17})\s+(.*)$", re.I)


def _run(args: list[str], timeout: float = 10.0) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def _parse_devices(out: str) -> list[dict]:
    devices: list[dict] = []
    for line in out.splitlines():
        m = _DEVICE_LINE_RE.match(line.strip())
        if m:
            devices.append({"mac": m.group(1).upper(), "name": m.group(2).strip()})
    return devices


def _device_info(mac: str) -> dict:
    info = {
        "mac": mac.upper(),
        "name": None,
        "paired": False,
        "connected": False,
        "trusted": False,
    }
    try:
        r = _run(["bluetoothctl", "info", mac], timeout=5)
        if r.returncode != 0:
            return info
        for line in r.stdout.splitlines():
            line = line.strip()
            if line.startswith("Name:"):
                info["name"] = line.split(":", 1)[1].strip()
            elif line.startswith("Paired:"):
                info["paired"] = "yes" in line.lower()
            elif line.startswith("Connected:"):
                info["connected"] = "yes" in line.lower()
            elif line.startswith("Trusted:"):
                info["trusted"] = "yes" in line.lower()
    except Exception as e:
        logger.warning("bluetoothctl info %s failed: %s", mac, e)
    return info


class BluetoothManager:
    def __init__(self):
        self._scan_thread: Optional[threading.Thread] = None
        self._scan_lock = threading.Lock()
        self._state = self._load_state()

    # --- State persistence ---

    def _load_state(self) -> dict:
        try:
            if _STATE_FILE.exists():
                return json.loads(_STATE_FILE.read_text())
        except Exception as e:
            logger.warning("Loading BT state failed: %s", e)
        return {"active_mac": None}

    def _save_state(self) -> None:
        try:
            _STATE_DIR.mkdir(parents=True, exist_ok=True)
            _STATE_FILE.write_text(json.dumps(self._state, indent=2))
        except Exception as e:
            logger.warning("Saving BT state failed: %s", e)

    @property
    def active_mac(self) -> Optional[str]:
        return self._state.get("active_mac")

    def set_active_mac(self, mac: Optional[str]) -> None:
        self._state["active_mac"] = mac.upper() if mac else None
        self._save_state()

    # --- Availability ---

    def available(self) -> bool:
        try:
            r = _run(["bluetoothctl", "--version"], timeout=2)
            return r.returncode == 0
        except Exception:
            return False

    # --- Scan ---

    def scan_start(self, timeout_s: int = SCAN_TIMEOUT_S) -> None:
        """Kick off a time-boxed scan in the background. Idempotent."""
        with self._scan_lock:
            if self._scan_thread and self._scan_thread.is_alive():
                return

            def _scan():
                try:
                    _run(
                        ["bluetoothctl", "--timeout", str(timeout_s), "scan", "on"],
                        timeout=timeout_s + 5,
                    )
                except Exception as e:
                    logger.warning("BT scan failed: %s", e)

            t = threading.Thread(target=_scan, daemon=True, name="bt-scan")
            t.start()
            self._scan_thread = t

    def scan_active(self) -> bool:
        return self._scan_thread is not None and self._scan_thread.is_alive()

    def discovered_devices(self) -> list[dict]:
        """All devices BlueZ has seen — caller filters to unpaired for UI."""
        try:
            r = _run(["bluetoothctl", "devices"], timeout=5)
            return _parse_devices(r.stdout) if r.returncode == 0 else []
        except Exception as e:
            logger.warning("discovered_devices failed: %s", e)
            return []

    # --- Paired ---

    def paired_devices(self) -> list[dict]:
        try:
            r = _run(["bluetoothctl", "devices", "Paired"], timeout=5)
            if r.returncode != 0:
                r = _run(["bluetoothctl", "paired-devices"], timeout=5)
            base = _parse_devices(r.stdout) if r.returncode == 0 else []
        except Exception:
            base = []
        out = []
        for d in base:
            info = _device_info(d["mac"])
            if info["name"] is None:
                info["name"] = d["name"]
            out.append(info)
        return out

    def info(self, mac: str) -> dict:
        return _device_info(mac)

    # --- Pair / connect / forget ---

    def pair(self, mac: str) -> bool:
        mac = mac.upper()
        try:
            _run(["bluetoothctl", "pair", mac], timeout=20)
        except Exception as e:
            logger.warning("pair %s failed: %s", mac, e)
        try:
            _run(["bluetoothctl", "trust", mac], timeout=5)
        except Exception:
            pass
        try:
            _run(["bluetoothctl", "connect", mac], timeout=15)
        except Exception as e:
            logger.warning("connect after pair %s failed: %s", mac, e)
        return _device_info(mac)["paired"]

    def connect(self, mac: str) -> bool:
        try:
            _run(["bluetoothctl", "connect", mac.upper()], timeout=15)
        except Exception as e:
            logger.warning("connect %s failed: %s", mac, e)
        # PulseAudio takes a beat to expose the new sink after BlueZ reports connected.
        for _ in range(10):
            if _device_info(mac)["connected"]:
                time.sleep(0.5)
                return True
            time.sleep(0.3)
        return False

    def disconnect(self, mac: str) -> bool:
        try:
            _run(["bluetoothctl", "disconnect", mac.upper()], timeout=10)
        except Exception as e:
            logger.warning("disconnect %s failed: %s", mac, e)
        return not _device_info(mac)["connected"]

    def forget(self, mac: str) -> bool:
        mac = mac.upper()
        try:
            _run(["bluetoothctl", "disconnect", mac], timeout=10)
        except Exception:
            pass
        try:
            r = _run(["bluetoothctl", "remove", mac], timeout=10)
            ok = r.returncode == 0
        except Exception as e:
            logger.warning("remove %s failed: %s", mac, e)
            ok = False
        if self.active_mac == mac:
            self.set_active_mac(None)
        return ok

    # --- sounddevice index resolution ---

    def find_sd_indices(self, mac: str, sd_module) -> tuple[Optional[int], Optional[int]]:
        """Find PortAudio output/input indices matching this MAC.

        Forces PortAudio re-enumeration first — sounddevice caches the device
        list at import time and a freshly-paired BT sink won't appear otherwise.
        """
        try:
            sd_module._terminate()
            sd_module._initialize()
        except Exception:
            logger.exception("PortAudio reinit failed during BT lookup")

        needles = (mac.upper().replace(":", "_"), mac.upper().replace(":", "-"))
        out_idx = in_idx = None
        for i, dev in enumerate(sd_module.query_devices()):
            up = dev.get("name", "").upper()
            if any(n in up for n in needles):
                if dev.get("max_output_channels", 0) > 0 and out_idx is None:
                    out_idx = i
                if dev.get("max_input_channels", 0) > 0 and in_idx is None:
                    in_idx = i
        return out_idx, in_idx
