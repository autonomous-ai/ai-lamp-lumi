# Wiring

Pin-by-pin map for everything connected to the SBC. Two columns: **Raspberry Pi 5** and **OrangePi 4 Pro (Allwinner A733 / sun60iw2)**. Numbers come straight from the code so this stays verifiable — `lelamp/service/...` references are noted in each row.

Keep this in sync when wiring changes. Mismatch between this file and the code is a bug.

---

## Compute board pinouts

- Raspberry Pi 5 — https://pinout.xyz/
- OrangePi 4 Pro — see vendor wiki; 40-pin header, Allwinner A733 GPIO scheme: `PA=0..31, PB=32..63, PC=64..95, PD=96..127, PE=128..159, PL=352..383`

---

## Button (single)

Single momentary tactile, normally-open. Single-click = stop / unmute. Triple-click = reboot. Long press 3 s = shutdown. 200 ms debounce in software.

| | Raspberry Pi 5 | OrangePi 4 Pro |
|---|---|---|
| Header pin | 11 | 11 |
| Signal | BCM 17 | PL9 |
| Char device | `/dev/gpiochip0` line 17 | `/dev/gpiochip1` line 9 |
| GND | pin 9 | pin 9 |
| Code | `lelamp/service/gpio_button.py:22-24` | `lelamp/service/gpio_button.py:30-32` |

---

## WS2812 RGB LED ring (64 pixels)

5 V data + power + GND. Common ground with SBC. Brightness capped in software — see `power.md` for current budget rationale.

| | Raspberry Pi 5 | OrangePi 4 Pro |
|---|---|---|
| Driver | `spidev` raw WS2812 over SPI0.0 | `spidev` raw WS2812 over SPI3.0 |
| Data pin | GPIO 10 (SPI0 MOSI) — header pin 19 | SPI3 MOSI — header pin 19 |
| Clock | n/a (MOSI-only) | n/a (MOSI-only) |
| Bus speed | 6.4 MHz | 6.4 MHz |
| 5 V | external 5 V rail (not header) | external 5 V rail (not header) |
| GND | header pin 6 (common with rail) | header pin 6 (common with rail) |
| Code | `lelamp/service/rgb/rgb_service.py:102-111` | `lelamp/service/rgb/rgb_service.py:176-180` |

> **Pi 4 fallback**: PWM driver on GPIO 12 (header pin 32). See `lelamp/service/rgb/rgb_service.py:182-186`.

> **Power note**: 64 px × 60 mA white worst-case = 3.84 A. Software caps brightness; do not test at full white without a 5 A-capable rail.

---

## Servo bus (5× STS3215)

Feetech STS3215 servos on a TTL daisy chain, driven by a USB-to-TTL servo control board. Same wiring on both SBCs — it's just USB.

| | Raspberry Pi 5 | OrangePi 4 Pro |
|---|---|---|
| Connection | USB-A → USB control board | USB-A → USB control board |
| Enumeration | `/dev/ttyACM0` | `/dev/ttyACM0` |
| Servo count | 5 (chained) | 5 |
| Servo power | external 5 V (NOT from USB) | external 5 V (NOT from USB) |
| Protocol | Feetech SCS via `scservo_sdk` | same |
| `P_Coefficient` | 16 (do **not** override — see `lelamp/UPSTREAM.md:37`) | 16 |
| Code | `lelamp/config.py:13`, `lelamp/routes/servo.py:383` | same |

> Servo and camera **share serialization** in software because of bus contention (`lelamp/UPSTREAM.md:26-27`). Mechanically they're independent — this is purely a runtime concern.

---

## Speaker amplifier (PAM8610 v2) + 2× 3 W speakers

Stereo class-D amp driven by a **USB audio board (DAC)** plugged into the SBC. The onboard codec → PAM8610 path was hissing / picking up static, so we moved the audio source off the SBC's onboard codec entirely. The onboard codec stays in use for **mic capture** only.

Signal chain:

```
SBC → USB → USB audio board (DAC) → 3.5 mm line-out → PAM8610 L/R in → speakers
```

| | Raspberry Pi 5 | OrangePi 4 Pro |
|---|---|---|
| Audio source | USB audio board (line-out) | USB audio board (line-out) |
| Connection | USB-A | USB-A |
| ALSA alias | `plug:lamp_speaker` (mapped to USB DAC card) | `plug:lamp_speaker` (mapped to USB DAC card) |
| DAC out → amp | 3.5 mm TRS → PAM8610 L/R inputs (twisted pair, short run) | same |
| Speaker A | PAM8610 L+ / L− → speaker A | same |
| Speaker B | PAM8610 R+ / R− → speaker B | same |
| Amp Vcc | 12 V (do not feed 5 V — under-driven) | 12 V |
| Amp GND | star-ground at buck output | same |

> The onboard codec (WM8960 on Pi via Seeed HAT, ES8389 on OPi) is still wired in for mic capture (Mic 2 / sensing). Its line-out is no longer connected to the amp.

> Keep the DAC → amp lead short and twisted. Run it away from the 12 V power harness — the prior hiss was partly induced from the SBC's switching supply.

---

## Microphones

Two mics: a USB mic for voice capture, an onboard mic for ambient sensing.

| Role | Device | ALSA alias | Code |
|---|---|---|---|
| Voice (Mic 1) | USB mic (`lamp_usb_mic` card) | `plug:lamp_micro2` | `/opt/lelamp/.env` (`LELAMP_AUDIO_INPUT_ALSA`) |
| Sensing (Mic 2) | onboard codec capture | `plug:lamp_micro1` | `/opt/lelamp/.env` (`LELAMP_AUDIO_SENSING_DEVICE`) |

> ALSA aliases live in `/etc/asound.conf` on each device; not the same string across all units.

> On Raspberry Pi the wm8960 capture gain has a watchdog that clamps it to 160 — see `project_lumi_pcm_watchdog.md`.

---

## Camera (USB IMX307)

USB UVC. Plug into any free USB port (prefer USB 3 if available for headroom; 1080p30 fits in USB 2 fine).

| | Raspberry Pi 5 | OrangePi 4 Pro |
|---|---|---|
| Connection | USB-A | USB-A |
| Enumeration | `/dev/video0` (first UVC device) | `/dev/video0` |
| Pixel format | MJPG @ 1080p / 30 fps | MJPG @ 1080p / 30 fps |
| Notes | Camera + servo serialize in software | same |
| Code | `lelamp/service/camera/`, `lelamp/server.py` | same |

---

## TTP223 capacitive touch (optional, OPi only)

Four touch pads for left/right swipe gesture. Factory default mode (AB pads unsoldered): momentary, active-HIGH push-pull output.

| Pad | OPi header pin | GPIO line | Notes |
|---|---|---|---|
| S1 (leftmost) | 29 | gpiochip0 line 96 (PD0) | |
| S2 | 31 | gpiochip0 line 97 (PD1) | |
| S3 | 33 | gpiochip0 line 98 (PD2) | |
| S4 (rightmost) | 35 | gpiochip0 line 99 (PD3) | |
| VCC (all 4) | 17 (3.3 V) | — | **Must be 3.3 V, NOT 5 V** — OPi GPIO is 3.3 V tolerant only |
| GND (all 4) | 25 or 39 | — | |

Default mode (AB pads unsoldered) gives momentary, active-HIGH output — the SoC reads HIGH while a finger is on the pad, LOW otherwise.

---

## Power

See [`power.md`](power.md) for the full 12 V → 5 V tree, current budget, and grounding scheme.
