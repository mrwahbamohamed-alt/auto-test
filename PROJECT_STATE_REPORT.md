# DIT-3000 / INJECTOR PRO — Project State Report

## 1. Overview

- **Purpose:** Bench diesel-injector test system: drive up to 3 solenoid injector coils (Peak & Hold pulses) *and* a proportional Fuel Metering Valve (PWM), synced to a cam-proximity sensor, with a live GUI for measurement + calibration.
- **MCU:** ESP32 (`esp32:esp32:esp32`, arduino-esp32 core 3.3.x), Arduino/C++, USB serial @ 115200.
- **GUI:** Python 3.12 + **PyQt6** + pyqtgraph. Single-window `QMainWindow`.
- **File layout:**
  - `ESP32_Injector_Final/ESP32_Injector_Final.ino` (~1314 LOC — main sketch)
  - `ESP32_Injector_Final/injector_driver.h` / `.cpp` (Peak & Hold pin-bang driver, defines)
  - `diesel_dashboard_FINAL.py` (~4934 LOC — the whole dashboard)
  - `presets_common_rail.json` (injector calibration presets)
  - Many `*.bak` snapshots per feature branch (`.stable`, `.premv`, `.prehard`, `.presqmode`, …)

## 2. Operating Modes

| Mode | Firmware side | UI side |
|---|---|---|
| **CAM / CamBox** | `MODE_CAM` = proximity ISR (GPIO5, RISING) fires enabled coils via `esp_timer` one-shot at `angle_deg` after the trigger; free-run fallback at `s_freq_hz` when the cam is stale (`RPM_STALE_US = 2 s`). | Startup popup `_ModePicker` → `MODE CAM` + `COIL 2 ON` + `COIL 1/3 OFF` (only EUI fires with the cam). Coil 2 row hides the FREQ spinbox because it's cam-synced. |
| **Common Rail / PUMP** | `MODE_PUMP` = GPIO18 detached from digital use, reattached as LEDC PWM (12-bit @ 200 Hz default). `pid_tick()` runs every `PID_DT_MS=10 ms` **any time we're in PUMP mode** (no `start` needed) but only outputs duty when `s_mv_enabled` is true. | Startup popup → `MODE PUMP` + auto-prime: `MV_MODE MANUAL` + `MV_DUTY 0` + `MV_ENABLE ON`. Coil 1 row is replaced with a "METERING VALVE" panel (`_make_mv_row()`). |
| Legacy switch | `mode` (lowercase) still toggles CAM↔PUMP for back-compat. Explicit `MODE CAM` / `MODE PUMP` / `MODE` (query) added later — dashboard uses the explicit form. | — |

A **"Unit test"** mode is **not implemented as a distinct firmware mode**. The dashboard's INJECTOR PROFILE / test-mode combo (Idle / Medium / Full Load / Leak Test / VE) is purely a parameter-preset concept applied on top of whichever firmware mode is active.

## 3. Coil Channels

All 3 coils go through TLP250 gate driver → IRFP260N low-side MOSFET (2× in parallel on Coil 1). A `GPIO19` relay selects the Peak supply (12 V default / 24-28 V on `RELAY ON`).

| # | GPIO | What it drives | How firmware drives it |
|---|---|---|---|
| **Coil 1** | **18** | **Fuel Metering Valve** (Bosch ZME, ~2.5 Ω, normally-open) at 12 V | **Continuous LEDC PWM**, 12-bit, 100–1000 Hz (`MV_FREQ`, default 200), duty hard-capped at `MV_MAX_DUTY_PCT = 30 %` (`MV_MAX_RAW = 1228`). Two sub-modes: `MV_MODE_MANUAL` (user duty) or `MV_MODE_PRESSURE` (PID from GPIO14). Soft-start ramp `MV_SOFTSTART_MS = 200 ms`. Fault latch on pressure out-of-range (`s_actual_bar < 0` or > `1.05 × PSCALE.pmax`). |
| **Coil 2** | **23** | Injector "EUI" (cam-synced) | **Peak & Hold** via `fire_peak_hold_pin()` (direct GPIO bang, `esp_rom_delay_us`, interrupts disabled during pulse) — **OR** plain 100 %-HIGH SQUARE pulse when `s_sq_mode`/MAXPOWER=ON (which is the *default at boot*). Fired by cam ISR + per-coil runner. |
| **Coil 3** | **4** | Injector "CR" (spare / free-run) | Same P&H / SQUARE driver as Coil 2, own frequency (`CFREQ`), own width (`CPW`), own runner (`CRUN`). |

