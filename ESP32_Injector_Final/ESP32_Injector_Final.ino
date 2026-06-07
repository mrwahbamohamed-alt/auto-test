/**
 * ================================================================
 *  INJECTOR PRO — ESP32 Firmware  (Professional Industrial Build)
 *  Diesel Injection Test System
 * ================================================================
 *
 *  ARCHITECTURE:
 *  ┌─────────────────────────────────────────────────────────┐
 *  │  CAM ISR  (IRAM_ATTR, RISING)                          │
 *  │   Stage-1 debounce  → rejects EMI bursts  < 5 ms       │
 *  │   Stage-2 plausibility → rejects > 8000 RPM pulses     │
 *  │   Rolling RPM window  → median of last RPM_WINDOW gaps           │
 *  │   Sets s_cam_fired flag (main loop reads)               │
 *  └──────────────────────────┬──────────────────────────────┘
 *                             │ flag
 *                             ▼
 *  ┌─────────────────────────────────────────────────────────┐
 *  │  MAIN LOOP  (purely reactive — zero blocking)          │
 *  │  handle_serial()    read chars, parse on '\n'           │
 *  │  handle_custom()    micros() compare → fire             │
 *  │  handle_cambox()    flag + armed timer → fire           │
 *  │  update_pressure()  1 ADC sample / iteration            │
 *  │  send_telemetry()   every 10 ms                         │
 *  │  beep_update()      non-blocking buzzer                 │
 *  └──────────────────────────┬──────────────────────────────┘
 *                             │
 *                             ▼
 *  ┌─────────────────────────────────────────────────────────┐
 *  │  RMT TX  (hardware pulse — GPIO 23)                    │
 *  │  Resolution  1 µs/tick  (1 MHz clock)                  │
 *  │  Idle level  LOW  (automatic after pulse)               │
 *  │  Non-blocking — CPU free during pulse                   │
 *  └─────────────────────────────────────────────────────────┘
 *
 *  PIN MAP:
 *    GPIO 23  Injector output      (RMT TX — do NOT use digitalWrite)
 *    GPIO 4   Pressure sensor      (ADC,  0.5–4.5 V via divider)
 *    GPIO 16  Cam Proximity sensor (Interrupt RISING, INPUT_PULLUP)
 *    GPIO 2   Status LED
 *    GPIO 15  Buzzer               (active-HIGH, pull-down 10 kΩ)
 *
 *  SERIAL PROTOCOL @ 115200 baud:
 *    PC → ESP32:
 *      start          Start injection
 *      stop           Stop injection
 *      mode           Toggle Custom ↔ CamBox
 *      w<200-3000>    Pulse width (µs)
 *      f<1-100>       Frequency Hz  [Custom]
 *      a<0-45>        Delay angle ° [CamBox]
 *    ESP32 → PC:
 *      P:<bar>,A:<°>,R:<rpm>,I:<inj_count>,C:<cam_count>  @ 10 ms
 *
 * ================================================================
 */

#include "driver/rmt_tx.h"
#include "injector_driver.h"        // Peak & Hold — Common Rail

// ── Pins ─────────────────────────────────────────────────────────────
#define PIN_INJECTOR    23
#define PIN_PRESSURE     4
#define PIN_CAM         16
#define PIN_LED          2
#define PIN_BUZZER      15

// ── Pressure ADC ─────────────────────────────────────────────────────
//   ESP32 sends raw averaged VX4 mV — all calibration done in Python
#define P_SAMPLES  256              // rolling ADC window (256 samples ≈ max stability)

// ── Injection defaults ───────────────────────────────────────────────
#define DEF_PW_US       1000        // µs
#define DEF_DELAY_DEG      0        // degrees
#define DEF_FREQ_HZ       25        // Hz

// ── Timing ───────────────────────────────────────────────────────────
#define TELEMETRY_MS      10        // telemetry period
#define DEG_FULL        360.0f

// ── RMT hardware pulse ────────────────────────────────────────────────
#define RMT_RES_HZ   1000000UL      // 1 MHz → 1 µs per tick (max PW 32 ms)

