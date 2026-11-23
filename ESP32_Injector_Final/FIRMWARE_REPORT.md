# CamBox Pro — Firmware Report (3-coil build)

**Date:** 2026-07-29
**Sketch:** `ESP32_Injector_Final/` (`ESP32_Injector_Final.ino`, `injector_driver.h`, `injector_driver.cpp`)
**Board:** `esp32:esp32:esp32` — ESP32 Arduino core **3.3.8**

## Build status — PASSED ✅
Compiled on-device with `arduino-cli 1.5.0` (bundled with Arduino IDE):

```
Sketch uses 330479 bytes (25%) of program storage space. Maximum is 1310720 bytes.
Global variables use 23208 bytes (7%) of dynamic memory, leaving 304472 bytes.
```

> **NOT yet flashed.** Pin map verified 2026-07-29 against the ESP32-30pin board
> diagram; Coil2 (GPIO23), Coil3 (GPIO4) and the Peak relay (GPIO19) are all
> confirmed wired. Nothing fires or energises on boot: Coil2/Coil3 boot disabled,
> Coil1 needs `start`, and the relay boots OFF (LOW / 12 V side).

No compile errors. The 7 "Problems" shown in VS Code are IntelliSense includePath
warnings only (`cannot open source file "esp_timer.h"`), not build errors — the
real toolchain resolves those headers.

---

## What changed from V4

| Item | V4 (old board) | This build |
|---|---|---|
| Control | Python serial + (no LCD/keypad in code) | Python serial only, LCD/keypad removed explicitly |
| Injector channels | 1 (GPIO23, RMT) | **3 coils** (GPIO18/23/4), individually enabled; GPIO18 doubles as the pump valve |
| Proximity | GPIO16 | **GPIO5** |
| Pressure ADC | GPIO4 | **GPIO14** |
| Pressure control | none (raw ADC to PC) | **PID closed loop on the coil (PUMP mode)** |
| Angle firing | `micros()` polling (~±15 µs) | **`esp_timer` one-shot** (jitter down to a few µs) |
| P&H chop | 10 kHz | 10 kHz (kept — 25 kHz overheats the coil) |

## Pin map (3-coil) — verified 2026-07-29 against the ESP32-30pin board diagram

Driven by this firmware:
```
GPIO18  X5  Coil1 PWM         (P&H; also the SCV / PCV / metering valve in PUMP mode)
GPIO23  X3  Coil2 PWM         (P&H)
GPIO4   X2  Coil3 PWM         (P&H)
GPIO5   X4  Proximity sensor  (cam trigger, 1 pulse/rev, RISING)
GPIO14  X1  Pressure sensor   (ADC, LM358 conditioned)
GPIO15      Buzzer
GPIO26      Debug timing pin  (oscilloscope; = keypad8, free since the keypad was removed)
```

Also driven by this firmware:
```
GPIO19  X6  Relay — 12 V / 28 V Peak-supply select (MANUAL, operator-toggled)
```

Present on the board, **not** driven by this firmware:
```
GPIO21/22   LCD SDA / SCL   (LCD unused)
GPIO16/17   UART2 RX / TX   (unused)
GPIO36/39/34/35/32/33/25/26 — old keypad rows/cols (keypad removed)
```
UART0 (GPIO1 TX / GPIO3 RX) is the USB dashboard link at 115200.

## Per-coil runner — own frequency, run duration, live pulse counts

Each coil can free-run Peak & Hold pulses at **its own frequency** AND **its own
pulse width** for a **set duration**, independent of the global `start`/CAM path.
One coil runs at a time in practice (single-shot bench), so there is no
simultaneous multi-coil current draw.

- `CFREQ <n> <hz>` sets coil n's frequency (1–200 Hz, `s_coil_freq[n-1]`).
- `CPW <n> <us>` sets coil n's own P&H width (100–5000 µs, `s_coil_pw[n-1]`). The
  runner fires each coil with **its own width**, not the global `s_pw_us`.
  `FIRE <n>` (no width) also uses `s_coil_pw[n-1]`; `FIRE <n> <us>` still overrides
  for that one shot; the global `w<us>` still drives the CAM / global free-run path.
- `CRUN <n> <ms>` starts coil n pulsing at that frequency and width; it
  **auto-stops** after `<ms>` (0 or omitted = run until `CSTOP`). Resets its counter.
- `CSTOP <n|ALL>` stops immediately and drives the pin LOW.
- `coil_runner_tick()` (called every `loop()`) schedules each running coil's next
  pulse from `esp_timer_get_time()`, so the frequency is time-based, not loop-rate.
- **Live display:** `CPULSES:<c1>,<c2>,<c3>` streams the per-run pulse counts at
  10 Hz while any coil runs (plus once on stop). `CINFO:<f1..3>,<pw1..3>,<r1..3>`
  reports freqs, widths + run flags on boot, on change, and on request. Neither
  prefix contains a `P:` substring, so `P:/A:/R:/I:/C:` telemetry is untouched.
