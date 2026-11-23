/**
 * injector_driver.h
 * Peak & Hold driver — MODE_COMMON_RAIL only.
 * EUI/EUP (CamBox / flat-pulse RMT) path is NOT affected.
 *
 *  Waveform per pulse:
 *  ┌─────peak_us──────┐  soft transition  ┌──── hold (chop) ────┐
 *  │   100 % HIGH     │  2 × 50 % cycles  │  on_us / period_us  │ LOW
 */
#pragma once

#include <Arduino.h>
#include "driver/gpio.h"
#include "soc/gpio_struct.h"

// ── Pins (must match PIN_INJECTOR in .ino) ───────────────────────────
#define INJECTOR_PIN      23              // RMT / GPIO injector output
#define DEBUG_PIN         GPIO_NUM_26     // oscilloscope trigger

// ── Safety limits & defaults ─────────────────────────────────────────
#define PH_PW_MIN_US     200UL            // absolute minimum total PW
#define PH_PW_MAX_US    5000UL            // fault threshold
#define PH_PEAK_US_DEF   175UL            // 175 µs flat peak phase
// ── Chop period — 10 kHz is safe for both brands ─────────────────────
//   25 kHz (40µs) caused current accumulation → coil overheating
//   10 kHz (100µs) allows proper current decay each cycle
#define PH_PERIOD_US_DEF  100UL           // 100 µs period → 10 kHz chop

// ── Hold ON time per brand (at period = 100µs) ────────────────────────
//   Bosch CRIN  (~0.5 Ω) : 7µs ON / 93µs OFF  → I ≈ 2.1A, P ≈ 2.1W ✅
//   Denso CR    (~0.3 Ω) : 5µs ON / 95µs OFF  → I ≈ 1.8A, P ≈ 0.9W ✅
//   Serial commands:
//     Bosch  → SET_PH 175 100 7
//     Denso  → SET_PH 175 100 5
#define PH_ON_US_BOSCH_DEF   7UL
#define PH_ON_US_DENSO_DEF   5UL
#define PH_ON_US_DEF  PH_ON_US_BOSCH_DEF   // startup default = Bosch

// ── Runtime config (tunable via SET_PH command) ──────────────────────
typedef struct {
    uint32_t peak_us;    // Peak phase duration (µs)  — flat 100 % HIGH
    uint32_t period_us;  // Chop period (µs)          — 40 µs @ 25 kHz
    uint32_t on_us;      // ON time per chop cycle    — 10 µs = 25 % duty
} peak_hold_config_t;

// ── Globals (defined in injector_driver.cpp) ─────────────────────────
extern peak_hold_config_t g_ph_config;
extern bool               g_use_peak_hold;  // false = RMT flat  |  true = P&H

// ── API ──────────────────────────────────────────────────────────────
void init_debug_pin();
void fire_common_rail(uint32_t total_pw_us);   // IRAM_ATTR on definition
