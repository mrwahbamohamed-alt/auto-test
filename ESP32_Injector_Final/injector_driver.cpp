/**
 * injector_driver.cpp
 * Peak & Hold driver implementation — MODE_COMMON_RAIL only.
 *
 *  Waveform per pulse:
 *  ┌─────peak_us──────┐  soft transition  ┌──── hold (chop) ────┐
 *  │   100 % HIGH     │  2 × 50 % cycles  │  on_us / period_us  │ LOW
 *
 *  Timing : esp_rom_delay_us() — cycle-accurate, no RTOS overhead.
 *  Safety : portDISABLE_INTERRUPTS() wraps the entire pulse.
 *           Fault gate rejects PW > PH_PW_MAX_US before blocking.
 */

#include "injector_driver.h"
#include "esp_rom_sys.h"        // esp_rom_delay_us()
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

// ── Direct GPIO register macros (IDF 5.x / arduino-esp32 v3.x) ───────
//   out_w1ts / out_w1tc are plain volatile uint32_t — no .val member
#define INJ_HIGH  GPIO.out_w1ts = (1UL << INJECTOR_PIN)
#define INJ_LOW   GPIO.out_w1tc = (1UL << INJECTOR_PIN)
#define DBG_HIGH  GPIO.out_w1ts = (1UL << (uint32_t)DEBUG_PIN)
#define DBG_LOW   GPIO.out_w1tc = (1UL << (uint32_t)DEBUG_PIN)

// ── Runtime config (default values, override with SET_PH) ─────────────
peak_hold_config_t g_ph_config = {
    .peak_us   = PH_PEAK_US_DEF,
    .period_us = PH_PERIOD_US_DEF,
    .on_us     = PH_ON_US_DEF,
};

bool g_use_peak_hold = false;

// ════════════════════════════════════════════════════════════════════
//  init_debug_pin — configure GPIO26 as push-pull output, start LOW
// ════════════════════════════════════════════════════════════════════
void init_debug_pin() {
    gpio_config_t cfg = {};
    cfg.pin_bit_mask = (1ULL << (uint32_t)DEBUG_PIN);
    cfg.mode         = GPIO_MODE_OUTPUT;
    cfg.pull_up_en   = GPIO_PULLUP_DISABLE;
    cfg.pull_down_en = GPIO_PULLDOWN_DISABLE;
    cfg.intr_type    = GPIO_INTR_DISABLE;
    gpio_config(&cfg);
    gpio_set_level(DEBUG_PIN, 0);
}

// ════════════════════════════════════════════════════════════════════
//  fire_common_rail  —  IRAM_ATTR, full Peak & Hold pulse
//
//  Stages (timing counted from pulse start):
//    0 … peak_us                → 100 % HIGH  (open needle)
//    peak_us … +2×period        → 50 % duty   (soft transition)
//    +2×period … total_pw_us    → on/off chop  (hold open)
//    total_pw_us                → hard LOW     (shutdown)
// ════════════════════════════════════════════════════════════════════
void IRAM_ATTR fire_common_rail(uint32_t total_pw_us) {

    // ── Fault gate — checked BEFORE disabling interrupts ─────────────
    if (total_pw_us > PH_PW_MAX_US) {
        Serial.printf("FAULT:PW_EXCEEDED:%lu\n", (unsigned long)total_pw_us);
        return;
    }
    if (total_pw_us < PH_PW_MIN_US) return;

    // ── Snapshot config — clamp on_us to keep off_us > 0 ─────────────
    const uint32_t peak   = g_ph_config.peak_us;
    const uint32_t period = g_ph_config.period_us;
    const uint32_t on     = (g_ph_config.on_us < period)
                              ? g_ph_config.on_us
                              : (period / 2);
    const uint32_t off    = period - on;
    const uint32_t half   = period / 2;

    portDISABLE_INTERRUPTS();

    // ── Debug pin HIGH (oscilloscope: marks real pulse start) ─────────
    DBG_HIGH;

    // ── Phase 1 : PEAK — 100 % duty for peak_us ──────────────────────
    INJ_HIGH;
    esp_rom_delay_us(peak);

    // ── Soft transition : 2 chop cycles at 50 % duty ─────────────────
    //    Damps inductive voltage spike at peak → hold boundary.
    for (int t = 0; t < 2; t++) {
        INJ_LOW;
        esp_rom_delay_us(half);
        INJ_HIGH;
        esp_rom_delay_us(half);
    }

    // ── Phase 2 : HOLD — PWM chopping for remaining PW budget ────────
    const uint32_t transition_us = 2UL * period;
    const uint32_t hold_budget   = (total_pw_us > peak + transition_us)
                                    ? (total_pw_us - peak - transition_us)
                                    : 0;
    uint32_t elapsed = 0;

    // Full chop cycles
    while (elapsed + period <= hold_budget) {
        INJ_HIGH;
        esp_rom_delay_us(on);
        INJ_LOW;
        esp_rom_delay_us(off);
        elapsed += period;
    }

    // Partial last cycle — fire one ON pulse if budget allows
    if ((hold_budget - elapsed) >= on) {
        INJ_HIGH;
        esp_rom_delay_us(on);
    }

    // ── Hard shutdown — pin hard LOW, no float ────────────────────────
    INJ_LOW;

    // ── Debug pin LOW (oscilloscope: marks real pulse end) ────────────
    DBG_LOW;

    portENABLE_INTERRUPTS();
}