- **Bench-verified (freq runner):** `CRUN 2 2000` at 25 Hz produced exactly **50**
  pulses; all three at 10/25/50 Hz for 1.5 s gave **15 / 38 / 75**.

### Hardware envelope (24 V via `RELAY ON`)

Series ballast ~0.5 Ω on the coil cable + coil ~0.3–0.5 Ω → **~25–30 A peak** during
the 350 µs PEAK, then the 10 kHz HOLD cuts the average. Per-channel MOSFET
**IRFP260N** (50 A cont / 200 A pulse, Rds~0.04 Ω) is comfortable for ~30 A peak but
needs a heatsink for continuous running. **One coil fires at a time** → no
simultaneous multi-coil draw. The thermal limit is the **ballast resistor (25 W)**
and the **coil**, not the MOSFET — higher frequency or wider `pw` = more average
heat, so keep `pw` modest at high frequency.

### Test plan (per-coil freq + width, strong repeated pulses)

```bash
RELAY ON ; PEAK 350                    # 24 V supply, strong opening kick
CFREQ 1 25 ; CPW 1 1500 ; CRUN 1 0     # coil1 continuous, 25 Hz, 1.5 ms
CFREQ 2 40 ; CPW 2 800  ; CRUN 2 3000  # coil2 for 3 s, 40 Hz, 0.8 ms
CSTOP ALL                              # stop; watch CPULSES + coil/resistor temp
```
Keep `pw` modest as frequency rises — the ballast resistor and coil are the heat
limit, not the MOSFET.

Safety: `stop` and any mode change halt every runner and drive the pins LOW. In
PUMP mode coil 1 (GPIO18/LEDC/PID) is refused, same rule as `FIRE 1` / `SHOT`. The
global free-run/CAM `fire_shot()` skips any coil that a per-coil runner owns, so a
coil is never double-fired. Blocking budget is the same as any P&H pulse — if
several coils come due in the same tick they fire sequentially (see file header).

## Strong shot — max needle-lift punch (Peak & Hold)

The Peak & Hold waveform is a full-voltage **PEAK** (snaps the needle open) followed
by a 10 kHz **HOLD** chop (keeps it open without overheating). A bigger peak = a
harder opening kick.

- **Default peak raised 175 → 350 µs** (`PH_PEAK_US_DEF`) for a strong, crisp shot.
  Hold default stays 7/93 µs (10 kHz) — the chop rule is unchanged.
- `PEAK <us>` sets just the peak (50–800 µs), leaving the hold alone.
- `SET_PH <peak> <on> <off>` now accepts peak up to **800 µs** (was 2000); the chop
  period `on+off` is held to **[50..500] µs** so it stays near 10 kHz.
- `FIRE <n> <us>` fires one shot at an explicit total width **for that shot only**
  (does not change the stored `w`/`s_pw_us`). `FIRE <n>` still uses `s_pw_us`.
- `STATUS` shows `P&H: peak=…us on=…us off=…us (…kHz)`.

> ### ⚠ Safety — the PEAK phase is FULL VOLTAGE
> With 24 V, a ~0.5 Ω ballast resistor and a ~0.3–0.5 Ω coil, peak current is
> **~25–30 A**. This is a **single, non-repeating** shot — never auto-repeat it at
> these levels. The **MOSFET must be rated for the peak current**, and the **ballast
> resistor for the average power**. Nothing fires on boot; the relay boots OFF (12 V)
> and a strong shot expects **RELAY ON (24 V)**. The board prints a `NOTE:` line at
> boot restating this.

### Test plan (strong shot)

1. `RELAY ON` — select the 24 V Peak supply (confirm 24 V on the scope/meter first).
2. `PEAK 350` — set the strong opening kick (already the default).
3. `FIRE 1` — expect a strong, crisp shot. Scope GPIO26 to see peak width then 10 kHz hold.
4. Repeat singly; **do not** auto-repeat rapidly.
5. If the MOSFET or ballast resistor heats up:
   - lower the peak: `PEAK 250`, or
   - lower the hold-on current: `SET_PH 350 5 95` (still 10 kHz), or
   - space the shots further apart.
6. `RELAY OFF` when done to drop back to 12 V.

## Single-shot valve pulse (SHOT) — precise, hardware-timed

`SHOT <us>` fires **one plain square pulse** of `<us>` µs (500–5000) on the valve
(GPIO18) — a discrete, on-demand energisation rather than PUMP mode's continuous
LEDC duty-cycle PWM. It is a *plain* pulse (full HIGH for the whole width), **not**
the chopped Peak & Hold waveform.

