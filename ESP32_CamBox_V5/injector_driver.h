/**
 * injector_driver.h  —  CamBox Pro V5
 * ---------------------------------------------------------------------------
 * Multi-channel Peak & Hold driver for diesel solenoid injectors.
 *
 * Applies to all three injector channels:
 *     Coil1 / ch1  → GPIO18   (also PCV valve in Common-Rail mode)
 *     Coil2 / ch2  → GPIO23
 *     Coil3 / ch3  → GPIO4
 *
 * Waveform per pulse:
 *   ┌─────peak_us──────┐  soft transition  ┌──── hold (chop) ────┐
 *   │   100 % HIGH     │  2 × 50 % cycles  │  on_us / (on+off)   │ LOW
 *
 * CHOP RATE — INTENTIONALLY 10 kHz (100 µs period), NOT 25 kHz.
 *   The V4 bench proved 25 kHz (40 µs) accumulates coil current between
 *   cycles → the solenoid overheats. 10 kHz lets current decay each cycle.
 *   This is preserved on explicit instruction; do not "restore" 25 kHz.
 * ---------------------------------------------------------------------------
 */
#pragma once

#include <Arduino.h>
#include "driver/gpio.h"
#include "soc/gpio_struct.h"

// ── Injector output pins (V5 board) ──────────────────────────────────
#define INJ_PIN_CH1   18      // Coil1 (dual MOSFET) — PCV in Common-Rail mode
#define INJ_PIN_CH2   23      // Coil2 (single MOSFET)
#define INJ_PIN_CH3    4      // Coil3 (single MOSFET)
#define DEBUG_PIN     GPIO_NUM_26   // oscilloscope trigger (keypad8, free in test)

// ── 28 V boost relay (Peak phase supply) ─────────────────────────────
#define RELAY_PIN     19      // 12 V / 28 V switching

// ── Pulse-width safety window (total PW) ─────────────────────────────
#define PH_PW_MIN_US   100UL  // reject total PW below this
#define PH_PW_MAX_US  5000UL  // reject total PW above this (fault)

// ── Peak & Hold defaults ─────────────────────────────────────────────
//   Peak : 175 µs at full (28 V) voltage.
//   Hold : 10 kHz chop.  period = hold_on + hold_off.
//   Bosch CRIN (~0.5 Ω): 7 µs ON / 93 µs OFF  → I ≈ 2.1 A  (safe)
//   Denso CR   (~0.3 Ω): 5 µs ON / 95 µs OFF  → I ≈ 1.8 A  (safe)
#define PH_PEAK_US_DEF     175UL
#define PH_HOLD_ON_DEF       7UL   // Bosch startup default (10 kHz)
#define PH_HOLD_OFF_DEF     93UL   // 7 + 93 = 100 µs  → 10 kHz

// ── Runtime config — set via SET_PH <peak_us> <hold_on_us> <hold_off_us>
typedef struct {
    uint32_t peak_us;      // flat 100 % HIGH peak phase
    uint32_t hold_on_us;   // chop ON  time
    uint32_t hold_off_us;  // chop OFF time  (period = on + off)
} peak_hold_config_t;

extern peak_hold_config_t g_ph_config;

// ── API ──────────────────────────────────────────────────────────────
void injector_pins_init();                 // configure all 3 injector pins + debug + relay
void init_debug_pin();                      // GPIO26 push-pull output, start LOW
void relay_set(bool on);                    // 28 V boost relay for Peak phase

// Fire one channel with the full Peak & Hold waveform (blocking, IRAM).
// mark_debug=true toggles GPIO26 HIGH/LOW around the real pulse.
void fire_peak_hold(uint32_t pin, uint32_t total_pw_us, bool mark_debug);