// ── Cam debounce & plausibility ───────────────────────────────────────
// Stage-1 — electrical debounce (EMI bursts arrive µs apart)
#define CAM_DEBOUNCE_US     5000UL  // reject gaps < 5 ms (MOSFET/injector EMI)

// Stage-2 — physical plausibility (max test-bench RPM)
// At 8000 RPM: T_min = 60 000 000 / 8000 = 7 500 µs
#define CAM_MAX_RPM           8000
#define CAM_MIN_PERIOD_US  (60000000UL / CAM_MAX_RPM)  // 7 500 µs

// Stage-3 — rate-of-change ceiling, applied to SHORT gaps only (% of period)
//   Rejects a pulse whose gap is < period / (ratio) — i.e. a spurious extra
//   edge / EMI. Long gaps (deceleration, or a missed sensor pulse) are always
//   valid, so they pass; rejecting them made CamBox skip an injection when
//   the bench slowed down. 250 = reject gaps shorter than period / 2.5.
#define CAM_MAX_ROC_PCT      250UL

// ── RPM rolling average ──────────────────────────────────────────────
//   Lag ≈ RPM_WINDOW × period. 20 @ 1000 RPM (60 ms) ≈ 1.2 s — too slow to
//   track. 5 still rejects single-pulse spikes (median of 5) at ~4× faster
//   response. Stage 1/2/3 already filter EMI, so the window need not be large.
#define RPM_WINDOW            5     // median window
#define RPM_STALE_US    2000000UL   // declare 0 RPM after 2 s silence

// ════════════════════════════════════════════════════════════════════
//  RMT HANDLES
// ════════════════════════════════════════════════════════════════════
static rmt_channel_handle_t s_rmt_chan = NULL;
static rmt_encoder_handle_t s_rmt_enc  = NULL;

static rmt_transmit_config_t k_rmt_cfg;   // initialized in rmt_init()

// ════════════════════════════════════════════════════════════════════
//  CAM / RPM STATE  (written in ISR → volatile)
// ════════════════════════════════════════════════════════════════════
volatile unsigned long  s_cam_time_us  = 0;    // timestamp of last valid cam pulse
volatile unsigned long  s_last_cam_us  = 0;    // for period calculation
volatile unsigned long  s_rpm_period   = 0;    // most-recent period (µs)
volatile bool           s_cam_fired    = false; // consumed by handle_cambox()
volatile int            s_cam_telem    = 0;    // pulse count for telemetry

volatile unsigned long  s_rpm_win[RPM_WINDOW]; // circular period buffer
volatile int            s_rpm_wptr     = 0;
volatile int            s_rpm_wcnt     = 0;

// ════════════════════════════════════════════════════════════════════
//  INJECTION STATE
// ════════════════════════════════════════════════════════════════════
bool           s_running        = false;
int            s_pw_us          = DEF_PW_US;
int            s_delay_deg      = DEF_DELAY_DEG;
int            s_freq_hz        = DEF_FREQ_HZ;
int            s_mode           = 0;            // 0=Custom  1=CamBox

// CamBox armed shot
bool           s_armed          = false;
unsigned long  s_fire_at_us     = 0;

// Custom mode last-fire reference
unsigned long  s_last_fire_us   = 0;

// ════════════════════════════════════════════════════════════════════
//  TELEMETRY / SERIAL
// ════════════════════════════════════════════════════════════════════
unsigned long  s_telem_last     = 0;
String         s_serial_buf     = "";
int            s_inj_count      = 0;    // injections this telemetry period

// ════════════════════════════════════════════════════════════════════
//  PRESSURE  (background ADC — non-blocking)
// ════════════════════════════════════════════════════════════════════
float          s_pressure       = 0.0f;
long           s_adc_sum        = 0;
int            s_adc_cnt        = 0;

// ════════════════════════════════════════════════════════════════════
//  BUZZER  (non-blocking)
// ════════════════════════════════════════════════════════════════════
unsigned long  s_beep_end       = 0;

