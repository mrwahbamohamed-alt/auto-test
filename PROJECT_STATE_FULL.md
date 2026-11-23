# DIT-3000 / INJECTOR PRO — Full Technical State Report

Written from the actual source. Every claim below cites a real file, function, or variable. Anything absent from the code is marked **NOT IMPLEMENTED**.

---

## 1. File & Project Structure

### 1.1 File tree (only the files that participate)

```
Diesel Dashboard/
├── ESP32_Injector_Final/                  ← Arduino sketch folder
│   ├── ESP32_Injector_Final.ino           (1314 LOC — main firmware)
│   ├── injector_driver.h                  ( 108 LOC — pin map + P&H + MV #defines)
│   ├── injector_driver.cpp                ( 137 LOC — Peak & Hold pin-bang driver)
│   └── ESP32_Injector_Final.ino.*.bak     (30+ chronological snapshots)
│
├── diesel_dashboard_FINAL.py              (4934 LOC — the whole PyQt6 dashboard)
├── presets_common_rail.json               (calibration presets)
├── injector_db.json                       (SEPARATE injector-profile DB, ~635 lines)
├── PROJECT_STATE_REPORT.md                (previous short report)
├── PROJECT_STATE_FULL.md                  (this file)
│
├── _esp32_flash.bat / _esp32_build.bat    (helper batch: arduino-cli wrappers)
├── _esp32_flash_log.txt / _esp32_build_log.txt
├── _serial_capture.ps1 / _serial_test.bat / _serial_log.txt
├── auto_pro_test.py                       (1843 LOC — legacy stand-alone tester, unrelated)
├── pressure_simulator.py                  (175 LOC — legacy standalone sim, unrelated)
├── create_icon.py, make_icon.py           (icon utilities)
├── build.ps1, build_auto_test.py          (PyInstaller helpers)
├── campro.ico, injector.ico               (window icons)
└── Injector_Report_*.pdf                  (sample generated reports)
```

`auto_pro_test.py` and `pressure_simulator.py` are legacy standalone Python programs — the running dashboard is **only** `diesel_dashboard_FINAL.py`.

### 1.2 Responsibilities

| File | Responsibility |
|---|---|
| `ESP32_Injector_Final.ino` | Main sketch: state variables, `setup()`, `loop()`, `handle_serial()`, `process_command()`, `pid_tick()`, `send_telemetry()`, mode management (`enter_mode()`), single-shot valve pulse (`fire_single_shot`/`fire_square_shot`), per-coil runner (`coil_runner_tick`), cam ISR (`proximityISR`), CAM callback (`coil_fire_cb`). |
| `injector_driver.h` | `#define`s for coil pins, MV PWM parameters, P&H safety window, boot defaults; declares `peak_hold_config_t g_ph_config`, `COIL_PINS[]`, `coil_pins_init()`, `fire_peak_hold_pin()`, `relay_set()`, `init_debug_pin()`. |
| `injector_driver.cpp` | Defines `COIL_PINS[NUM_COILS] = { COIL1_PIN, COIL2_PIN, COIL3_PIN }`. Implements `coil_pins_init`, `init_debug_pin`, and the IRAM-attributed `fire_peak_hold_pin()` with direct GPIO register writes (`GPIO.out_w1ts` / `out_w1tc`) and `portDISABLE_INTERRUPTS()` wrap. |
| `diesel_dashboard_FINAL.py` | Contains everything on the Python side: constants/palette, `class CylinderGauge(QWidget)`, `class SerialWorker(QObject)`, `class DieselDashboard(QMainWindow)`, and at module level the startup `_ModePicker(QDialog)`. |
| `presets_common_rail.json` | Storage for the calibration-table presets (INJECTOR MODEL dropdown). Written by the dashboard on Save/Update/Delete. |
| `injector_db.json` | **Different** DB: version "2.2". Holds "Common Rail injector profiles" with brand/model/type/engine/safety/modes, plus a `cambox_profiles` block. Consumed by the sidebar "INJECTOR PROFILE" panel (`_panel_presets()`) — this is **not** the calibration-table preset system. |

### 1.3 How to run

**Firmware** — Arduino CLI, board `esp32:esp32:esp32` (arduino-esp32 core 3.3.x), port `COM3`:
```
arduino-cli compile --upload -p COM3 --fqbn esp32:esp32:esp32 ESP32_Injector_Final
```
Wrapped in `_esp32_flash.bat`.

**Dashboard** — plain Python:
```
python diesel_dashboard_FINAL.py
```
Entry point at line 4809: `if __name__ == "__main__":` — creates `QApplication`, calls `_acquire_lock()` (single-instance lock via `socket.bind('127.0.0.1', 47832)`), shows `_ModePicker`, then constructs `DieselDashboard()` and `win.showMaximized()`. Requires: `PyQt6`, `pyqtgraph`, `pyserial`.

---

## 2. Firmware (ESP32)

### 2.1 Pin map — literal, from source

From `ESP32_Injector_Final.ino` lines 89–95:

```c
#define PIN_PROX      5
#define PIN_COIL      COIL1_PIN    // GPIO18 — Coil1, also the PCV/LEDC valve
#define PIN_PRESSURE  14
#define PIN_BUZZER    15
#define PIN_RELAY     19           // X6 — 12 V / 28 V Peak-supply select (MANUAL)
```

From `injector_driver.h` lines 37–42:

```c
#define COIL_PIN      18              // Coil1 — legacy alias
#define COIL1_PIN     18              // Coil1
#define COIL2_PIN     23              // Coil2
#define COIL3_PIN      4              // Coil3
#define NUM_COILS      3
#define DEBUG_PIN     GPIO_NUM_26     // oscilloscope trigger (free during test)
```

Also referenced but not driven by this firmware: GPIO 21/22 (LCD SDA/SCL, unused), GPIO 16/17 (UART2, unused), GPIO 36/39/34/35/32/33/25/26 (legacy keypad rows/cols, removed).

Mode constants (lines 96–98):
```c
#define MODE_CAM   0
#define MODE_PUMP  1
```

### 2.2 Coil channels

All 3 coils share the same pin-init in `coil_pins_init()` (`injector_driver.cpp`): `GPIO_MODE_OUTPUT`, pull-ups/downs disabled, initial level LOW.

| # | GPIO | What it drives (per source comments) | Drive method |
|---|---|---|---|
| Coil 1 | 18 | "PCV/SCV valve" in comments; the dashboard sends the MV commands to it | LEDC PWM in `MODE_PUMP` (12-bit, runtime-tunable 100–1000 Hz). Same pin also usable as `fire_peak_hold_pin()` target if fired directly, and `fire_single_shot`/`fire_square_shot` uses it via `PIN_COIL`. |
| Coil 2 | 23 | Nominally an injector coil (called "EUI" in the dashboard) | Peak & Hold (`fire_peak_hold_pin`) — OR plain 100 %-HIGH square when `s_sq_mode` is true (which is the boot default). Fired by cam ISR + per-coil runner. |
| Coil 3 | 4 | Nominally an injector coil (called "CR" in the dashboard) | Same P&H / SQUARE driver as Coil 2. |