- **Timing:** a dedicated hardware timer (`timerBegin(1000000)` → 1 MHz, 1 µs/tick).
  The rising edge is issued in `fire_single_shot()`; the falling edge is timed in
  hardware and dropped by `shot_end_isr()` (a one-shot `timerAlarm`, `autoreload=false`).
  Non-blocking — unlike Peak & Hold it does **not** busy-wait with interrupts masked.
- **Scope marker:** GPIO26 frames the pulse (HIGH at the rising edge, LOW at the ISR),
  so the debug pin width equals the shot width.
- **Range / state:** `SHOT_MIN_US`=500, `SHOT_MAX_US`=5000; out of range → `ERR:SHOT_RANGE_500-5000`.
  A second `SHOT` while one is still HIGH → `ERR:SHOT_BUSY`. `SHOT` with no argument
  repeats the last duration (`s_shot_us`, default 1000). `STATUS` shows `shot_us`.
- **Mode guard:** rejected in PUMP mode (`ERR:SHOT_NOT_IN_PUMP_MODE`) because LEDC
  owns GPIO18 there — same pin-ownership rule as `FIRE 1`. Use it in CAM mode / idle.

> This is a *full-voltage* pulse for its whole length (no current chopping), so it
> is intended for the SCV / metering valve, not a bare low-Ω injector. A single
> pulse ≤ 5 ms is well within thermal limits; it is not repeated automatically.

## Bench validation log

**Test unit (injector):** `500339059`
**Date:** 2026-07-29

| Item | Value |
|---|---|
| Mode | CAM BOX (proximity-synced) |
| Waveform | **Square pulse** (MAXPOWER / SQMODE ON — full HIGH, no P&H chop) |
| Pulse width | **2800 µs** |
| Ballast resistor | **none** (removed) |
| Supply | 24 V, `RELAY ON` |
| Gate driver | TLP250 per channel |
| MOSFET | IRFP260N |
| Max cam speed | **900 RPM** → 1 pulse/rev = **15 Hz max** → duty ≈ **4.2 %** |
| Duration | **30 min continuous** |
| Result | ✅ **PASS** — MOSFET only *warm* (not hot); needle opened firmly; timing stable |

At 900 RPM the square pulse duty is only ~4.2 %, so MOSFET dissipation is a few
watts (Rds≈0.04 Ω) and the coil/injector duty stays low — this is why a full-power
square pulse runs cool at the rig's maximum speed. No Peak & Hold is required for
thermal safety within this 900-RPM envelope.

## Peak-supply relay (GPIO19) — MANUAL

GPIO19 selects the **12 V / 28 V Peak supply**. It is driven **manually** by the
operator (`RELAY ON|OFF` / the dashboard toggle) and is **never** switched per
pulse — the firmware just holds the commanded level. It boots as an OUTPUT driven
**LOW (OFF / 12 V side)** so the board powers up in a deterministic, safe state.

> The HIGH↔28 V vs HIGH↔12 V mapping depends on your relay board's active-high /
> active-low wiring. The dashboard labels OFF = 12 V and ON = 28 V as a starting
> assumption — confirm it on the bench (scope the coil supply while toggling) and
> relabel if your board is inverted. Nothing energises a coil on boot regardless.

## Three coils

`s_coil_en[3]` is the enable mask, boot value `{Coil1 ON, Coil2 OFF, Coil3 OFF}` —
i.e. identical behaviour to the previous single-coil build until you enable more.
`fire_shot()` walks the mask in order 1→2→3 and Peak & Hold fires every enabled
channel; only the first coil fired carries the GPIO26 scope marker. In PUMP mode
Coil1 is owned by the LEDC/PID loop and is skipped by `fire_shot()` / rejected by
`FIRE 1`, so PWM and P&H never fight over GPIO18. `stop` and every mode change
drive all three pins LOW.

### Blocking budget (read before enabling all three)

`fire_peak_hold_pin()` masks interrupts for the whole pulse and the coils fire
**sequentially**, so one shot costs `(enabled coils) × pw_us`:

| Enabled | pw = 1000 µs | @ 3000 RPM (20 ms/rev) |
|---|---|---|
| 1 coil | 1 ms | 5 % of the revolution masked |
| 2 coils | 2 ms | 10 % |
| 3 coils | 3 ms | 15 % |

Interrupts are re-enabled *between* coils, so this is N short windows rather than
one long one — but at high RPM with 3 coils the 100 Hz telemetry can still
stutter and cam edges can be missed. Keep `w` modest when running all three.

## Modes (both drive GPIO18, never at the same time)
- **CAM** — proximity-synced Peak & Hold pulse. `fire_delay = angle/360 × period`,
  recomputed every revolution, fired by an `esp_timer` one-shot. GPIO26 goes HIGH
  in the ISR and LOW at the fire instant, so the scope pulse width = the delay.
  Logs `[CAM] RPM=… angle=… delay=… pw=…` every 10 revolutions. If no cam signal
  is present it free-runs at `f` Hz so you can bench-pulse the solenoid.