// ════════════════════════════════════════════════════════════════════
//  FORWARD DECLARATIONS
// ════════════════════════════════════════════════════════════════════
void rmt_init();
void fire_injector();
void handle_serial();
void process_command(const String& cmd);
void handle_custom();
void handle_cambox();
void update_pressure();
void send_telemetry();
void beep_start(int ms);
void beep_update();

// ════════════════════════════════════════════════════════════════════
//  FIRE INJECTOR  —  dispatches to P&H (Common Rail) or RMT (CamBox)
// ════════════════════════════════════════════════════════════════════
void fire_injector() {
    // ── Common-Rail Peak & Hold path ──────────────────────────────────
    if (g_use_peak_hold) {
        fire_common_rail((uint32_t)s_pw_us);
        s_inj_count++;
        return;
    }
    // ── Standard RMT flat-pulse path (CamBox / EUI / EUP) ─────────────
    static rmt_symbol_word_t sym;
    sym.level0    = 1;
    sym.duration0 = (uint16_t)s_pw_us;   // HIGH for s_pw_us µs
    sym.level1    = 0;
    sym.duration1 = 0;                    // end-marker → idle LOW

    rmt_transmit(s_rmt_chan, s_rmt_enc,
                 &sym, sizeof(sym), &k_rmt_cfg);
    s_inj_count++;
}

// ════════════════════════════════════════════════════════════════════
//  CAM ISR  —  IRAM, first-edge seed + three-stage filter
// ════════════════════════════════════════════════════════════════════
void IRAM_ATTR cambox_isr() {
    unsigned long now = micros();

    // ── First edge after start/reset — just seed the timestamp ───────
    //   s_last_cam_us == 0 means there is no previous edge yet. Computing
    //   a gap here would yield "micros() since boot" — a huge garbage
    //   period that poisons s_rpm_period and makes Stage-3 reject every
    //   real pulse afterwards. Seed and wait for the next edge.
    if (s_last_cam_us == 0) { s_last_cam_us = now; return; }

    unsigned long gap = now - s_last_cam_us;

    // ── Stage 1: electrical debounce ─────────────────────────────────
    //   Catches rapid EMI bursts from injector coil switching.
    if (gap < CAM_DEBOUNCE_US) return;

    // ── Stage 2: physical plausibility ───────────────────────────────
    //   If the implied RPM is above CAM_MAX_RPM the pulse is likely
    //   noise (e.g. 50 Hz mains coupling or ringing on the wire).
    if (gap < CAM_MIN_PERIOD_US) return;

    // ── Stage 3: rate-of-change — reject abnormally SHORT gaps only ───
    //   A spurious extra edge / EMI shows up as a gap much shorter than
    //   the running period. Long gaps (deceleration, or a genuinely
    //   missed sensor pulse) are physically valid and must pass, else
    //   CamBox skips an injection when the bench slows. On rejection,
    //   still advance s_last_cam_us so the next valid pulse is not
    //   measured across two periods (which would double the gap).
    if (s_rpm_period > 0 && gap < s_rpm_period) {
        unsigned long ratio = s_rpm_period * 100UL / gap;
        if (ratio > CAM_MAX_ROC_PCT) { s_last_cam_us = now; return; }
    }

    // ── Valid pulse — update state ────────────────────────────────────
    s_rpm_period  = gap;
    s_cam_time_us = now;
    s_last_cam_us = now;
    s_cam_fired   = true;
    s_cam_telem++;

    // Rolling RPM buffer (circular, newest first)
    s_rpm_win[s_rpm_wptr % RPM_WINDOW] = gap;
    s_rpm_wptr++;
    if (s_rpm_wcnt < RPM_WINDOW) s_rpm_wcnt++;
}

