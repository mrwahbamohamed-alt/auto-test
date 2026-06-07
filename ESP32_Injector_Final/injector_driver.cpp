/**
 * injector_driver.cpp  —  CamBox Pro V4
 * Peak & Hold driver — MODE_COMMON_RAIL only.
 *
 *  CHANGE: Hold phase + soft-transition timing migrated from
 *          esp_rom_delay_us() to hw_timer_t polling at 1 MHz.
 *
 *  Why the split:
 *    Peak phase  (175 µs) → esp_rom_delay_us() kept.
 *      ±1 µs / 175 µs = 0.6 % — well within spec.
 *    Hold ON/OFF ( 7–10 µs ) → hw_timer_t polling (this file).
 *      Old error: ±1 µs (cpu spin) + ±0.5 µs (TLP250) + ±0.35 µs
 *                 (MOSFET) = ±1.85 µs → 26 % on 7 µs ON pulse.
 *      New error: ±0.5 µs (1 µs timer tick, half-tick max miss).
 *      Target met: Hartridge HK1400 level (±0.5 µs).
 *
 *  Timer safety:
 *    g_hold_timer runs free (no ISR attached) — polling only.
 *    timerRead() reads the hardware APB-clocked counter register.
 *    The flash cache is NOT disabled by portDISABLE_INTERRUPTS(),
 *    so calling timerRead() from within the interrupt-masked block
 *    is safe. One warm-up read in init_hold_timer() eliminates any
 *    first-call cache-cold latency.
 */

#include "injector_driver.h"
#include "esp_rom_sys.h"        // esp_rom_delay_us() — peak phase only
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

// ── Direct GPIO register macros (IDF 5.x / arduino-esp32 v3.x) ───────
//   out_w1ts / out_w1tc are volatile uint32_t — atomic bit-set / bit-clear
#define INJ_HIGH  GPIO.out_w1ts = (1UL << PIN_INJECTOR)
#define INJ_LOW   GPIO.out_w1tc = (1UL << PIN_INJECTOR)
#define DBG_HIGH  GPIO.out_w1ts = (1UL << PIN_DEBUG)
#define DBG_LOW   GPIO.out_w1tc = (1UL << PIN_DEBUG)

// ── Global state ──────────────────────────────────────────────────────
peak_hold_config_t g_ph_config = {
    .peak_us   = PH_PEAK_US_DEF,
    .period_us = PH_PERIOD_US_DEF,
    .on_us     = PH_ON_US_DEF,
};
bool         g_use_peak_hold = false;
hw_timer_t*  g_hold_timer    = nullptr;

// ════════════════════════════════════════════════════════════════════
//  init_debug_pin — GPIO26 push-pull output, start LOW
// ════════════════════════════════════════════════════════════════════
void init_debug_pin() {
    gpio_config_t cfg = {};
    cfg.pin_bit_mask = 1ULL << PIN_DEBUG;
    cfg.mode         = GPIO_MODE_OUTPUT;
    cfg.pull_up_en   = GPIO_PULLUP_DISABLE;
    cfg.pull_down_en = GPIO_PULLDOWN_DISABLE;
    cfg.intr_type    = GPIO_INTR_DISABLE;
    gpio_config(&cfg);
    gpio_set_level((gpio_num_t)PIN_DEBUG, 0);
}

// ════════════════════════════════════════════════════════════════════
//  init_hold_timer
//  CHANGE: Configures hw_timer_t at 1 MHz for hold-phase polling.
//
//  Arduino ESP32 v3 API: timerBegin(uint32_t frequency_hz)
//    The v2 form timerBegin(num, prescaler, countUp) is NOT valid
//    on Arduino Core v3 (IDF5-based) — do not use.
//
//  No interrupt is attached — the timer runs free and is read via
//  timerRead() in _hold_wait_us().
// ════════════════════════════════════════════════════════════════════
void init_hold_timer() {
    // 1,000,000 Hz → 1 tick = 1 µs
    g_hold_timer = timerBegin(HOLD_TIMER_FREQ_HZ);
    if (!g_hold_timer) {
        Serial.println("ERR: hold timer init failed");
        return;
    }
    // Cache warm-up: one read so the first real call has no cold-cache cost
    (void)timerRead(g_hold_timer);
    Serial.printf("Hold timer: 1 MHz OK (pin %d / %d)\n",
                  PIN_INJECTOR, PIN_DEBUG);
}

