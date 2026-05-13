# Components

Running list of parts that go into one lamp. Models / links filled in as we lock things down.

| Part | Model | Link / Notes |
|---|---|---|
| Mic 1 (voice) | USB | |
| Mic 2 (sensing) | onboard OrangePi | |
| Camera | USB | https://www.alibaba.com/product-detail/Newlink-1080P-30fps-IMX307-Starvis-Day_1600739999329.html |
| Speaker 3W x2 | | |
| Speaker amplifier | PAM8610 v2 | TBD |
| USB audio board (DAC) | TBD | feeds line-in of PAM8610; onboard codec → PAM path was hissing / static |
| Pi5 | 4GB RAM | |
| Servo x5 | STS3215 ST-3215-C018 | drives via Waveshare Bus Servo Adapter (USB) |
| Waveshare Bus Servo Adapter | USB-to-TTL servo bus | shows up as `/dev/ttyACM0`; powers servo bus from external 5 V |
| RGB LED ring | | |
| Button | | |
| Wire, screw, header, USB-C female | | |
| 3D printed body | | |
| Power adaptor | 12V 5A | |
| DC-DC step-down (12V → 5V for OrangePi) | MP2482 | |
| Fan 5V | Nidec | |
| Touch sensor x4 | TTP223 | swipe gesture pads (left↔right); see `wiring.md` |
| Resistor pair (Option B only) | 47 Ω + 91 Ω | divider for 5 V → 3.3 V at the head if reusing the existing 5 V rail; not needed if running a 3.3 V wire from the OPi |