// ════════════════════════════════════════════════════════════════════
//  RMT INIT
// ════════════════════════════════════════════════════════════════════
void rmt_init() {
    // TX channel config
    rmt_tx_channel_config_t ch_cfg;
    memset(&ch_cfg, 0, sizeof(ch_cfg));
    ch_cfg.gpio_num          = (gpio_num_t)PIN_INJECTOR;
    ch_cfg.clk_src           = RMT_CLK_SRC_DEFAULT;
    ch_cfg.resolution_hz     = RMT_RES_HZ;
    ch_cfg.mem_block_symbols = 64;
    ch_cfg.trans_queue_depth = 4;

    esp_err_t err = rmt_new_tx_channel(&ch_cfg, &s_rmt_chan);
    if (err != ESP_OK) {
        Serial.printf("RMT channel error: %s\n", esp_err_to_name(err));
        return;
    }

    // Copy encoder
    rmt_copy_encoder_config_t enc_cfg;
    memset(&enc_cfg, 0, sizeof(enc_cfg));
    err = rmt_new_copy_encoder(&enc_cfg, &s_rmt_enc);
    if (err != ESP_OK) {
        Serial.printf("RMT encoder error: %s\n", esp_err_to_name(err));
        return;
    }

    err = rmt_enable(s_rmt_chan);
    if (err != ESP_OK) {
        Serial.printf("RMT enable error: %s\n", esp_err_to_name(err));
        return;
    }

    // Transmit config — eot_level=0 → pin goes LOW after pulse
    memset(&k_rmt_cfg, 0, sizeof(k_rmt_cfg));
    k_rmt_cfg.loop_count        = 0;
    k_rmt_cfg.flags.eot_level   = 0;
}

// ════════════════════════════════════════════════════════════════════
//  SETUP
// ════════════════════════════════════════════════════════════════════
void setup() {
    Serial.begin(115200);

    // RMT owns PIN_INJECTOR — do NOT call pinMode on it
    rmt_init();
    init_debug_pin();               // GPIO26 — oscilloscope trigger for P&H

    pinMode(PIN_LED,      OUTPUT);
    pinMode(PIN_BUZZER,   OUTPUT);
    pinMode(PIN_CAM,      INPUT_PULLUP);

    // GPIO4 (ADC2 CH0) — global attenuation + resolution for reliable reading
    analogReadResolution(12);
    analogSetAttenuation(ADC_11db);   // global: covers ADC2 pins unlike per-pin call
    pinMode(PIN_PRESSURE, INPUT);

    digitalWrite(PIN_LED,    LOW);
    digitalWrite(PIN_BUZZER, LOW);

    // CAM interrupt starts DETACHED — default mode is Custom (s_mode=0)
    // attachInterrupt is called only when user switches to CamBox mode

    Serial.println("INJECTOR PRO - Ready");
}

// ════════════════════════════════════════════════════════════════════
//  MAIN LOOP  —  zero blocking, all operations return immediately
// ════════════════════════════════════════════════════════════════════
void loop() {
    handle_serial();                   // 1. parse serial commands

    if (s_running) {                   // 2. injection logic
        if (s_mode == 0) handle_custom();
        else             handle_cambox();
    }

    update_pressure();                 // 3. one ADC sample

    unsigned long now_ms = millis();   // 4. telemetry
    if (now_ms - s_telem_last >= TELEMETRY_MS) {
        send_telemetry();
        s_telem_last += TELEMETRY_MS;   // += keeps interval precise (no drift)
    }

    beep_update();                     // 5. buzzer timeout
}

// ════════════════════════════════════════════════════════════════════
//  CUSTOM MODE  —  fixed-frequency injection
// ════════════════════════════════════════════════════════════════════
void handle_custom() {
    unsigned long now    = micros();
    unsigned long period = 1000000UL / (unsigned long)s_freq_hz;

    if ((now - s_last_fire_us) >= period) {
        s_last_fire_us = now;
        fire_injector();
    }
}

// ════════════════════════════════════════════════════════════════════
//  CAMBOX MODE  —  cam-synchronised injection with delay angle
//
//  Timing precision:
//    The main loop runs in ~5–15 µs (no blocking).
//    The armed-shot check fires within ±15 µs of the target.
//    At 3000 RPM (T = 20 ms), 15 µs ≡ ±0.27° — well within spec.
// ════════════════════════════════════════════════════════════════════
void handle_cambox() {
    // Consume cam event
    if (s_cam_fired) {
        s_cam_fired = false;

        unsigned long delay_us = 0;

        if (s_delay_deg > 0 && s_rpm_period > 0) {
            // Convert angle to time using the most-recent revolution period
            delay_us = (unsigned long)(
                ((float)s_delay_deg / DEG_FULL) * (float)s_rpm_period
            );
        }

        if (delay_us < 20UL) {
            // Negligible delay — fire immediately
            fire_injector();
        } else {
            // Arm the shot: fire at cam_time + delay
            s_fire_at_us = s_cam_time_us + delay_us;
            s_armed      = true;
        }
    }

    // Armed-shot check — runs every loop iteration (~5–15 µs)
    if (s_armed && (micros() >= s_fire_at_us)) {
        s_armed = false;
        fire_injector();
    }
}