**Metering Valve safety chain**:
1. `MV_MAX_DUTY_PCT` hard clamp in firmware (never > 30 %).
2. Fault latch → PWM = 0, `s_mv_fault = 1`, cleared only by `MV_FAULT_CLEAR` + re-`MV_ENABLE ON`.
3. Optional current-sense pin `MV_CURRENT_SENSE_PIN` is `#define`-guarded — **not enabled** (no code path uses it).
4. `MV_MAX_CURRENT_A = 1.8f` defined but **not enforced** (no current sensor connected).

## 4. Calibration Table & Presets

### Actual table columns (identical for BOTH modes)

`diesel_dashboard_FINAL.py:1533`
```
["Test Mode", "RPM", "PW (µs)", "Time (s)", "Target (ml)",
 "Min", "Max", "Unit", "Actual", "Status"]
```

5 rows, hard-coded modes: **Idle · Medium · Full Load · Leak Test · VE** (VE = "CamBox" key internally). All spec cells (RPM/PW/Time/Target/Min/Max) are `editable=True`; Actual is editable, Status is read-only.

### What's the same vs. what differs Common Rail ↔ CamBox

**Nothing differs between modes in the table itself** — same 10 columns, same rows, same edit rules. The mode picker only changes:
- which firmware mode is active,
- which coils get enabled,
- whether the Coil 1 row renders as an injector row (CamBox) or as the Metering Valve row (Common Rail).

### Preset system

- **Storage:** `presets_common_rail.json`, sibling of the running .py. Loaded by `_load_presets_json()`, saved atomically by `_save_presets_json()` after every mutation.
- **Toolbar** above the table (`_panel_calib_table`): `INJECTOR MODEL` `QComboBox` + `SAVE AS…` + `UPDATE` + `DELETE` buttons.
- **On selection:** `_on_preset_pick()` folds preset → the profile dict shape `_populate_calib_table()` expects, and fills the table.
- **On Save/Update:** `_current_table_as_preset_modes()` reads visible cells back; **preserves the extra JSON-only fields** (`pressure_bar`, `return_min`, `return_max`, `leak_limit_bar`) from the currently-selected preset if any.
- **No dedicated Edit Dialog** — editing is done in-place in the table (spec cells are editable), then `UPDATE` writes back. `SAVE AS…` uses a plain `QInputDialog.getText` for the name. Delete uses a `QMessageBox.question` confirm.

### JSON preset schema (per mode, per preset)

```json
{
  "pressure_bar":   int|null,
  "freq_hz":        num|null,
  "pulse_us":       num|null,
  "duration_s":     num|null,
  "vol_target":     num|null,
  "vol_min":        num|null,
  "vol_max":        num|null,
  "return_min":     num|null,
  "return_max":     num|null,
  "leak_limit_bar": num|null
}
```

Shipped presets: `— Empty template —`, `Bosch 0445110xxx (CRIN)`, `Denso 095000-xxxx (HP3)`.

### Straight answers to your specific questions

| Q | A |
|---|---|
| **Return / Back-leak (Return Min/Max) per stage?** | **Not in the table.** Only stored in JSON (`return_min` / `return_max`) — round-tripped through Save/Update but never displayed or entered from the UI. |
| **Leak Test measured in bar vs counts?** | **Neither, cleanly.** The Leak Test row uses the same `Actual` cell as the others; the Unit column reads `≤ml/m`, and `_on_calib_actual_changed` compares `actual ≤ max`. `leak_limit_bar` exists in the JSON schema but is *not* consumed by any UI or firmware code. |
| **Did Common Rail drop RPM and use Pressure instead?** | **No.** Column 1 is still labelled `"RPM"` in both modes. The preset stores `freq_hz` and pushes it into the RPM cell verbatim (that column is effectively "RPM *or* free-run freq"). `pressure_bar` is JSON-only, never rendered. |
| **FREQ (Hz) column per stage in Common Rail table?** | **No.** No dedicated FREQ column. `freq_hz` lives in JSON and gets shoved into the `RPM` cell on load — implicit conflation. |

