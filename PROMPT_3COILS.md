# PROMPT — CamBox Pro: add 3 named coil controls (dashboard + firmware)

Copy everything below into a new chat/agent to continue the work.

---

## Project
CamBox Pro — an ESP32 diesel injector / pump test system. An ESP32 firmware
(Arduino, C++) talks over USB serial @115200 to a Python PyQt dashboard
(`diesel_dashboard_FINAL.py`, "INJECTOR PRO"). The dashboard shows live RPM,
pressure, angle and injector pulses, and sends control commands.

## Files
- Firmware sketch: `ESP32_Injector_Final/`
  - `ESP32_Injector_Final.ino`, `injector_driver.h`, `injector_driver.cpp`
  - `*.v4.bak` are backups of the previous version.
- Dashboard: `diesel_dashboard_FINAL.py` (PyQt, ~3600 lines).
- Board: `esp32:esp32:esp32`, ESP32 core 3.3.8, port **COM3**.
- Build (bundled arduino-cli): compile with
  `arduino-cli compile --fqbn esp32:esp32:esp32 ESP32_Injector_Final`
  and flash with `--upload -p COM3`. (Current build passes, 24% flash / 7% RAM.)

## Hardware pins (VERIFIED from the official ESP32-30pin board diagram)
```
GPIO18  X5: Coil1 PWM   (currently the ONLY driven coil — SCV/PCV valve)
GPIO23  X3: Coil2 PWM   (WIRED, not yet driven by firmware)
GPIO4   X2: Coil3 PWM   (WIRED, not yet driven by firmware)
GPIO5   X4: Proximity sensor (cam trigger, 1 pulse/rev, RISING)
GPIO14  X1: Pressure sensor (ADC, LM358 conditioned)
GPIO19  X6: Relay (12V/28V switching — Peak supply)
GPIO15  Buzzer
GPIO21  LCD SDA        GPIO22  LCD SCL     (LCD unused in current firmware)
GPIO26  Debug/scope pin (= keypad8_pin; free because keypad removed)
Keypad (removed): GPIO36/39/34/35/32/33/25/26
UART0: GPIO1 TX / GPIO3 RX   UART2: GPIO17 TX / GPIO16 RX
```

## Current firmware state
- Single coil only, on **GPIO18**. LCD and keypad removed; serial-only control.
- Two modes: **CAM** (proximity-synced Peak & Hold pulse, angle→delay recomputed
  every rev via esp_timer one-shot; GPIO26 HIGH at ISR, LOW at fire) and **PUMP**
  (PID pressure loop drives GPIO18 PWM via LEDC).
- Peak & Hold hold-chop fixed at **10 kHz** (do not raise — 25 kHz overheats coils).
- Telemetry every 10 ms: `P:<bar>,A:<deg>,R:<rpm>,I:<val>,C:<revcount>`.
- Serial commands: `start`, `stop`, `w<us>` (100–5000), `f<Hz>` (1–200),
  `a<deg>` (0–359), `mode`, `SET_PH <peak_us> <hold_on_us> <hold_off_us>`,
  `TARGET_P <bar>`, `PID <Kp> <Ki> <Kd>`, `PSCALE <v0> <vmax> <pmax>`,
  `PCV_FREQ <hz>`, `STATUS`.
- Flashed to the board; dashboard connects on COM3 and shows 100 packets/sec.

---

## NEW FEATURE TO BUILD
Add control for **three coils** in the dashboard, each as its own box/section:

1. **Coil 1**, **Coil 2**, **Coil 3** — three separate boxes in the GUI.
2. Each box has a **button** (its action — see below).
3. Each coil has an **editable name** the user types in the program (rename from
   the dashboard). Names persist between sessions (save to a small JSON/config).

### Design decisions (defaults chosen — change if the user says otherwise)
- **Scope:** Firmware + dashboard. Re-enable Coil2 (GPIO23) and Coil3 (GPIO4)
  in the firmware so the buttons drive real hardware, alongside Coil1 (GPIO18).
  Keep the single-coil PUMP/PID path on Coil1.
- **Button behavior:** ON/OFF toggle per coil (enable/disable that channel).
  When a coil is enabled and the system is running, that coil fires with the
  Peak & Hold profile in CAM/free-run, at the shared pulse width.
  (Alternatives the user may prefer: momentary "fire one pulse", or radio-style
  "only one active coil at a time".)
- **Naming:** free-text label per coil, saved in a config file (e.g.
  `coil_names.json`) and reloaded on start; names are display-only (don't affect
  serial protocol).

### Firmware changes needed
- Re-add Coil2 (GPIO23) and Coil3 (GPIO4) as Peak & Hold outputs (multi-channel
  version already exists in `../ESP32_CamBox_V5/` for reference).
- Add serial commands to enable/disable/fire each coil, e.g.
  `COIL <n> ON|OFF` (n = 1..3) and/or `FIRE <n>`. Preserve all existing commands.
- Keep 10 kHz chop; keep GPIO18's PUMP/PID role in PUMP mode.
- Watch the blocking budget: firing multiple Peak & Hold pulses back-to-back
  blocks with interrupts masked (~pulse-width each) — fine at bench RPM, note it.

### Dashboard changes needed
- Add a "Coils" panel with 3 boxes: each shows the editable name + an ON/OFF
  (or Fire) button + a status indicator.
- Wire the buttons to the new serial commands.
- Add rename (double-click label or an edit field) and persist to config.
- Match the existing dark theme / layout style.

### Constraints
- Do NOT break existing serial commands, telemetry format, CAM/PUMP modes, or the
  10 kHz Peak & Hold tuning.
- Confirm board wiring before flashing; firmware idles on boot (no coil fires
  until `start` / a coil is enabled).
- Before editing, back up `diesel_dashboard_FINAL.py` and the firmware files.
```
```