// ════════════════════════════════════════════════════════════════════
//  BACKGROUND PRESSURE  —  1 ADC read per loop iteration (no delay)
// ════════════════════════════════════════════════════════════════════
void update_pressure() {
    s_adc_sum += analogReadMilliVolts(PIN_PRESSURE);
    s_adc_cnt++;

    if (s_adc_cnt >= P_SAMPLES) {
        // Send raw averaged VX4 mV — Python applies EMA + BAR formula
        s_pressure = (float)s_adc_sum / (float)s_adc_cnt;
        s_adc_sum  = 0;
        s_adc_cnt  = 0;
    }
}

// ════════════════════════════════════════════════════════════════════
//  TELEMETRY — sent every TELEMETRY_MS
//  Format: P:<bar>,A:<°>,R:<rpm>,I:<inj>,C:<cam>
// ════════════════════════════════════════════════════════════════════
void send_telemetry() {
    // RPM from rolling average of last N periods
    int rpm = 0;
    unsigned long cam_age = micros() - (unsigned long)s_last_cam_us;

    if (s_rpm_wcnt > 0 && cam_age < RPM_STALE_US) {
        noInterrupts();
        int           cnt = s_rpm_wcnt;
        unsigned long buf[RPM_WINDOW];
        for (int i = 0; i < cnt; i++) buf[i] = s_rpm_win[i];
        interrupts();

        // Insertion sort → median (robust to outlier noise periods)
        for (int i = 1; i < cnt; i++) {
            unsigned long k = buf[i]; int j = i - 1;
            while (j >= 0 && buf[j] > k) { buf[j + 1] = buf[j]; j--; }
            buf[j + 1] = k;
        }
        unsigned long median_period = buf[cnt / 2];
        if (median_period > 0) rpm = (int)(60000000UL / median_period);
    }

    // Atomically snapshot and reset counters
    noInterrupts();
    int inj       = s_inj_count;  s_inj_count = 0;
    int cam_pulses = s_cam_telem;  s_cam_telem = 0;
    interrupts();

    Serial.print("P:");  Serial.print(s_pressure, 1);
    Serial.print(",A:"); Serial.print(s_delay_deg);
    Serial.print(",R:"); Serial.print(rpm);
    Serial.print(",I:"); Serial.print(inj);
    Serial.print(",C:"); Serial.println(cam_pulses);
}

// ════════════════════════════════════════════════════════════════════
//  SERIAL HANDLER
// ════════════════════════════════════════════════════════════════════
void handle_serial() {
    while (Serial.available()) {
        char c = (char)Serial.read();
        if (c == '\n') {
            s_serial_buf.trim();
            if (s_serial_buf.length() > 0) process_command(s_serial_buf);
            s_serial_buf = "";
        } else if (c != '\r') {
            s_serial_buf += c;
        }
    }
}

