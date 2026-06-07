/**
 * injector_driver.h  —  CamBox Pro V4
 * Peak & Hold driver — MODE_COMMON_RAIL only.
 * EUI / EUP (CamBox flat-pulse RMT) path is NOT affected.
 *
 *  CHANGE: All constants removed — now live in config.h.
 *          Added g_hold_timer + init_hold_timer() for
 *          hardware-timer hold phase (target ±0.5 µs accuracy).
 *
 *  Waveform per pulse:
 *  ┌──── peak_us ────┐  soft 2×50%  ┌────── hold chop ──────┐
 *  │   100 % HIGH    │  transition  │  on_us / period_us    │ LOW
 */
#pragma once

#include <Arduino.h>
#include "driver/gpio.h"
#include "soc/gpio_struct.h"
#include "config.h"     // ← single source of all constants

// ── Pin aliases (gpio_num_t casts for IDF gpio_config calls) ─────────
#define INJECTOR_PIN    ((gpio_num_t)PIN_INJECTOR)
#define DEBUG_PIN       ((gpio_num_t)PIN_DEBUG)

// ── Runtime config struct (tunable via SET_PH serial command) ─────────
typedef struct {
    uint32_t peak_us;    // Peak phase duration (µs) — 100 % HIGH
    uint32_t period_us;  // Chop period (µs)
    uint32_t on_us;      // ON time per chop cycle (µs)
} peak_hold_config_t;

// ── Globals (defined in injector_driver.cpp) ──────────────────────────
extern peak_hold_config_t g_ph_config;
extern bool               g_use_peak_hold;   // false = RMT flat | true = P&H
extern hw_timer_t*        g_hold_timer;       // 1 MHz timer for hold phase

// ── API ───────────────────────────────────────────────────────────────
void init_debug_pin();                        // configure GPIO26 output
void init_hold_timer();                       // call once in setup()
void fire_common_rail(uint32_t total_pw_us);  // IRAM_ATTR on definition
