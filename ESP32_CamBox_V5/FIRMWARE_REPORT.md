# CamBox Pro V5 — Firmware Audit & Build Report

**Date:** 2026-07-29
**Scope:** Audit of the existing V4 firmware (`ESP32_Injector_Final/`) and a new
V5 firmware set (`ESP32_CamBox_V5/`) targeting the new board pin-out with
per-revolution angle tracking, closed-loop rail-pressure control, and a
multi-channel Peak & Hold driver.

> ⚠ **Hardware not verified.** V5 targets a new board that was not physically
> available during this work. The firmware compiles against the arduino-esp32
> v3.x / IDF 5.x API and is logically complete, but every timing and pressure
> figure below is *analytical/expected* — not a bench measurement. Do not treat
> any number here as validated until STEP 4 is run on the real rig.

---

## STEP 1 — Audit of the existing V4 firmware

### Was angle tracking correct before? **Yes — essentially correct.**
The V4 `cambox_isr` measured the revolution period (`gap = now - s_last_cam_us`)
and `handle_cambox()` computed `delay_us = (delay_deg / 360) * s_rpm_period`
using the **most recent** period, recomputed on every cam edge. That matches the
required formula. Two caveats:

1. **One-revolution lag** (inherent to any single-pulse-per-rev system): the
   delay for the current revolution uses the *previous* revolution's period.
   Correct at steady RPM; slightly off during hard acceleration. Unavoidable
   with 1 pulse/rev without prediction.
2. **Firing method = polling, not a hardware timer.** V4 armed `s_fire_at_us`
   and compared `micros()` every loop iteration (~±15 µs jitter ≈ ±0.18° at
   2000 RPM). Within spec, but a one-shot `esp_timer` removes the software
   polling jitter. **This is the main thing V5 improves.**

### Was there existing pressure control (PID)? **No.**
V4 read the pressure ADC (GPIO4) as a raw 256-sample average and streamed it to
the Python dashboard as millivolts. **All** scaling/filtering happened in Python.
There was no PID, no PCV output, and GPIO18 was unused. "Common Rail" in the V4
code referred only to the Peak & Hold *waveform* path used in Custom mode — not a
pressure-controlled mode.

### Jitter sources found in V4
- Software-polled fire instant (~±15 µs).
- Peak & Hold path disables interrupts for the whole pulse (which is *why* V4
  deliberately never used P&H in CamBox — it would stall the cam ISR).
- One-revolution period lag (physical, not a bug).

### Pin-map conflict discovered (V4 vs the V5 spec)
| Signal | V5 spec | V4 firmware (actual) |
|---|---|---|
| Proximity | GPIO5 | **GPIO16** |
| Pressure ADC | GPIO14 | **GPIO4** |
| Injector | 3 ch (18/23/4) | **1 ch, GPIO23 (RMT)** |
| PCV / relay / LCD / keypad | required | **absent** |

Because the boards differ, V5 was written as **new files** in `ESP32_CamBox_V5/`.
The V4 sketch is untouched and still valid for the old board.

### Peak & Hold chop rate — kept at 10 kHz (not 25 kHz)
The V4 header documents that 25 kHz (40 µs) accumulated coil current and
overheated the solenoid, and it was deliberately set to **10 kHz (100 µs)**. The
V5 spec's request for 25 kHz was **rejected on your instruction** to avoid
re-introducing that fault. V5 keeps 10 kHz.

---

## STEP 2 — CAM mode (V5)

- Proximity ISR on **GPIO5**, RISING. `esp_timer_get_time()` for the period.
- Same three-stage EMI filter ported from V4 (5 ms debounce, 8000-RPM
  plausibility, adaptive half-period refractory).
- `fire_delay_us = (angle_deg / 360) * period_us`, **recomputed every rev.**
- Fires via **`esp_timer` one-shot** (`coil_fire_cb`) → removes the software
  polling jitter. Timer resolution is 1 µs; callback latency is a few µs.
- **GPIO26 debug pulse:** HIGH in the ISR, LOW at the fire instant → the scope
  pulse width *is* the injection delay. (`HIGH..LOW` = delay.)
- Logs every 10 revolutions: `[CAM] RPM=<X> angle=<Y>deg delay=<Z>us pw=<W>us`.

**Blocking-budget caveat:** the spec asks for Peak & Hold on *all* injector
channels in CAM mode. P&H blocks with interrupts masked for the pulse duration.
Firing 3 channels × up to 5 ms = up to 15 ms of blocking per shot. That is fine
at bench RPM (30 ms period @ 2000 RPM) for a single wired injector, but at high
RPM with all three channels it can crowd the revolution. Recommendation: on a
single-injector bench, wire only ch2 (GPIO23); for multi-channel high-RPM work,
consider a non-blocking RMT flat pulse instead of blocking P&H (as V4 did).

---

## STEP 3 — Common Rail pressure control (V5)

- Injectors ch2 (GPIO23) and ch3 (GPIO4) fire at `RPM/60 Hz` from an internal
  scheduler (no proximity needed).
- **PCV valve on GPIO18** via LEDC (default **1000 Hz**, 8-bit duty), driven by a
  PID loop at **100 Hz (every 10 ms)**.
- Pressure read from **GPIO14** every 10 ms, converted to bar via `PSCALE`.
- PID includes **output clamping (0–255)** and **conditional integral
  anti-windup** (integral only accumulates when not saturated in the same
  direction) — important so the valve recovers cleanly after a large step.
- Logs every 100 ms: `[PCV] target=<X>bar actual=<Y>bar duty=<Z>% rpm=<W>`.