## 5. Measurements / Telemetry

**Header MEASUREMENTS panel** (`_panel_meters`), three `QLCDNumber` displays + one status frame + one INJ-pulse LED frame:

| Widget | Source |
|---|---|
| `lcd_r` (RPM) | `_snap_r` ← telemetry `R:` |
| `lcd_p` (PRESSURE, bar) | `_snap_p` ← telemetry `P:` |
| `lcd_a` (ANGLE, deg) | `_snap_a` ← telemetry `A:` |
| `inj_led` + `inj_rate_lbl` | rising edge on `I:` field triggers 80 ms green flash |
| ENGINE frame (`run_lbl`, `mode_lbl`) | dashboard-side (STOPPED / RUNNING, COMMON RAIL / CAMBOX) |

**MV panel** (Coil 1 row) has its own live readouts: `mv_p_lbl` (P bar, mirrors `_snap_p`), `mv_duty_lbl` (measured duty %), `mv_freq_lbl` (carrier Hz), `mv_fault_lbl` (green OK / red FAULT).

**Telemetry line** (every 10 ms from `send_telemetry()`):
```
P:<bar>,A:<deg>,R:<rpm>,I:<val>,C:<revcount>
```
- `P:` = actual rail pressure from GPIO14 through `PSCALE` linear map.
- `I:` overloaded: in PUMP mode = duty percent (currently computed as `s_pcv_duty / 255 * 100` — **BUG**, see Gaps), in CAM mode = current `s_freq_hz`.
- **No current** is measured or reported anywhere (no current-sense hardware).

## 6. Serial Protocol

**Line-based ASCII, `\n`-terminated, 115200 bps.** Responses prefixed `OK:` / `ERR:`; unsolicited state lines have their own prefix (`P:` / `MV:` / `CINFO:` / `CPULSES:` / `COILS:` / `RELAY:` / `SQMODE:` / `MAXPOWER:` / `MODE:` / `NOTE:`).

### Command list (from `process_command()` @ line 787)

| Command | Purpose |
|---|---|
| `start` / `stop` | legacy master run flag (`s_running`) — gates CAM free-run + PCV log only |
| `mode` | **toggle** CAM/PUMP (kept for back-compat) |
| `MODE CAM` / `MODE PUMP` / `MODE` | explicit set / query |
| `w<us>` / `f<Hz>` / `a<deg>` | global pulse width / freq / angle (CAM path) |
| `SET_PH <peak> <on> <off>` | Peak & Hold shape (peak 50–800, chop 50–500 µs) |
| `PEAK <us>` | shortcut for peak only |
| `TARGET_P <bar>` | MV PRESSURE-mode setpoint |
| `PID <Kp> <Ki> <Kd>` / `PSCALE <v0> <vmax> <pmax>` / `PCV_FREQ <hz>` | tuning |
| `COILS` / `COIL <n\|ALL> ON\|OFF` | injector enable mask (query / set) |
| `FIRE <n> [<us>]` | one shot on coil n (P&H or SQUARE if SQMODE) |
| `CFREQ <n> <hz>` (1–20) · `CPW <n> <us>` (100–5000) · `CRUN <n> [<ms>]` · `CSTOP <n\|ALL>` · `CINFO` | per-coil runner |
| `SHOT [<us>]` (500–5000) | legacy plain valve pulse on GPIO18 |
| `SQFIRE <n> <us>` (50–100000) | plain SQUARE pulse on coil n |
| `SQMODE` / `SQMODE ON\|OFF` | global: FIRE/CRUN use SQUARE instead of P&H (default ON) |
| `HARD <n> <us>` (100–5000) · `MAXPOWER [ON\|OFF]` | aliases of SQFIRE / SQMODE |
| `RELAY` / `RELAY ON\|OFF` | 12 V / 24 V Peak-supply relay |
| `MV` | MV snapshot: `MV:<en>,<mode>,<manual%>,<target_bar>,<actual%>,<fault>,<freq_hz>` |
| `MV_ENABLE ON\|OFF` · `MV_MODE MANUAL\|PRESSURE` · `MV_DUTY <pct>` · `MV_FREQ <hz>` · `MV_FAULT_CLEAR` | MV control |
| `READPIN <n>` · `PROBE <n>` | diagnostics (one-shot / 10 s stream of GPIO level) |
| `STATUS` | human-readable multi-line dump |

