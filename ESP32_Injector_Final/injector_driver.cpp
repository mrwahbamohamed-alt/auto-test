/**
 * injector_driver.cpp  —  CamBox Pro (3-coil build)
 * Peak & Hold implementation for Coil1 (GPIO18), Coil2 (GPIO23), Coil3 (GPIO4).
 *
 * Timing : esp_rom_delay_us() — cycle-accurate, no RTOS overhead.
 * Safety : portDISABLE_INTERRUPTS() wraps the pulse so chop timing is exact.
 *          Fault gate rejects PW outside [PH_PW_MIN_US, PH_PW_MAX_US] BEFORE
 *          masking interrupts. Interrupts are re-enabled between coils, so a
 *          multi-coil shot is N separate masked windows, not one long one.
 *
 * Register writes target arduino-esp32 v3.x / IDF 5.x, where GPIO.out_w1ts /
 * out_w1tc are plain volatile uint32_t (no ".val" member). All coil pins
 * (18/23/4) and DEBUG_PIN (26) are < 32, so the low registers cover them.
 */

#include "injector_driver.h"
#include "esp_rom_sys.h"          // esp_rom_delay_us()
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

// ── Direct GPIO register macros (pin arg must be 0..31) ──────────────
#define PIN_HIGH(p)  (GPIO.out_w1ts = (1UL << (uint32_t)(p)))
#define PIN_LOW(p)   (GPIO.out_w1tc = (1UL << (uint32_t)(p)))
#define DBG_HIGH     (GPIO.out_w1ts = (1UL << (uint32_t)DEBUG_PIN))
#define DBG_LOW      (GPIO.out_w1tc = (1UL << (uint32_t)DEBUG_PIN))

// ── Index → GPIO map (index 0..2 == "COIL 1..3" on the wire) ─────────
const uint32_t COIL_PINS[NUM_COILS] = { COIL1_PIN, COIL2_PIN, COIL3_PIN };

// ── Runtime config (override with SET_PH) ────────────────────────────
peak_hold_config_t g_ph_config = {
    .peak_us     = PH_PEAK_US_DEF,
    .hold_on_us  = PH_HOLD_ON_DEF,
    .hold_off_us = PH_HOLD_OFF_DEF,
};

// ════════════════════════════════════════════════════════════════════
//  init_debug_pin — GPIO26 push-pull output, start LOW
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
//  coil_pins_init — all 3 coil pins push-pull output LOW + debug pin
//  (GPIO18 is later re-attached to LEDC when PID pressure mode starts.)
//  Every coil starts LOW: nothing fires on boot until the dashboard
//  enables a coil and sends start.
// ════════════════════════════════════════════════════════════════════
void coil_pins_init() {
    for (int i = 0; i < NUM_COILS; i++) {
        gpio_config_t cfg = {};
        cfg.pin_bit_mask = (1ULL << COIL_PINS[i]);
        cfg.mode         = GPIO_MODE_OUTPUT;
        cfg.pull_up_en   = GPIO_PULLUP_DISABLE;
        cfg.pull_down_en = GPIO_PULLDOWN_DISABLE;
        cfg.intr_type    = GPIO_INTR_DISABLE;
        gpio_config(&cfg);
        gpio_set_level((gpio_num_t)COIL_PINS[i], 0);
    }
    init_debug_pin();
}

// ════════════════════════════════════════════════════════════════════
//  fire_peak_hold_pin — full Peak & Hold pulse on one coil
//
//  Stages (counted from pulse start):
//    0 … peak_us                 → 100 % HIGH   (open valve/needle)
//    peak_us … +2×period         → 50 % duty    (soft transition)
//    +2×period … total_pw_us     → 10 kHz chop  (hold open)
//    total_pw_us                 → hard LOW      (shutdown)
// ════════════════════════════════════════════════════════════════════
void IRAM_ATTR fire_peak_hold_pin(uint32_t pin, uint32_t total_pw_us, bool mark_debug) {

    // ── Fault gate — before disabling interrupts ─────────────────────
    if (total_pw_us > PH_PW_MAX_US) {
        Serial.printf("FAULT:PW_EXCEEDED:%lu\n", (unsigned long)total_pw_us);
        return;
    }
    if (total_pw_us < PH_PW_MIN_US) return;

    // ── Snapshot config ──────────────────────────────────────────────
    const uint32_t peak   = g_ph_config.peak_us;
    const uint32_t on     = g_ph_config.hold_on_us;
    const uint32_t off    = g_ph_config.hold_off_us;
    const uint32_t period = on + off;
    const uint32_t half   = period / 2;

    if (period == 0) return;   // guard against a bad SET_PH

    portDISABLE_INTERRUPTS();

    if (mark_debug) DBG_HIGH;

    // ── Phase 1 : PEAK — 100 % duty for peak_us ──────────────────────
    PIN_HIGH(pin);
    esp_rom_delay_us(peak);

    // ── Soft transition : 2 chop cycles at 50 % duty ─────────────────
    for (int t = 0; t < 2; t++) {
        PIN_LOW(pin);
        esp_rom_delay_us(half);
        PIN_HIGH(pin);
        esp_rom_delay_us(half);
    }

    // ── Phase 2 : HOLD — 10 kHz chop for the remaining PW budget ─────
    const uint32_t transition_us = 2UL * period;
    const uint32_t hold_budget   = (total_pw_us > peak + transition_us)
                                    ? (total_pw_us - peak - transition_us)
                                    : 0;
    uint32_t elapsed = 0;
    while (elapsed + period <= hold_budget) {
        PIN_HIGH(pin);
        esp_rom_delay_us(on);
        PIN_LOW(pin);
        esp_rom_delay_us(off);
        elapsed += period;
    }
    if ((hold_budget - elapsed) >= on) {
        PIN_HIGH(pin);
        esp_rom_delay_us(on);
    }

    // ── Hard shutdown ────────────────────────────────────────────────
    PIN_LOW(pin);
    if (mark_debug) DBG_LOW;

    portENABLE_INTERRUPTS();
}