**Pressure scaling** (`PSCALE <v0> <vmax> <pmax>`):
`bar = (V - v0)/(vmax - v0) * pmax`, clamped ≥ 0. Defaults 0.5 V→0 bar,
4.5 V→2000 bar. **Set this from your sensor datasheet before trusting readings.**
Also confirm the Vref jumper (5 V vs 12 V) and any LM358 divider ratio — the ESP32
ADC only tolerates 0–3.3 V, so a 0–5 V or 0–12 V sensor **must** be divided down.

---

## STEP 4 — Verification (procedure + expected values; not yet run)

I could not run these — they require the physical bench and a scope. Run each and
fill in the "measured" column.

### CAM mode — angle must stay constant (±0.5°) across RPM
Set `a10` (10°), `w1000`, `mode`→CAM, `start`. Spin at each RPM; measure the
GPIO26 HIGH→LOW width (= delay) and compute `angle = delay/period × 360`.

| RPM | Period (µs) | Expected delay @10° (µs) | Measured delay | Angle error |
|----:|------------:|-------------------------:|:--------------:|:-----------:|
| 200  | 300000 | 8333 |  |  |
| 500  | 120000 | 3333 |  |  |
| 1000 | 60000  | 1667 |  |  |
| 1500 | 40000  | 1111 |  |  |
| 2000 | 30000  | 833  |  |  |

Expected angle error with the esp_timer one-shot: **≤ ±0.1°** (timer + callback
latency of a few µs), comfortably inside ±0.5°.

### Common Rail — pressure must stabilize within 3 s
For each target, `TARGET_P <bar>`, `mode`→RAIL, `start`; time until `actual`
stays within ±2 % of target. Watch the `[PCV]` log.

| Target (bar) | Stabilization time (s) | Overshoot (bar) |
|-------------:|:----------------------:|:---------------:|
| 800  |  |  |
| 1000 |  |  |
| 1200 |  |  |
| 1500 |  |  |

If it oscillates: lower `Kp`. If it's sluggish / never reaches target: raise `Ki`
slightly. If it overshoots then rings: add a little `Kd`.

### Peak & Hold — peak = 175 µs ±2 µs on GPIO26
In RAIL mode the P&H driver marks GPIO26 around the pulse. The first flat-HIGH
segment before chopping starts is the peak phase — should read **175 µs**. Then
verify the hold chops at **10 kHz** (100 µs period). Expected accuracy from
`esp_rom_delay_us` with interrupts masked: **within ±1–2 µs**.

---

## Recommended settings

### PID starting points (rail pumps)
Start with the spec defaults and tune per the table above:

| Pump type | Kp | Ki | Kd | Note |
|---|---:|---:|---:|---|
| Default / unknown | 0.80 | 0.050 | 0.010 | spec default; safe start |
| Small CP (light valve) | 1.00 | 0.080 | 0.010 | faster, watch overshoot |
| Large CP4 / high-flow | 0.60 | 0.040 | 0.020 | gentler P, more D to damp |

Command: `PID 0.8 0.05 0.01`. Tune Kp first (fast approach, small steady ripple),
then Ki (kill steady-state error), then Kd (damp overshoot). Anti-windup is built
in, so large steps won't cause the integral to run away.

### SET_PH — Bosch vs Denso (10 kHz hold)
Format: `SET_PH <peak_us> <hold_on_us> <hold_off_us>`; period = on + off = 100 µs → 10 kHz.

| Injector | Coil R | Command | Hold current (approx) |
|---|---:|---|---|
| Bosch CRIN | ~0.5 Ω | `SET_PH 175 7 93` | ≈ 2.1 A |
| Denso CR | ~0.3 Ω | `SET_PH 175 5 95` | ≈ 1.8 A |

Peak stays 175 µs for both. Keep total pulse width within **100–5000 µs**
(`w<value>`); values outside are rejected by the fault gate.

---

## Serial command reference (V5)

Preserved: `start`, `stop`, `w<us>` (100–5000), `f<Hz>` (1–200), `a<deg>` (0–359),
`mode`, `SET_PH <peak> <on> <off>`.
New: `TARGET_P <bar>`, `PID <Kp> <Ki> <Kd>`, `PSCALE <v0> <vmax> <pmax>`,
`PCV_FREQ <hz>`, `STATUS`.

> **Format change to flag:** V4's `SET_PH` was `<peak> <period> <on>`; the V5 spec
> (and this build) use `<peak> <hold_on> <hold_off>`. If you reuse the old Python
> dashboard, update its `SET_PH` sender accordingly, or it will mis-configure the
> hold chop.

## Files delivered (`ESP32_CamBox_V5/`)
- `ESP32_CamBox_V5.ino` — main firmware (both modes, ISR, PID loop, serial)
- `injector_driver.h/.cpp` — multi-channel Peak & Hold (10 kHz), relay, debug pin
- `pid_control.h/.cpp` — PID with clamping + anti-windup
- `FIRMWARE_REPORT.md` — this file

## Open items before flashing
1. Confirm the physical board matches the V5 pin table (especially GPIO18 dual
   role as PCV/injector, and GPIO14 pressure).
2. Set `PSCALE` from your pressure-sensor datasheet and confirm the ADC divider
   keeps GPIO14 within 0–3.3 V.
3. Decide CAM-mode channel policy (single ch2 vs all three) given the blocking
   budget.
4. Run STEP 4 and record real numbers.
5. LCD (GPIO21/22) and keypad (GPIO36/39/34/35/32/33/25) are **not implemented**
   — this firmware is serial-driven. Say the word if you want them added.
