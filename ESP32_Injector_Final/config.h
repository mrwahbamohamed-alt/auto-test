/**
 * config.h  —  CamBox Pro V4
 * ═══════════════════════════════════════════════════════════════════════
 *  CHANGE: New file — single source of truth for every constant.
 *          Previously scattered across injector_driver.h and the .ino.
 *          Edit here; all .cpp / .ino files pick up changes automatically.
 * ═══════════════════════════════════════════════════════════════════════
 */
#pragma once

// ── Firmware version ──────────────────────────────────────────────────
#define FW_VERSION          "4.0.0"

// ═════════════════════════════════════════════════════════════════════
//  GPIO PIN MAP
//  Hardware: TLP250 gate driver → IRFP260N MOSFET (200 V / 50 A)
// ═════════════════════════════════════════════════════════════════════
#define PIN_INJECTOR        23      // GPIO23 — TLP250 gate drive (P&H + RMT path)
#define PIN_DEBUG           26      // GPIO26 — oscilloscope trigger (debug only)
#define PIN_CAM             16      // GPIO16 — cam proximity sensor (RISING, INPUT_PULLUP)
#define PIN_PRESSURE         4      // GPIO4  — pressure sensor ADC (0.5–4.5 V via divider)
#define PIN_LED              2      // GPIO2  — status LED
#define PIN_BUZZER          15      // GPIO15 — buzzer (active-HIGH, 10 kΩ pull-down)

// ═════════════════════════════════════════════════════════════════════
//  PEAK & HOLD TIMING
//
//  Hardware propagation offsets (informational — absorbed in on_us trim):
//    TLP250 gate driver   propagation delay ≈ 0.5 µs
//    IRFP260N             rise / fall time  ≈ 0.35 µs
//    Total switching offset                ≈ 0.85 µs
//
//  Chop frequency: 10 kHz (100 µs period)
//    25 kHz was tried and caused current accumulation → coil overheating.
//    10 kHz allows proper inductive energy decay each cycle.
// ═════════════════════════════════════════════════════════════════════

// ── Peak phase (100 % duty — opens needle) ───────────────────────────
//  175 µs @ ±1 µs = 0.6 % error → acceptable; keep esp_rom_delay_us().
#define PH_PEAK_US_DEF      175UL   // µs

// ── Chop period ───────────────────────────────────────────────────────
#define PH_PERIOD_US_DEF    100UL   // µs  (1 / 10 kHz)

// ── Hold ON time per injector family (period = 100 µs) ───────────────
//  Bosch CRIN  (R ≈ 0.5 Ω) : 10 µs ON / 90 µs OFF → I_hold ≈ 2.1 A, P ≈ 2.2 W ✓
//  Denso CR    (R ≈ 0.3 Ω) :  7 µs ON / 93 µs OFF → I_hold ≈ 1.8 A, P ≈ 0.9 W ✓
//
//  Serial commands to set at runtime:
//    Bosch  →  SET_PH 175 100 10
//    Denso  →  SET_PH 175 100 7
#define PH_ON_US_BOSCH_DEF  10UL    // µs — Bosch (0.5 Ω)
#define PH_ON_US_DENSO_DEF   7UL    // µs — Denso  (0.3 Ω)
#define PH_ON_US_DEF        PH_ON_US_BOSCH_DEF   // startup default = Bosch

// ── Fault gate ────────────────────────────────────────────────────────
#define PH_PW_MIN_US        200UL   // µs — absolute minimum PW (below → ignore)
#define PH_PW_MAX_US       5000UL   // µs — maximum before FAULT rejection

// ═════════════════════════════════════════════════════════════════════
//  HOLD-PHASE HARDWARE TIMER
//
//  CHANGE: Replaces esp_rom_delay_us() in hold + soft-transition phases.
//  Timer:  hw_timer_t @ 1 MHz (1 µs / tick), polling mode, no ISR.
//
//  Arduino ESP32 v3 API: timerBegin(uint32_t freq_hz)
//    ← do NOT use old v2 form:  timerBegin(num, prescaler, countUp)
//
//  Why polling beats esp_rom_delay_us() for short intervals:
//    esp_rom_delay_us() uses a CPU spin loop → jitter from branch
//    prediction misses, cache misses, pipeline stalls → ±1–2 µs.
//    A hardware timer counter increments from the APB clock (80 MHz)
//    independent of CPU state → ±0.5 µs (1 tick resolution at 1 MHz).
// ═════════════════════════════════════════════════════════════════════
#define HOLD_TIMER_FREQ_HZ  1000000UL   // 1 MHz → 1 µs / tick

// ═════════════════════════════════════════════════════════════════════
//  CAM / RPM SIGNAL FILTERING
// ═════════════════════════════════════════════════════════════════════
//  Stage-1 debounce: rejects EMI bursts (MOSFET switching / injector)
#define CAM_DEBOUNCE_US     5000UL              // reject gaps < 5 ms

//  Stage-2 plausibility: max realistic bench RPM
#define CAM_MAX_RPM         8000                // pulses/min ceiling
#define CAM_MIN_PERIOD_US   (60000000UL / CAM_MAX_RPM)  // 7 500 µs

//  Stage-3 rate-of-change ceiling (period ratio, %).
//  160 (= 60 % jump) was too tight: manual deceleration grows the period
//  by > 60 % in a single revolution, so legitimate pulses were rejected
//  and the RPM glitched/halved when slowing down. 250 (= 2.5×) still
//  rejects EMI-scale anomalies (Stage 1/2 already catch short spikes).
#define CAM_MAX_ROC_PCT     250UL

//  RPM median filter
//  Window trades spike-rejection vs response lag: lag ≈ RPM_WINDOW × period.
//  20 samples @ 1000 RPM (60 ms period) ≈ 1.2 s lag — too slow to track.
//  5 samples still rejects single-pulse spikes (median of 5) with ~4× faster
//  response (≈ 0.3 s @ 1000 RPM).
#define RPM_WINDOW          5                   // circular buffer depth
#define RPM_STALE_US        2000000UL           // declare 0 RPM after 2 s

// ═════════════════════════════════════════════════════════════════════
//  INJECTION DEFAULTS
// ═════════════════════════════════════════════════════════════════════
#define DEF_PW_US           1000    // µs
#define DEF_DELAY_DEG          0    // °
#define DEF_FREQ_HZ           25    // Hz
#define DEG_FULL           360.0f

// ═════════════════════════════════════════════════════════════════════
//  TELEMETRY & ADC
// ═════════════════════════════════════════════════════════════════════
#define TELEMETRY_MS          10    // ms — send period
#define P_SAMPLES            256    // ADC rolling average window

// ═════════════════════════════════════════════════════════════════════
//  RMT  (flat-pulse path — CamBox / EUI / EUP injectors)
// ═════════════════════════════════════════════════════════════════════
#define RMT_RES_HZ          1000000UL   // 1 MHz → 1 µs/tick, max PW ≈ 32 ms

// ═════════════════════════════════════════════════════════════════════
//  HARDWARE WATCHDOG  (task WDT — IDF 5.x / Arduino ESP32 v3)
//
//  CHANGE: New — guards against loop() stalls (serial hang).
//  API: esp_task_wdt_config_t + esp_task_wdt_reconfigure() (IDF5 only).
//  Triggers panic → reboot if loop() does not call
//  esp_task_wdt_reset() within WDT_TIMEOUT_S seconds.
// ═════════════════════════════════════════════════════════════════════
#define WDT_TIMEOUT_S       5       // seconds
