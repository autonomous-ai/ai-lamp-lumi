"""Bluetooth headset routes — pair / connect / route TTS+STT to a BT
headset so the user can use the lamp privately without disturbing others.

Endpoints live under /bluetooth/* (exposed to the web UI via /hw/bluetooth/*
through the existing Lumi reverse proxy).
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import lelamp.app_state as state
from lelamp.service.audio_route import (
    current_label,
    route_to_bluetooth,
    route_to_lamp,
)
from lelamp.service.bluetooth_manager import BluetoothManager

logger = logging.getLogger("lelamp.bluetooth.routes")

router = APIRouter(prefix="/bluetooth", tags=["Bluetooth"])

try:
    import sounddevice as sd
except ImportError:
    sd = None  # type: ignore

_manager: Optional[BluetoothManager] = None


def _mgr() -> BluetoothManager:
    global _manager
    if _manager is None:
        _manager = BluetoothManager()
    return _manager


class MacRequest(BaseModel):
    mac: str


class ActiveRequest(BaseModel):
    mac: Optional[str] = None  # None / "" → switch back to lamp


@router.get("/available")
def bt_available():
    """Tell the UI whether bluetoothctl works on this host."""
    return {"available": _mgr().available()}


@router.post("/scan/start")
def bt_scan_start():
    mgr = _mgr()
    if not mgr.available():
        raise HTTPException(503, "bluetoothctl not available")
    mgr.scan_start()
    return {"status": "ok"}


@router.get("/scan/results")
def bt_scan_results():
    mgr = _mgr()
    paired_macs = {d["mac"] for d in mgr.paired_devices()}
    discovered = [d for d in mgr.discovered_devices() if d["mac"] not in paired_macs]
    return {"scanning": mgr.scan_active(), "devices": discovered}


@router.get("/devices")
def bt_devices():
    mgr = _mgr()
    paired = mgr.paired_devices()
    active = mgr.active_mac
    for d in paired:
        d["active"] = d["mac"] == active
    return {"active_mac": active, "label": current_label(), "devices": paired}


@router.post("/pair")
def bt_pair(req: MacRequest):
    mgr = _mgr()
    if not mgr.available():
        raise HTTPException(503, "bluetoothctl not available")
    if not mgr.pair(req.mac):
        raise HTTPException(
            500,
            "Pairing failed — make sure the headset is in pairing mode and try again",
        )
    return {"status": "ok"}


@router.post("/forget")
def bt_forget(req: MacRequest):
    mgr = _mgr()
    target = req.mac.upper()
    if mgr.active_mac and mgr.active_mac == target:
        # Bring TTS/STT back to the lamp before the device disappears,
        # otherwise the persistent OutputStream is left pointed at a gone sink.
        route_to_lamp()
    if not mgr.forget(target):
        raise HTTPException(500, "Forget failed")
    return {"status": "ok"}


@router.get("/active")
def bt_active_get():
    mgr = _mgr()
    return {"active_mac": mgr.active_mac, "label": current_label()}


@router.post("/active")
def bt_active_set(req: ActiveRequest):
    """Toggle voice routing.

    mac = null / "" → route back to the lamp's built-in speaker + mic.
    mac = MAC       → ensure connected, find PortAudio indices, route TTS+STT
                      to the BT device. STT mic falls back to lamp mic if the
                      device has no input (BT speaker case).
    """
    mgr = _mgr()
    target = (req.mac or "").strip().upper() or None

    if target is None:
        route_to_lamp()
        mgr.set_active_mac(None)
        return {"status": "ok", "active_mac": None, "label": current_label()}

    if sd is None:
        raise HTTPException(503, "sounddevice not available on host")

    if not mgr.info(target)["connected"] and not mgr.connect(target):
        raise HTTPException(503, f"Could not connect to {target}")

    out_idx, in_idx = mgr.find_sd_indices(target, sd)
    if out_idx is None:
        raise HTTPException(
            503,
            f"PulseAudio/bluez did not expose {target} to PortAudio — "
            f"check pipewire/pulseaudio service",
        )

    route_to_bluetooth(out_idx, in_idx, target)
    mgr.set_active_mac(target)
    return {
        "status": "ok",
        "active_mac": target,
        "label": current_label(),
        "output_index": out_idx,
        "input_index": in_idx,
    }


@router.get("/status")
def bt_status():
    """Snapshot for the monitor card — what's active, what's around."""
    mgr = _mgr()
    return {
        "available": mgr.available(),
        "active_mac": mgr.active_mac,
        "label": current_label(),
        "scanning": mgr.scan_active(),
        "paired": mgr.paired_devices(),
    }