void process_command(const String& cmd) {
    beep_start(40);   // short confirmation beep

    if (cmd == "start") {
        s_running      = true;
        s_armed        = false;
        s_last_fire_us = 0;
        // Clear cam/RPM state so each run starts clean — the first cam edge
        // re-seeds s_last_cam_us (see cambox_isr) instead of measuring a
        // stale gap left over from the previous run.
        noInterrupts();
        s_rpm_wcnt    = 0;
        s_rpm_wptr    = 0;
        s_rpm_period  = 0;
        s_cam_telem   = 0;
        s_cam_fired   = false;
        s_last_cam_us = 0;
        interrupts();
        digitalWrite(PIN_LED, HIGH);
        Serial.println("OK:START");

    } else if (cmd == "stop") {
        s_running = false;
        s_armed   = false;
        // RMT pin goes LOW automatically after the current pulse ends
        digitalWrite(PIN_LED, LOW);
        Serial.println("OK:STOP");

    } else if (cmd == "mode") {
        s_mode = (s_mode == 0) ? 1 : 0;
        s_armed        = false;
        s_cam_fired    = false;
        s_last_fire_us = 0;

        if (s_mode == 0) {
            // ── Custom: detach CAM interrupt, zero all RPM state ──────
            detachInterrupt(digitalPinToInterrupt(PIN_CAM));
            noInterrupts();
            s_rpm_wcnt    = 0;
            s_rpm_wptr    = 0;
            s_rpm_period  = 0;
            s_cam_telem   = 0;
            s_cam_fired   = false;
            s_last_cam_us = 0;
            interrupts();
        } else {
            // ── CamBox: re-attach CAM interrupt ───────────────────────
            attachInterrupt(digitalPinToInterrupt(PIN_CAM), cambox_isr, RISING);
        }

        Serial.print("OK:MODE:");
        Serial.println(s_mode == 0 ? "CUSTOM" : "CAMBOX");

    } else if (cmd.startsWith("w")) {
        int v = cmd.substring(1).toInt();
        if (v >= 200 && v <= 3000) {
            s_pw_us = v;
            Serial.print("OK:PW:"); Serial.println(s_pw_us);
        } else {
            Serial.println("ERR:PW_RANGE_200-3000");
        }

    } else if (cmd.startsWith("f")) {
        int v = cmd.substring(1).toInt();
        if (v >= 1 && v <= 100) {
            s_freq_hz = v;
            Serial.print("OK:FREQ:"); Serial.println(s_freq_hz);
        } else {
            Serial.println("ERR:FREQ_RANGE_1-100");
        }

    } else if (cmd.startsWith("a")) {
        int v = cmd.substring(1).toInt();
        if (v >= 0 && v <= 45) {
            s_delay_deg = v;
            Serial.print("OK:ANGLE:"); Serial.println(s_delay_deg);
        } else {
            Serial.println("ERR:ANGLE_RANGE_0-45");
        }

    } else if (cmd.startsWith("SET_PH ")) {
        // ── SET_PH <peak_us> <period_us> <on_us> ──────────────────────
        //    Example: SET_PH 175 40 10
        //    Enables Peak & Hold mode and updates runtime config.
        int sp1 = cmd.indexOf(' ', 7);
        int sp2 = (sp1 > 0) ? cmd.indexOf(' ', sp1 + 1) : -1;
        if (sp1 < 0 || sp2 < 0) {
            Serial.println("PH_CONFIG_ERR:BAD_FORMAT");
        } else {
            uint32_t p_us  = (uint32_t)cmd.substring(7,       sp1).toInt();
            uint32_t per   = (uint32_t)cmd.substring(sp1 + 1, sp2).toInt();
            uint32_t on_us = (uint32_t)cmd.substring(sp2 + 1).toInt();
            if (p_us  < 50   || p_us  > 2000 ||
                per   < 20   || per   > 500  ||
                on_us < 1    || on_us >= per) {
                Serial.println("PH_CONFIG_ERR:OUT_OF_RANGE");
            } else {
                g_ph_config.peak_us   = p_us;
                g_ph_config.period_us = per;
                g_ph_config.on_us     = on_us;
                g_use_peak_hold       = true;
                Serial.println("PH_CONFIG_OK");
            }
        }

    } else {
        Serial.print("ERR:UNKNOWN:"); Serial.println(cmd);
    }
}

// ════════════════════════════════════════════════════════════════════
//  BUZZER  —  non-blocking, duration-based
// ════════════════════════════════════════════════════════════════════
void beep_start(int ms) {
    digitalWrite(PIN_BUZZER, HIGH);
    s_beep_end = millis() + (unsigned long)ms;
}

void beep_update() {
    if (s_beep_end > 0 && millis() >= s_beep_end) {
        digitalWrite(PIN_BUZZER, LOW);
        s_beep_end = 0;
    }
}