**Peak & Hold** (`injector_driver.cpp:79`, `fire_peak_hold_pin(pin, total_pw_us, mark_debug)`):
- Attributed `IRAM_ATTR`.
- Fault gate rejects `total_pw_us` outside `[PH_PW_MIN_US=100, PH_PW_MAX_US=5000]` (defined in `injector_driver.h:47-48`) **before** calling `portDISABLE_INTERRUPTS()`.
- Waveform: `peak_us` at 100% HIGH → 2 chop cycles at 50% duty ("soft transition") → hold chop = 10 kHz (`hold_on_us=7`, `hold_off_us=93` defaults, `injector_driver.h:82-83`) → hard LOW.
- `SET_PH` cap in `.ino:852`: peak 50..800 µs, `on+off` in [50..500] µs so the chop stays near 10 kHz.
- Interrupts disabled during the *entire* pulse — the loop is blocked for the pulse width.

**No RMT is used.** No PWM ledc used for Coil 2 or Coil 3. There is no direct current measurement on any coil.

**Flyback**: **NOT IMPLEMENTED in firmware.** Assumed to be a hardware freewheel diode (`RURGB060` per the user's design notes) — no code path clamps or measures it.

**SQUARE / MAXPOWER mode** (`s_sq_mode`, `injector_driver.h` and `.ino:1157-1195`):
- Boot default is **ON** (line 208 in .ino sets `s_sq_mode = true`).
- When ON, `FIRE <n>` and `CRUN` fire plain 100 %-HIGH pulses via `fire_square_shot(pin, us)` instead of Peak & Hold.
- Alias command `HARD <n> <us>` maps to the same. Alias `MAXPOWER ON|OFF` maps to the same flag.

**Single-shot valve pulse** (`fire_single_shot`, .ino:227 area): hardware timer `s_shot_timer = timerBegin(1000000)` (1 MHz, 1 µs/tick), one-shot with `shot_end_isr` dropping the pin. Range `SHOT_MIN_US=500`, `SHOT_MAX_US=5000`.

### 2.3 Metering Valve — full details

From `injector_driver.h` (lines 58–68):
```c
#define MV_PIN            COIL1_PIN         // GPIO18
#define MV_PWM_FREQ_DEF   200UL             // default carrier 200 Hz
#define MV_PWM_FREQ_MIN   100UL             // runtime range (MV_FREQ command)
#define MV_PWM_FREQ_MAX   1000UL
#define MV_PWM_RES        12                // 12-bit resolution
#define MV_PWM_MAX        ((1UL << MV_PWM_RES) - 1UL)   // 4095
#define MV_MAX_DUTY_PCT   30                // safety cap (% of full duty)
#define MV_MAX_RAW        ((MV_PWM_MAX * MV_MAX_DUTY_PCT) / 100)  // = 1228
#define MV_MAX_CURRENT_A  1.8f              // for current-sense mode (optional)
#define MV_SOFTSTART_MS   200               // soft-start ramp on enable
// #define MV_CURRENT_SENSE_PIN 34          // uncomment if shunt+amp wired
```

Runtime state (`.ino:183-192`):
```c
#define MV_MODE_MANUAL    0
#define MV_MODE_PRESSURE  1
bool     s_mv_enabled       = false;
int      s_mv_mode          = MV_MODE_PRESSURE;
float    s_mv_manual_pct    = 0.0f;    // 0 .. 30
float    s_mv_target_raw    = 0.0f;    // computed each tick (raw LEDC)
float    s_mv_actual_raw    = 0.0f;    // soft-start ramp toward target_raw
bool     s_mv_fault         = false;
```

**LEDC setup** (`enter_mode(MODE_PUMP)`, .ino ~579): `ledcAttach(PIN_COIL, s_pcv_freq, MV_PWM_RES)` — 12-bit @ current `s_pcv_freq` (default 200). Also clears `s_mv_enabled=false`, `s_mv_fault=false`, actual/target raw to 0. On leaving PUMP: `ledcDetach(PIN_COIL)`.

**Runtime frequency change** (`MV_FREQ`, .ino:902-917): validates range, calls `ledcChangeFrequency(PIN_COIL, s_pcv_freq, MV_PWM_RES)` **only if in `MODE_PUMP`** (silent no-op in CAM mode). Duty and resolution are preserved.

**PID + soft-start** in `pid_tick()` (.ino:659-703). Called every `PID_DT_MS = 10 ms` from `loop()` **any time `s_mode == MODE_PUMP`** — the legacy `s_running` flag does *not* gate it any more. Sequence:

1. `s_actual_bar = read_pressure_bar()`.
2. Fault: if `s_actual_bar < 0` OR `> s_p_pmax * 1.05` → `s_mv_fault = true`.
3. If `!s_mv_enabled || s_mv_fault` → write 0 to LEDC, zero target/actual, return.
4. MANUAL: `target_raw = clamp(s_mv_manual_pct, 0, 30) * MV_PWM_MAX / 100`. PRESSURE: `target_raw = pid_compute(s_target_bar, s_actual_bar, 0.01)` — internally clamped to `MV_MAX_RAW`.
5. Hard cap: `target_raw = min(target_raw, MV_MAX_RAW)`.
6. Soft-start slew: `max_step = MV_MAX_RAW * (PID_DT_MS / MV_SOFTSTART_MS)` — actual walks toward target by ≤ ±max_step per tick.
7. `ledcWrite(PIN_COIL, actual_raw)`; mirror into legacy `s_pcv_duty`.

**PID gains**: `s_kp = 0.8`, `s_ki = 0.05`, `s_kd = 0.01` (defaults, .ino ~197). Tunable via `PID <Kp> <Ki> <Kd>`.

**Anti-windup**: conditional integration — the integral is only updated when the output is not saturated in the direction of further error (`pid_compute`, .ino:641-651).

**Feedback source**: pressure ADC on `PIN_PRESSURE = 14`.

**Current sensing**: **NOT IMPLEMENTED**. `MV_CURRENT_SENSE_PIN` is `#define`-commented; `MV_MAX_CURRENT_A = 1.8f` is defined but never read. `s_mv_meas_current` variable exists (line 192) but nothing writes to it.

### 2.4 Timers, interrupts, watchdog

- **`s_coil_timer`** (`esp_timer_handle_t`, .ino:213): esp_timer one-shot, `ESP_TIMER_TASK` dispatch, callback `coil_fire_cb`. Armed by `proximityISR` with the computed `s_fire_delay_us` after each cam edge; the callback then calls `fire_shot()` on every enabled non-Coil-1-in-PUMP-mode coil.
- **`s_shot_timer`** (`hw_timer_t*`, .ino:213-215): arduino-esp32 hardware timer at 1 MHz, callback `shot_end_isr` — drops the pin at the end of a single-shot / SQUARE pulse.
- **`proximityISR`** (`.ino:429-464`): attached to `PIN_PROX=5` with `RISING`, `IRAM_ATTR`. Debounce (`CAM_DEBOUNCE_US=5000`), max-RPM guard (`CAM_MAX_RPM=8000` → `CAM_MIN_PERIOD_US=7500`), rev counter, sliding RPM window (`RPM_WINDOW=5`). Uses **integer-only math** for `s_fire_delay_us` — a comment explicitly warns that FPU registers aren't saved in ISRs (would LoadProhibit ~10–20 s later).
- **Watchdog**: not explicitly touched. The main `loop()` is expected to be fast enough (P&H pulses ≤ 5 ms and `portDISABLE_INTERRUPTS()` blocks are ≤ a few ms). No `esp_task_wdt_*` calls.

### 2.5 Sensors — GPIO + conversion

**Pressure sensor** — `PIN_PRESSURE = 14`. `analogReadResolution(12)`, `analogSetAttenuation(ADC_11db)` (in `setup()`). Read + conversion in `read_pressure_bar()`, .ino:707-713:

```c
float v = (float)analogReadMilliVolts(PIN_PRESSURE) / 1000.0f;
float span = s_p_vmax - s_p_v0;
if (span <= 0.0001f) return 0.0f;
float bar = (v - s_p_v0) / span * s_p_pmax;
return bar < 0 ? 0 : bar;
```

`s_p_v0 = 0.5`, `s_p_vmax = 4.5`, `s_p_pmax = 2000.0` (defaults). Tunable at runtime via `PSCALE <v0> <vmax> <pmax>` (.ino ~959).

**RPM** — from `proximityISR` gaps, filtered through `current_rpm()` (.ino:715-732): median of the 5-sample window; returns 0 if last edge is older than `RPM_STALE_US = 2 s`. Formula: `60_000_000 / median_period_us`.

**Cam angle** — user-set `s_angle_deg` (via `a<deg>`). Delay-to-fire is `angle * gap / 360` computed integer-only in the ISR.

**Current**: **NOT MEASURED** (see 2.3).

---

## 3. Serial / Communication Protocol

### 3.1 Framing

- 115200 8N1, USB (CP210x). Line-based ASCII, `\n`-terminated (`\r` is stripped by `handle_serial()`, .ino ~770).
- Board→dashboard: unsolicited state lines have their own prefixes (`P:`, `MV:`, `CINFO:`, `CPULSES:`, `COILS:`, `RELAY:`, `SQMODE:`, `MAXPOWER:`, `MODE:`, `NOTE:`, `[CAM]`, `[PCV]`); command replies are `OK:…` / `ERR:…`.
- On the dashboard side, `SerialWorker.send_command(cmd)` writes `cmd + "\n"` directly (was signal-mediated; the current code at `.py:947` calls `self._write(cmd)` inline because "the previous signal indirection sometimes dropped commands issued from the connect callback"). `_write` skips if `self.port` is None or closed.

### 3.2 Every command in the firmware

From `process_command()` (starts .ino:786). Ordered as in the source.

| Command | Example | Reply (literal) |
|---|---|---|
| `start` | `start\n` | `OK:START` |
| `stop` | `stop\n` | `OK:STOP` then `CINFO:…` |
| `mode` (toggle) | `mode\n` | `OK:MODE:CAM` or `OK:MODE:PUMP` |
| `MODE CAM` | `MODE CAM\n` | `OK:MODE:CAM` |
| `MODE PUMP` | `MODE PUMP\n` | `OK:MODE:PUMP` |
| `MODE` (query) | `MODE\n` | `MODE:CAM` or `MODE:PUMP` |
| `w<us>` (global PW) | `w1500\n` | `OK:PW:1500` or `ERR:PW_RANGE_100-5000` |
| `f<hz>` (global freq for CAM free-run) | `f10\n` | `OK:FREQ:10` or `ERR:FREQ_RANGE_1-20` |
| `a<deg>` (cam angle) | `a45\n` | `OK:ANGLE:45` or `ERR:ANGLE_RANGE_0-359` |
| `SET_PH <peak> <on> <off>` | `SET_PH 350 7 93\n` | `PH_CONFIG_OK` or `PH_CONFIG_ERR:OUT_OF_RANGE` / `:BAD_FORMAT` |
| `PEAK <us>` | `PEAK 350\n` | `OK:PEAK:350` or `ERR:PEAK_RANGE_50-800` |
| `TARGET_P <bar>` | `TARGET_P 1200\n` | `OK:TARGET_P:1200` or `ERR:TARGET_P_RANGE_0-3000` |
| `MV` (snapshot) | `MV\n` | `MV:<en>,<mode>,<manual>,<target>,<actual_pct>,<fault>,<freq_hz>` |
| `MV_FREQ <hz>` | `MV_FREQ 500\n` | `OK:MV_FREQ:500` or `ERR:MV_FREQ_RANGE_100-1000` |
| `MV_ENABLE ON\|OFF` | `MV_ENABLE ON\n` | `OK:MV_ENABLE:ON`, or `ERR:MV_NOT_IN_PUMP_MODE`, or `ERR:MV_ENABLE_STATE_ON_OR_OFF` |
| `MV_MODE MANUAL\|PRESSURE` | `MV_MODE MANUAL\n` | `OK:MV_MODE:MANUAL` (or PRESSURE) or `ERR:MV_MODE_MANUAL_OR_PRESSURE` |
| `MV_DUTY <pct>` | `MV_DUTY 15\n` | `OK:MV_DUTY:15.0` or `ERR:MV_DUTY_RANGE_0-30` |
| `MV_FAULT_CLEAR` | `MV_FAULT_CLEAR\n` | `OK:MV_FAULT_CLEAR` |
| `PID <Kp> <Ki> <Kd>` | `PID 0.8 0.05 0.01\n` | `OK:PID:Kp=0.8000 Ki=0.0500 Kd=0.0100` or `ERR:PID_BAD_FORMAT` |
| `PSCALE <v0> <vmax> <pmax>` | `PSCALE 0.5 4.5 2000\n` | `OK:PSCALE:v0=0.500 vmax=4.500 pmax=2000` |
| `PCV_FREQ <hz>` | `PCV_FREQ 500\n` | `OK:PCV_FREQ:500` (100..20000) |
| `COILS` (query) | `COILS\n` | `COILS:<c1>,<c2>,<c3>` |
| `COIL <1\|2\|3\|ALL> ON\|OFF` | `COIL 2 ON\n` | `OK:COIL:2:ON` then `COILS:…` |
| `FIRE <n> [<us>]` | `FIRE 2 1500\n` | `OK:FIRE:2:1500us` (or `OK:FIRE:SQ:2:1500us` in SQMODE); errors `ERR:FIRE_RANGE_1-3` / `ERR:FIRE_WIDTH_100-5000` / `ERR:FIRE_COIL1_IS_PCV_IN_PUMP_MODE` |
| `CFREQ <n> <hz>` | `CFREQ 2 15\n` | `OK:CFREQ:2:15` then `CINFO:…` (1..20 Hz, `CFREQ_MAX=20`) |
| `CPW <n> <us>` | `CPW 2 800\n` | `OK:CPW:2:800` then `CINFO:…` (100..5000) |
| `CRUN <n> [<ms>]` | `CRUN 2 3000\n` | `OK:CRUN:2:15Hz:3000ms` then `CINFO:…` |
| `CSTOP <n\|ALL>` | `CSTOP ALL\n` | `OK:CSTOP:ALL` |
| `CINFO` | `CINFO\n` | `CINFO:<f1..3>,<pw1..3>,<r1..3>` (9 fields) |
| `SHOT [<us>]` | `SHOT 1000\n` | `OK:SHOT:1000us` (500..5000, valve GPIO18 only, refuses in PUMP mode) |
| `SQFIRE <n> <us>` | `SQFIRE 2 20000\n` | `OK:SQFIRE:2:20000us` (50..100000 µs) |
| `SQMODE` / `SQMODE ON\|OFF` | `SQMODE ON\n` | `SQMODE:1` or `OK:SQMODE:ON` |
| `HARD <n> <us>` | `HARD 1 2000\n` | `OK:HARD:1:2000us` — alias of SQFIRE (100..5000) |
| `MAXPOWER` / `MAXPOWER ON\|OFF` | `MAXPOWER ON\n` | `MAXPOWER:1` or `OK:MAXPOWER:ON` — alias of SQMODE |
| `RELAY` / `RELAY ON\|OFF` | `RELAY ON\n` | `RELAY:1` |
| `READPIN <n>` | `READPIN 5\n` | `READPIN:5:1` (0..39) |
| `PROBE <n>` | `PROBE 5\n` | `PROBE_START:5` then `PROBE:5:<v>:<ms>` for 10 s then `PROBE_END` |
| `STATUS` | `STATUS\n` | multi-line human-readable dump, delimited by `──…──` |
| Unknown | `foo\n` | `ERR:UNKNOWN:foo` |

Legacy `FAULT:PW_EXCEEDED:<us>` is emitted from inside `fire_peak_hold_pin` if `total_pw_us > PH_PW_MAX_US`.

### 3.3 Telemetry — literal format

From `send_telemetry()` (`.ino:750-756`), emitted every `TELEM_MS = 10 ms` (100 Hz):

```c
Serial.print("P:");  Serial.print(s_actual_bar, 1);
Serial.print(",A:"); Serial.print(s_angle_deg);
Serial.print(",R:"); Serial.print(current_rpm());
Serial.print(",I:"); Serial.print(s_mode == MODE_PUMP ? (int)(s_pcv_duty/255.0f*100.0f+0.5f) : s_freq_hz);
Serial.print(",C:"); Serial.println((int)s_rev_count);
```

Example line: `P:812.3,A:0,R:0,I:24,C:1523\n`

Meaning per field:
- `P:` = actual rail pressure in bar (from `s_actual_bar`).
- `A:` = commanded cam angle in degrees.
- `R:` = median-filtered RPM.
- `I:` = in PUMP mode: duty **percent**, computed as `s_pcv_duty / 255 * 100` — **this is wrong for the current 12-bit LEDC scale (should be `/ MV_PWM_MAX = 4095`); it under-reports by ~16×**. In CAM mode: `s_freq_hz`.
- `C:` = rev counter since boot.

Non-telemetry unsolicited lines (prefix + payload):
- `COILS:1,0,0`
- `RELAY:0` / `RELAY:1`
- `SQMODE:0` / `SQMODE:1`, `MAXPOWER:0`/`1`
- `MODE:CAM` / `MODE:PUMP`
- `CINFO:<f1>,<f2>,<f3>,<pw1>,<pw2>,<pw3>,<r1>,<r2>,<r3>`
- `CPULSES:<c1>,<c2>,<c3>` — 10 Hz while any per-coil runner is active
- `MV:<en>,<mode>,<manual>,<target_bar>,<actual_pct>,<fault>,<freq_hz>` — sent on boot, on change, and on `MV` request
- `NOTE: …` — free-text safety notes on boot

### 3.4 Boot banner (literal, .ino:497-521)

```
CamBox Pro (3-coil) - Ready
MODE:CAM
COILS:1,0,0            (from report_coils)
CINFO:10,10,10,1000,1000,1000,0,0,0
RELAY:0
SQMODE:1
MAXPOWER:1
MV:0,PRESSURE,0.0,0,0.0,0,200
NOTE: MV (Coil1/GPIO18) — LEDC 12-bit @ 200Hz (runtime 100-1000), MAX_DUTY 30% (safety), NORMALLY-OPEN valve.
NOTE: MAXPOWER=solid 100% pulse (no chop). Keep pulses short+spaced. Heatsink + ballast required.
NOTE: PEAK=full-voltage single shot (~25-30A). MOSFET/ballast must be rated. Relay boots OFF(12V); strong shots need RELAY ON(24V).
```

---

## 4. PyQt6 Dashboard

### 4.1 High-level structure

**Startup flow** (`.py:4809-4935` area):
1. `QApplication(sys.argv)`.
2. `_acquire_lock()` — binds `127.0.0.1:47832` to prevent a second instance.
3. Sets dark Fusion palette (a light palette is set by `_toggle_theme` on demand).
4. Shows the modal `_ModePicker` dialog (frameless, 620×360, two big cards: "CAMBOX / Cam-Synchronised Injection / EUI · GPIO 23" and "COMMON RAIL / PID Pressure Control / SCV · GPIO 18", plus an EXIT button). Returns `choice ∈ {'cambox', 'common_rail'}` or exits.
5. `DieselDashboard()` constructs the main window.
6. Applies picker choice by `win.rb_cam.setChecked(True)` or `win.rb_custom.setChecked(True)` — those radios live in the **hidden** INJECTION MODE panel (`_hidden_mode_panel`) but their `toggled` signal fires `_on_mode(mid)`.
7. `win.showMaximized()`.

**Main window layout** (`_build_ui`, `.py:1132-1149`):
```
main (QVBoxLayout)
├─ header bar (_make_header)          – logo, mode label, timer, PKT/s, PULSES,
│                                        theme button, connection status
└─ body (QHBoxLayout)
   ├─ left column (QScrollArea, fixed 340 px, contents from _make_left)
   │  ├─ CONNECTION           (_panel_conn)
   │  ├─ INJECTOR PROFILE     (_panel_presets)  — brand/model/mode combos
   │  ├─ [hidden]             (_panel_mode)    — kept for rb_cam / rb_custom
   │  ├─ PARAMETERS           (_panel_params)
   │  ├─ COILS                (_panel_coils)   — 3 rows, row 0 is MV
   │  ├─ RELAY · PEAK SUPPLY  (_panel_relay)
   │  └─ ACTUATORS            (_panel_actions) – START / STOP / SYNC / …
   └─ right column (_make_right)
      ├─ MEASUREMENTS         (_panel_meters)  – LCDs + INJ LED + ENGINE tile
      └─ body row (QHBoxLayout)
         ├─ Q INJECT   (_panel_cylinders)  – 5 cylinder gauges
         └─ CALIBRATION TABLE + presets toolbar (_panel_calib_table)
```

The `_panel_shot()` and `_panel_mini_graphs()` builders exist but their addWidget calls have been removed from `_make_left` / `_make_right` — dead code.

### 4.2 Panels — what each one shows

**CONNECTION** (`_panel_conn`, .py:1784): PORT combobox (auto-populated by `_refresh_ports` every 2 s), BAUD combobox, CONNECT/DISCONNECT toggle, Auto-Reconnect checkbox, INJECTOR ID field.

**INJECTOR PROFILE** (`_panel_presets`, .py:1828): Search bar + `+ ADD` button (opens `_on_add_profile` dialog). BRAND combo, MODEL combo (right-click opens Edit/Delete context menu — PIN-gated by `_verify_dev_pin`), TEST MODE combo (Full Load/Idle/Medium/Leak Test/VE), CAM PROFILE sub-combo (only visible for VE), Target RPM label, profile info card, safety limits badge. This whole panel operates on the SEPARATE `injector_db.json` file, not the calibration presets.

**PARAMETERS** (`_panel_params`): PULSE WIDTH (µs), FREQUENCY (Hz), DELAY ANGLE (°) — send `w`, `f`, `a` commands.

**COILS** (`_panel_coils` → 3× `_make_coil_row`, .py:2003-2160):
- Row 0 → `_make_mv_row()` (see below).
- Rows 1 (COIL 2 / EUI) and 2 (COIL 3 / CR): status dot, editable name (persisted to `coil_names.json` in `%APPDATA%\CAM PRO\`), pin label ("COIL 2" / "COIL 3"), OFF↔ON toggle (`COIL n ON|OFF`), `▶  SHOT` button (fires `SQFIRE n <pw>`), FREQ spinbox (1..20 Hz — **hidden on Coil 2** since it's cam-synced), PW spinbox (50..100000 µs), a hidden TIME spinbox (kept for parallel-array compat), `▶  RUN` toggle (fires `CRUN n <ms>`/`CSTOP n`), a live LED and pulse-rate label ("N · X Hz").

**COIL 1 / METERING VALVE row** — `_make_mv_row`, .py:2162-2249. Widgets:
- Read-only label "METERING VALVE" + pin label "COIL 1 · 12V".
- **ENABLE toggle** (`self.mv_enable_btn`) — sends `MV_ENABLE ON|OFF`. Text flips `DISABLED`↔`ENABLED`.
- **FAULT indicator label** (`self.mv_fault_lbl`) — reads "● FAULT" (red) or "● OK" (green) from `MV:` snapshots. Click on it sends `MV_FAULT_CLEAR`.
- **MODE combo** (`self.mv_mode_combo`) — 2 items: "PRESSURE (PID)" (index 0) and "MANUAL (duty %)" (index 1). Sends `MV_MODE PRESSURE|MANUAL`.
- **TARGET P (bar) spinbox** (`self.mv_target_p`, range 0..2000) — sends `TARGET_P <bar>`.
- **DUTY % spinbox** (`self.mv_duty`, range 0..30, suffix " %") — sends `MV_DUTY <pct>`.
- **PWM FREQ (Hz) spinbox** (`self.mv_freq`, range 100..1000, step 10, suffix " Hz") — sends `MV_FREQ <hz>`.
- **Live readouts row** (3 QLabels): `mv_p_lbl` "P: … bar", `mv_duty_lbl` "duty: … %", `mv_freq_lbl` "f: … Hz".
- Placeholder freq/pw/dur/run/led/pulse widgets are appended to the parallel `self._coil_*` arrays and hidden, so downstream loops don't index-error.

**RELAY** (`_panel_relay`): single big toggle, sends `RELAY ON|OFF`, labelled `OFF · 12V` / `ON · 28V`.

**ACTUATORS** (`_panel_actions`): START, STOP, SYNC PARAMS, ZERO Q, SAVE PDF, EXPORT CSV, AUTO-STOP checkbox.

### 4.3 MEASUREMENTS gauges (right pane top)

`_panel_meters()` builds 5 tiles:

| Tile | Widget | Source |
|---|---|---|
| RPM | `self.lcd_r` (`QLCDNumber` 5 digits) | `_snap_r` from `R:` telemetry, smoothed by `self._rpm_ema` in `_on_data` |
| PRESSURE | `self.lcd_p` (7 digits, bar) | `_snap_p` from `P:` |
| ANGLE | `self.lcd_a` (3 digits, deg) | `_snap_a` from `A:` |
| INJ PULSE | `self.inj_led` label + `self.inj_rate_lbl` | Rising edge on `I:` triggers 80 ms green flash via `self._led_timer`; rate label shows `inj/s` |
| ENGINE | `self.run_lbl` ("STOPPED"/"RUNNING") + `self.mode_lbl` ("COMMON RAIL"/"CAMBOX") | Dashboard-side state |

The three LCDs are updated from `_tick()` (called by `self._graph_timer` at `GRAPH_FPS`), which reads the current `_snap_*` values. `_on_data()` also sets `self.mv_p_lbl.setText(f"P: {self._snap_p:.0f} bar")` inside `_tick`.

---

## 5. Calibration Table & Presets

### 5.1 Literal table columns

From `.py:1533`:
```python
cols = ["Test Mode", "RPM", "PW (µs)", "Time (s)",
        "Target (ml)", "Min", "Max", "Unit", "Actual", "Status"]
```

10 columns, exactly. `QTableWidget(0, 10)`. Row height 72, column 0 fixed at 148 px, others Stretch.

Rows are always populated by `_populate_calib_table(profile)` (`.py:1567+`) for the mode names hard-coded in `mode_names = ["Idle", "Medium", "Full Load", "Leak Test", "CamBox"]`. Display names: `Idle → "Idle"`, `Medium → "Medium"`, `Full Load → "Full Load"`, `Leak Test → "Leak Test"`, `CamBox → "VE"`.

Cell editability:
- Column 0 (Test Mode) — read-only.
- Columns 1..6 (RPM, PW, Time, Target, Min, Max) — **editable** (set `editable=True` in the `cell()` helper).
- Column 7 (Unit) — read-only, shows `"≤ml/m"` for Leak Test and `"ml/1k"` for the others.
- Column 8 (Actual) — editable, blank on load.
- Column 9 (Status) — read-only, shows `"—"` initially, then `"✓  PASS"` (green) or `"✗  FAIL"` (red) via `_on_calib_actual_changed`.

### 5.2 Difference between Unit mode and Common Rail mode

**Zero difference in the table itself.** Same 10 columns, same 5 rows, same editable rules, same styling in both modes. The mode picker only changes:
- which firmware mode is active (`MODE CAM` vs `MODE PUMP`),
- which coils are enabled (`_on_mode()` in .py:4391),
- whether the Coil-1 row renders as an injector row or as the Metering-Valve row.

A dedicated "Unit mode" (batch-tester) is **not present** as a separate concept — the closest thing is the CamBox radio option.

### 5.3 Edit Dialog

There is **no dedicated edit dialog for the calibration-table presets.** Editing = editing the table cells in place. The only edit dialog in the codebase belongs to the SEPARATE `INJECTOR PROFILE` panel (which reads `injector_db.json`, not the presets).

**That dialog** — `_edit_profile_dialog(pid)` (.py:3195) — opens on `MODEL` combo right-click → "✏ Edit profile values" (PIN-gated). Layout: `QTabWidget` with one INFO tab and one tab per test mode.

- INFO tab fields (line 3221): Brand, Model, Type, Engine, `Max PW (µs)`, `Max Hz`, `Max RPM`.
- Per-mode tab fields (line 3247+), for each of `Idle / Medium / Full Load / Leak Test / CamBox (labelled VE)`:
  - `RPM`
  - `PW (µs)`
  - `Hz`
  - `Time (s)`
  - `Rail BAR`
  - `Target ml`
  - `Min ml`
  - `Max ml`

**Return Min/Max, Leak Test in bar, and Common Rail replacing RPM with pressure are NOT in this dialog either.**

### 5.4 Preset system (calibration table)

**Storage**: `presets_common_rail.json` (constant `PRESETS_JSON` at .py:1304), placed next to the entry point (`sys.argv[0]` dir, so the CWD of the running script/exe).

**Schema** (literal, from `presets_common_rail.json`):
```json
{
  "version": 1,
  "note": "Common-Rail injector calibration presets. Edit or add …",
  "presets": [
    {
      "name": "— Empty template —",
      "modes": {
        "Idle":      {"pressure_bar": null, "freq_hz": null, "pulse_us": null, "duration_s": null,
                      "vol_target": null, "vol_min": null, "vol_max": null,
                      "return_min": null, "return_max": null, "leak_limit_bar": null},
        "Medium":    { … same 10 fields … },
        "Full Load": { … },
        "Leak Test": { … },
        "CamBox":    { … }
      }
    },
    { "name": "Bosch 0445110xxx (CRIN)", "modes": { … } },
    { "name": "Denso 095000-xxxx (HP3)", "modes": { … } }
  ]
}
```

Per-mode fields: `pressure_bar`, `freq_hz`, `pulse_us`, `duration_s`, `vol_target`, `vol_min`, `vol_max`, `return_min`, `return_max`, `leak_limit_bar`.

**Toolbar above the table** (`_panel_calib_table`, .py:1495-1530):
- `INJECTOR MODEL` label + `self.preset_combo` (QComboBox, min width 240). First item is placeholder "— pick a preset —".
- `SAVE AS…` button → `_on_preset_save_as`.
- `UPDATE` button → `_on_preset_update`.
- `DELETE` button → `_on_preset_delete`.

**Button behavior — step by step**:

`SAVE AS…` (`_on_preset_save_as`, .py:1425):
1. `QInputDialog.getText(self, "Save Preset", "Injector model name:")`.
2. If empty/cancel → return.
3. If a preset with that name already exists → `QMessageBox.question` "Overwrite?"; on No, return; on Yes, remove the old entry.
4. Append `{"name": ..., "modes": self._current_table_as_preset_modes()}` to `self._presets_data["presets"]`.
5. `_save_presets_json()` writes the file.
6. `_refresh_preset_combo()` rebuilds the dropdown; then selects the new preset.
7. Logs `SAVED preset: …` in the comm log.

`UPDATE` (`_on_preset_update`, .py:1455):
1. If nothing picked → `QMessageBox.information` "Pick a preset from the dropdown first." and return.
2. Locate preset by name; overwrite its `"modes"` with `_current_table_as_preset_modes()`.
3. Save JSON.

`DELETE` (`_on_preset_delete`, .py:1469):
1. If nothing picked → info dialog, return.
2. Confirm with `QMessageBox.question` "Delete preset '…'? This cannot be undone."
3. Filter the preset out of the list, save JSON, refresh combo, blank the table via `_populate_calib_table(None)`.

`_current_table_as_preset_modes()` (.py:1382-1423):
- Column indices `C_NAME=0, C_RPM=1, C_PW=2, C_TIME=3, C_TGT=4, C_MIN=5, C_MAX=6`.
- Reads `num(item)` for each cell (handles "—", commas → dots, empty).
- Writes back `freq_hz` from RPM column, `pulse_us` from PW, `duration_s` from Time, `vol_target/min/max` from those columns.
- **Preserves `pressure_bar`, `return_min`, `return_max`, `leak_limit_bar`** from the currently-selected preset (or the preset being overwritten). No UI for these — they simply round-trip.

`_on_preset_pick(idx)` (.py:1353-1380):
- If index ≤ 0, no-op.
- Loads the preset by name and builds `profile = {"modes": {...}}` mapping:
  - `rpm ← freq_hz`
  - `pulse_us ← pulse_us`
  - `duration_s ← duration_s`
  - `vol_target ← vol_target`
  - `vol_min ← vol_min`
  - `vol_max ← vol_max`
  - `vol_unit ← "≤ml/m" if m == "Leak Test" else "ml/1000"`
- Calls `_populate_calib_table(profile)`.
- **Never touches the firmware.** Loading a preset does not send `TARGET_P`, `PCV_FREQ`, `w`, `f`, `a`, `MV_FREQ`, `MV_DUTY`, or anything else — it only fills the visible cells.

### 5.5 Present vs Missing — literal answers

| Feature | State | Details |
|---|---|---|
| Return / Back-leak fields (Return Min/Max) per stage | **Partial (JSON-only)** | Present in `presets_common_rail.json` (`return_min`, `return_max`). **No UI** in the calibration table or in `_edit_profile_dialog`. Round-tripped by `_current_table_as_preset_modes` but never displayed or entered. |
| Leak Test measured in bar instead of counts | **Missing** | `_on_calib_actual_changed` at .py:1622 does `ok = actual <= hi` where `hi` is the ml `vol_max`, and the Unit column shows `"≤ml/m"`. The JSON field `leak_limit_bar` exists but no code path consumes it. |
| Common Rail mode dropping RPM and replacing it with pressure | **Missing** | Column header is still `"RPM"` in both modes. Presets store `freq_hz` and the code shoves it into the RPM cell verbatim. `pressure_bar` from the JSON is not shown or used. |
| A FREQ (Hz) column per stage in the Common Rail table | **Missing** | No such column. `freq_hz` and `RPM` are conflated in the single `"RPM"` column. |
| Add-button letting the user choose Unit vs Common Rail | **Missing** | The calibration-table toolbar only has `SAVE AS…` / `UPDATE` / `DELETE` (no "Add"). The SEPARATE `INJECTOR PROFILE` panel's `+ ADD` button (`_on_add_profile`, .py:3352) always creates a Common-Rail-style profile — the default `type` string is `"Common Rail Solenoid"` (line 3416); there is no "Unit" vs "Common Rail" selector in that dialog either. |

---

## 6. State & Data Flow

### 6.1 Where each piece of state lives

**Firmware globals** (all in `.ino`):
- CAM/RPM ISR state: `s_last_trigger_us`, `s_period_us`, `s_fire_delay_us`, `s_rev_count`, `s_cam_seeded`, `s_rpm_win[5]`.
- Run state: `s_running`, `s_mode`, `s_pw_us`, `s_angle_deg`, `s_freq_hz`, `s_next_freerun_us`.
- Coil enables: `s_coil_en[3]` (boot = `{true, false, false}`).
- Per-coil runner: `s_coil_freq[3]`, `s_coil_pw[3]`, `s_coil_running[3]`, `s_coil_next_us[3]`, `s_coil_stop_us[3]`, `s_coil_pulses[3]`.
- Relay: `s_relay_on`.
- MV: `s_mv_enabled`, `s_mv_mode`, `s_mv_manual_pct`, `s_mv_target_raw`, `s_mv_actual_raw`, `s_mv_fault`, `s_mv_enable_ms`, `s_mv_meas_current` (unused).
- PID/pressure: `s_target_bar`, `s_actual_bar`, `s_pcv_duty`, `s_pcv_freq`, `s_kp/ki/kd`, `s_pid_integral`, `s_pid_prev_err`, `s_pid_have_prev`, `s_p_v0/vmax/pmax`.
- Peak & Hold shape: `g_ph_config` (defined in `injector_driver.cpp`, extern in `.h`).
- SQMODE: `s_sq_mode` (boot true), `s_shot_us`, `s_shot_pin`, `s_shot_busy`.

**Dashboard state** (all attributes of `DieselDashboard`):
- Snapshot values from telemetry: `_snap_p`, `_snap_r`, `_snap_a`, `_rpm_ema`, `_pkt_rate`, `_last_data_time`.
- Coil-row parallel arrays: `_coil_dots[3]`, `_coil_edits[3]`, `_coil_pins[3]`, `_coil_toggles[3]`, `_coil_fires[3]`, `_coil_freq_sp[3]`, `_coil_pw_sp[3]`, `_coil_dur_sp[3]`, `_coil_run_btns[3]`, `_coil_leds[3]`, `_coil_pulse_lbl[3]`, `_coil_on[3]`, `_coil_running[3]`, `_coil_pcount[3]`, `_coil_prate[3]`, `_coil_names[3]`.
- MV-row extras: `mv_enable_btn`, `mv_fault_lbl`, `mv_mode_combo`, `mv_target_p`, `mv_duty`, `mv_freq`, `mv_p_lbl`, `mv_duty_lbl`, `mv_freq_lbl`.
- Calibration table: `_calib_table` (`QTableWidget`), `_presets_data` (parsed JSON), `preset_combo` (calibration-preset combo — *overwrites* the `preset_combo` alias set by `_panel_presets` which was `= self.model_combo`), `preset_save_btn`, `preset_update_btn`, `preset_delete_btn`.
- Sidebar profile combos: `brand_combo`, `model_combo`, `mode_combo`, `cambox_combo`.
- Startup radio group (hidden): `rb_cam`, `rb_custom`, `mode_grp`.
- Injector-profile DB wrapper: `_injector_db` (loads/saves `injector_db.json`).

**Files on disk**:
- `presets_common_rail.json` — calibration-table presets. Written by `_save_presets_json`.
- `injector_db.json` — brand/model injector-profile DB. Written by `_injector_db.add_profile / update_profile / delete_profile`.
- `%APPDATA%\CAM PRO\coil_names.json` — persistent coil display names (per `load_coil_names` / `save_coil_names`).

### 6.2 End-to-end flow (typical Common-Rail session)

1. User launches → picker picks "Common Rail" → `_ModePicker` returns.
2. `DieselDashboard()` built. `win.rb_custom.setChecked(True)` fires `_on_mode(0)` **before** the serial worker has a port — commands are lost (SerialWorker's `_write` no-ops when `port` is None).
3. User picks COM3 → CONNECT. `SerialWorker.connect_device` opens the port with `dtr=None, rts=None` and a 300 ms settle to avoid the CP210x DTR-reset trap.
4. `_on_conn(True)` fires (.py:4530). Sends: `COILS`, `RELAY`, `CINFO`, `SQMODE ON`, then calls `self._on_mode(self._mode_id)` — which now sends:
   - `MODE PUMP`
   - `COIL 2 OFF`, `COIL 3 OFF`
   - `MV_MODE MANUAL`, `MV_DUTY 0`, `MV_ENABLE ON`
   - Finally `MV` (request snapshot).
5. Board replies with `OK:MODE:PUMP` + `OK:COIL:2:OFF` + `OK:COIL:3:OFF` + `OK:MV_MODE:MANUAL` + `OK:MV_DUTY:0.0` + `OK:MV_ENABLE:ON` + `MV:1,MANUAL,0.0,0,0.0,0,200`.
6. Board starts streaming `P:…,A:…,R:…,I:…,C:…` every 10 ms. `SerialWorker.read_loop` reads line by line and emits `data_received` → `DieselDashboard._on_data` dispatches by prefix.
7. User picks a preset from `INJECTOR MODEL` → `_on_preset_pick` fills the table. **Not sent to firmware.**
8. User moves `DUTY %` spinbox → `valueChanged` sends `MV_DUTY <v>`.
9. User moves `PWM FREQ` → sends `MV_FREQ <v>` → `ledcChangeFrequency` on the board → `OK:MV_FREQ:<v>` back.
10. User types the actual measured volume into the table's Actual cell → `_on_calib_actual_changed` reads Min/Max from the same row, sets Status to PASS/FAIL and updates the matching `CylinderGauge` in the Q INJECT panel.

Nothing in the calibration-preset system talks to the firmware. Everything from the injector-profile panel is a helper for the sidebar `PARAMETERS` (which then can be `SYNC`'d as `w`, `f`, `a` to the ESP32).

---

## 7. Known Gaps / TODO / Bugs

Ordered by real impact.

1. **`I:` telemetry uses wrong divisor** — `.ino:754` computes `s_pcv_duty/255.0f*100.0f`; the LEDC is 12-bit (max 4095), so the reported duty is ~16× too small in PUMP mode. Corrected duty is available in the `MV:` snapshot (`s_pcv_duty / MV_PWM_MAX * 100`, line 895) — the dashboard's MV panel uses that, so the bug is invisible in the UI but wrong on any raw serial log.
2. **`preset_combo` name collision** — `_panel_presets` (INJECTOR PROFILE sidebar) sets `self.preset_combo = self.model_combo` at .py:1922; then `_panel_calib_table` overrides `self.preset_combo` with the CALIBRATION preset combo (.py:1503). Any code that reads `self.preset_combo` (e.g. `_apply_preset`, `_save_pdf` when it inspects the current model) reaches the wrong combo after boot. Bug — untested.
3. **Preset "extras" are silent** — `pressure_bar`, `return_min`, `return_max`, `leak_limit_bar` are stored in JSON, preserved by round-trip, but **no UI enters or shows them**, and **no firmware call is made when a preset is picked** (e.g. `TARGET_P` is not auto-sent from `pressure_bar`). Dead weight until wired.
4. **RPM column is really `RPM or freq_hz`** — the same column is used for both meanings depending on where the number came from (user typed vs. preset-loaded).
5. **No dedicated Return-line meter** — hardware would be needed. `return_min/max` in the JSON schema are ml/min values, but no ADC path measures return flow.
6. **Current sensing** — `MV_MAX_CURRENT_A = 1.8` and `MV_CURRENT_SENSE_PIN` are `#define`-only, never wired. Safety is duty-clamp only.
7. **`MV_FREQ` silent no-op in CAM mode** — `.ino:912` guards `ledcChangeFrequency` with `if (s_mode == MODE_PUMP)`; sending `MV_FREQ 500` in CAM mode returns `OK:MV_FREQ:500` but the hardware isn't reconfigured (only `s_pcv_freq` is stored).
8. **`start` semantics** — `pid_tick()` runs whenever `s_mode == MODE_PUMP`, not just when `s_running`. `start` now only gates the CAM free-run fallback (`.ino ~528`) and the `[PCV]` log line (`log_pcv`, `.ino:737`).
9. **DTR-reset workaround** — `SerialWorker.connect_device` opens the port with `dtr=None, rts=None` + 300 ms sleep + input/output buffer flush. Verified on the current CP210x; may need revisiting on other USB-serial chips.
10. **Dead code paths in `_tick`** — after the WAVEFORM panel was removed, the graph-update path is guarded with `hasattr(self, 'curve_p')` but `pressure_buf.append(...)` etc. still runs every tick.
11. **Two parallel "preset" systems** with overlapping vocabulary — the sidebar `INJECTOR PROFILE` (backed by `injector_db.json` with brand/model/mode/rail_bar/vol_target/…) and the right-side `INJECTOR MODEL` (backed by `presets_common_rail.json`). They do not cross-reference and can hold contradictory numbers.
12. **`SET_PH` error string mismatch** — `PH_CONFIG_ERR:BAD_FORMAT` vs `PH_CONFIG_ERR:OUT_OF_RANGE` (rest of protocol uses `ERR:` prefix). Minor.
13. **Backup soup** — 30+ `.bak` files (`.stable`, `.premv`, `.prehard`, `.presqmode`, `.preui`, `.preprobe`, `.prerelay`, `.prepcpw`, `.precoilrun`, `.pre3coil`, `.prepeak`, `.premodeexplicit`, `.v4`, …) — no git worktree visible; this is the version history.
14. **`Ctrl+S` shortcut** is bound in `_setup_shortcuts` to `_save_pdf`, but also implicitly to text edit fields in Qt — no conflict noted, but focus-dependent.

---

## 8. Open Questions

Things in the code that are ambiguous or need your call:

- **Is Coil 1 really "just" the Metering Valve now, or should it still be usable as a P&H injector channel?** `fire_peak_hold_pin` and the runner can still target `COIL_PINS[0]` (the code refuses this only in `MODE_PUMP`, not in `MODE_CAM`), but the dashboard row was rebuilt around the MV — there's no UI in CamBox mode to fire Coil 1 as an injector.
- **`_panel_shot()` and `_panel_mini_graphs()` still exist** but are not addWidget'd anywhere. Deleted or kept as spares?
- **Two preset stores** (`presets_common_rail.json` + `injector_db.json`): should they be merged, or is the split intentional (bench-tech presets vs. shop database)?
- **`Return Min/Max` and `Leak (bar)` in the calibration table**: are we expected to add the columns (breaks layout) or add a per-row expand/detail dialog? The JSON fields exist to make the storage forward-compatible with whichever route we take.
- **`pressure_bar` from the preset**: on preset-pick, should the dashboard auto-send `TARGET_P <pressure_bar>` (per-mode)? Right now it does not.
- **`freq_hz` in a Leak Test preset row** is `null` (both shipped presets set it to null with `pulse_us: 0` and `duration_s: 60`). Should the row's RPM cell show `—` or `0` there? Current code shows `—`.
- **In `_on_add_profile` (sidebar profile ADD)** the profile always contains all 5 mode entries (Idle/Medium/Full Load/Leak Test/CamBox) with hard-coded defaults; is that acceptable, or should the ADD dialog let the tech pick which modes apply?
- **Firmware `stop` behaviour in PUMP mode** currently does `ledcWrite(PIN_COIL, 0)` and clears runners but does *not* touch `s_mv_enabled` — so if the tech hits STOP mid-PID, the MV re-enables the moment they nudge the DUTY spinbox (because `s_mv_enabled` was never cleared). Intentional?
- **The dashboard's `MV_ENABLE ON` step** requires the board to already be in `MODE_PUMP` (firmware returns `ERR:MV_NOT_IN_PUMP_MODE` otherwise). On the auto-prime path in `_on_mode(0)` the order is `MODE PUMP → MV_MODE MANUAL → MV_DUTY 0 → MV_ENABLE ON`; if `MODE PUMP` fails or lands mid-boot, everything after silently fails. No retry or backoff.