- **PUMP** — closed-loop pressure. PID (100 Hz) sets the PWM duty on GPIO18 (LEDC,
  default 1 kHz) from the GPIO14 feedback. Logs `[PCV] target=… actual=… duty=… rpm=…`
  every 100 ms. PID has output clamping + conditional integral anti-windup.

## Serial commands
Preserved: `start`, `stop`, `w<us>` (100–5000), `f<Hz>` (1–200), `a<deg>` (0–359),
`mode`, `SET_PH <peak_us> <hold_on_us> <hold_off_us>`.
Added earlier: `TARGET_P <bar>`, `PID <Kp> <Ki> <Kd>`, `PSCALE <v0> <vmax> <pmax>`,
`PCV_FREQ <hz>`, `STATUS`.

New in the 3-coil build (all of the above still work unchanged):

| Command | Effect |
|---|---|
| `COIL <1\|2\|3\|ALL> ON` | enable that channel — it now fires with every shot |
| `COIL <1\|2\|3\|ALL> OFF` | disable it and drive the pin LOW immediately |
| `FIRE <1\|2\|3>` | one single Peak & Hold pulse, ignores the enable mask |
| `COILS` | report the mask as `COILS:<c1>,<c2>,<c3>` |
| `RELAY ON\|OFF` | MANUAL GPIO19 Peak-supply relay (12 V ↔ 28 V) |
| `RELAY` | report relay state as `RELAY:<0\|1>` |
| `SHOT <us>` | one precise plain valve pulse, 500–5000 µs (sets + fires) |
| `SHOT` | repeat the last SHOT duration |
| `CFREQ <n> <hz>` | set coil n's own free-run frequency (1–200 Hz) |
| `CPW <n> <us>` | set coil n's own P&H pulse width (100–5000 µs) |
| `CRUN <n> [<ms>]` | run coil n at its own freq **and width** for `<ms>` (0/omit = ∞) |
| `CSTOP <n\|ALL>` | stop coil n's runner |
| `CINFO` | report `CINFO:<f1..3>,<pw1..3>,<r1..3>` (freqs, widths, run flags) |
| `PEAK <us>` | set only the P&H peak phase, 50–800 µs (hold chop unchanged) |
| `FIRE <n> <us>` | one shot of `<us>` total width for that shot only (100–5000) |

`COILS:…` and `RELAY:…` are emitted on boot, on change, and on request — **never**
in the 100 Hz stream, so the `P:…,A:…,R:…,I:…,C:…` telemetry format is untouched.
`STATUS` now lists each coil's pin/enable state and the relay state.

> `SET_PH` format is `<peak> <hold_on> <hold_off>` (V4 used `<peak> <period> <on>`).
> Update the dashboard's SET_PH sender if it still uses the old order.

## Recommended settings
**PID (rail/pump valve)** — start `PID 0.8 0.05 0.01`; tune Kp (approach), then Ki
(kill steady error), then Kd (damp overshoot). Anti-windup is built in.

**SET_PH (10 kHz hold, period = on + off = 100 µs)**

| Injector | Command | Hold current |
|---|---|---|
| Bosch CRIN (~0.5 Ω) | `SET_PH 175 7 93` | ≈ 2.1 A |
| Denso CR (~0.3 Ω) | `SET_PH 175 5 95` | ≈ 1.8 A |

**PSCALE** — set from your sensor datasheet, e.g. `PSCALE 0.5 4.5 2000`
(0.5 V→0 bar, 4.5 V→2000 bar). Confirm the ADC divider keeps GPIO14 ≤ 3.3 V.

## Still requires the physical rig (cannot be done in software)
1. Flash the firmware to the board (confirm wiring matches the pin map first).
2. STEP 4 bench checks:
   - CAM: angle must stay constant ±0.5° at 200/500/1000/1500/2000 RPM
     (expected delay @10°: 8333/3333/1667/1111/833 µs).
   - PUMP: pressure stabilizes within 3 s at 800/1000/1200/1500 bar.
   - Peak = 175 µs ±2 µs on the GPIO26 scope; hold chops at 10 kHz.
3. Set `PSCALE` from the sensor datasheet.

## Files
- `ESP32_Injector_Final.ino`, `injector_driver.h`, `injector_driver.cpp` — the build (compiles).
- `*.v4.bak` — backups of the original V4 files.
- `*.pre3coil.bak` — backups of the single-coil build, taken before the 3-coil change.
- `../ESP32_CamBox_V5/` — earlier 3-channel design; its `fire_peak_hold(pin, …)`
  shape is what this build's `fire_peak_hold_pin()` is based on.