### Dashboard command examples (from `_on_conn`, `_on_mode`, MV handlers)

Auto-fired on connect + Common Rail pick:
```
COILS · RELAY · CINFO · SQMODE ON
MODE PUMP · COIL 2 OFF · COIL 3 OFF
MV_MODE MANUAL · MV_DUTY 0 · MV_ENABLE ON · MV
```

## 7. Known Gaps / TODO

Ordered roughly by "how much it will bite":

1. **`I:` telemetry field uses the wrong denominator in PUMP mode** — line 754 still divides `s_pcv_duty / 255.0f` but the LEDC is now **12-bit (max 4095)**. Reports duty as ~16× larger than reality. Not consumed anywhere critical (the MV UI uses the `MV:` snapshot's `actual%` which *is* correct at `s_pcv_duty / MV_PWM_MAX`), but it will confuse anyone reading raw telemetry.
2. **Preset "extras" are silent** — `pressure_bar`, `return_min`, `return_max`, `leak_limit_bar` are stored in JSON and preserved on Save/Update round-trip, but there is **no UI to view or enter them**, and **no firmware/dashboard code consumes** `pressure_bar` (e.g. to auto-set `TARGET_P` when a preset is loaded) or `leak_limit_bar` (leak PASS/FAIL still uses `vol_max`, not bar). Round-tripped dead weight until the UI is added.
3. **RPM column is really a mixed FREQ/RPM cell** — presets write `freq_hz` into the RPM cell; there is no separate FREQ (Hz) column for the metering-valve pressure stages. Rename to "RPM / FREQ" or split into two columns.
4. **No dedicated Return-line meter** anywhere — hardware would be needed (`return_min`/`max` in JSON are ml/min values, no code path measures return flow).
5. **Current sensing** (`MV_MAX_CURRENT_A = 1.8 A`, `MV_CURRENT_SENSE_PIN` `#define`-guarded and undefined) — never wired, never read. Safety is duty-clamp only.
6. **`ledcChangeFrequency` glitch guard** — `MV_FREQ` calls it only when `s_mode == MODE_PUMP`; if user sends `MV_FREQ` in CAM mode the number is stored but the LEDC hardware isn't reconfigured (silent no-op). Not a bug per se but easy to trip over.
7. **`start` semantics vs `MV_ENABLE`** — after the MV rework, `start` no longer gates PUMP-mode PID (`pid_tick()` runs whenever `s_mode == MODE_PUMP`). `start` now only gates the CAM free-run fallback and the periodic `[PCV]` log. Confusing legacy.
8. **DTR-reset workaround for connect** is in `SerialWorker.connect_device` (opens the port with `dtr=None, rts=None` + 300 ms settle). Works on the CP210x currently in use; may need revisiting on other USB-serial chips.
9. **Cosmetic:** `WAVEFORM` panel removed but the `_tick` graph-update path still references `curve_p` — guarded with `hasattr(self, 'curve_p')` but the buffer fill code (`self.pressure_buf.append(...)`) still runs every tick, wasting CPU.
10. **Injector-profile "Test Mode" selector** in the sidebar (Idle / Medium / Full Load / Leak Test / VE) is a separate system from the calibration-table presets. They share concepts (mode names, target volumes) but their data models don't cross-reference. Two sources of truth.
11. **Backup soup**: 30+ `*.bak` files in `ESP32_Injector_Final/` — no git worktree in evidence, so version history lives in filename suffixes (`.stable`, `.premv`, `.prehard`, `.presqmode`, `.preui`, `.preprobe`, `.preprelay`, `.prepcpw`, `.precoilrun`, `.presqmode`, `.pre3coil`, `.prepeak`, `.premodeexplicit`, `.v4`…).