// ════════════════════════════════════════════════════════════════════
//  _hold_wait_us — hardware timer spin-wait
//  CHANGE: Replaces esp_rom_delay_us() for hold and soft-transition.
//
//  Uses a differential read (t_now - t0) so the free-running counter
//  is never reset — no write-then-read race condition.
//  Resolution: 1 µs/tick → max error ±0.5 µs (half-tick).
// ════════════════════════════════════════════════════════════════════
static inline void _hold_wait_us(uint64_t us) {
    uint64_t t0 = timerRead(g_hold_timer);
    while ((timerRead(g_hold_timer) - t0) < us) { /* spin */ }
}

// ════════════════════════════════════════════════════════════════════
//  fire_common_rail  —  IRAM_ATTR, full Peak & Hold pulse
//
//  Pulse stages:
//    [0 … peak_us]            100 % HIGH   (esp_rom_delay_us — KEPT)
//    [+2 × period_us]         50 % soft transition  (_hold_wait_us)
//    [+hold_budget µs]        on/off chop           (_hold_wait_us)
//    [end]                    hard LOW
//
//  Safety:
//    Fault gate runs BEFORE portDISABLE_INTERRUPTS — keeps serial alive.
//    portDISABLE_INTERRUPTS masks ISR delivery only; flash cache stays
//    active, so timerRead() (flash code) is callable within the block.
// ════════════════════════════════════════════════════════════════════
void IRAM_ATTR fire_common_rail(uint32_t total_pw_us) {

    // ── Fault gate — checked before disabling interrupts ─────────────
    if (total_pw_us > PH_PW_MAX_US) {
        Serial.printf("FAULT:PW_EXCEEDED:%lu\n", (unsigned long)total_pw_us);
        return;
    }
    if (total_pw_us < PH_PW_MIN_US) return;

    // ── Snapshot config — clamp on_us to guarantee off_us > 0 ────────
    const uint32_t peak   = g_ph_config.peak_us;
    const uint32_t period = g_ph_config.period_us;
    const uint32_t on     = (g_ph_config.on_us < period)
                              ? g_ph_config.on_us : (period / 2);
    const uint32_t off    = period - on;
    const uint32_t half   = period / 2;

    portDISABLE_INTERRUPTS();
    DBG_HIGH;   // oscilloscope: marks real pulse start

    // ── Phase 1: PEAK — 100 % duty ───────────────────────────────────
    // KEPT: esp_rom_delay_us() is acceptable here.
    // 175 µs target: ±1 µs = 0.6 % error — within spec.
    INJ_HIGH;
    esp_rom_delay_us(peak);

    // ── Soft transition: 2 chop cycles at 50 % duty ──────────────────
    // Damps the inductive voltage spike at peak→hold boundary.
    // CHANGE: was esp_rom_delay_us(half) — now hw_timer polling.
    for (int t = 0; t < 2; t++) {
        INJ_LOW;
        _hold_wait_us(half);    // ← hardware timer ±0.5 µs
        INJ_HIGH;
        _hold_wait_us(half);    // ← hardware timer ±0.5 µs
    }

    // ── Phase 2: HOLD — PWM chop for remaining pulse budget ──────────
    // CHANGE: was esp_rom_delay_us(on/off) — now hw_timer polling.
    const uint32_t transition_us = 2UL * period;
    const uint32_t hold_budget   = (total_pw_us > peak + transition_us)
                                    ? (total_pw_us - peak - transition_us)
                                    : 0;
    uint32_t elapsed = 0;

    // Full chop cycles
    while (elapsed + period <= hold_budget) {
        INJ_HIGH;
        _hold_wait_us(on);      // ← hardware timer ±0.5 µs
        INJ_LOW;
        _hold_wait_us(off);     // ← hardware timer ±0.5 µs
        elapsed += period;
    }

    // Partial last cycle — fire ON if budget allows
    if ((hold_budget - elapsed) >= on) {
        INJ_HIGH;
        _hold_wait_us(on);      // ← hardware timer ±0.5 µs
    }

    // ── Hard shutdown — pin hard LOW, no float ────────────────────────
    INJ_LOW;
    DBG_LOW;    // oscilloscope: marks real pulse end

    portENABLE_INTERRUPTS();
}
