/**
 * ============================================================================
 *  CamBox Pro V5 — ESP32 Diesel Injector Test System
 * ============================================================================
 *
 *  ⚠ HARDWARE STATUS: This firmware targets the NEW V5 board pin-out (below).
 *    It is written but has NOT been verified against physical hardware or an
 *    oscilloscope. Confirm the board is wired exactly as this table before
 *    flashing, and bench-verify per FIRMWARE_REPORT.md (STEP 4) before use.
 *
 *  ── VERIFIED PIN ASSIGNMENTS (V5 board) ──────────────────────────────────
 *    GPIO5   X4  Proximity sensor   (cam trigger — 1 pulse/rev, RISING)
 *    GPIO18  X5  Coil1 PWM          (dual MOSFET) — PCV valve in COMMON RAIL,
 *                                     injector ch1 in CAM mode
 *    GPIO23  X3  Coil2 PWM          (single MOSFET) — injector ch2
 *    GPIO4   X2  Coil3 PWM          (single MOSFET) — injector ch3
 *    GPIO19  X6  Relay              (12 V / 28 V switching — Peak supply)
 *    GPIO14  X1  Pressure sensor    (ADC — LM358 conditioned)
 *    GPIO21      LCD SDA            (not driven by this firmware yet)
 *    GPIO22      LCD SCL            (not driven by this firmware yet)
 *    GPIO15      Buzzer
 *    GPIO26      Debug timing pin   (oscilloscope; keypad8, free during test)
 *    GPIO36/39/34/35/32/33/25/26  Keypad (not driven by this firmware yet)
 *
 *  ── TIMING FLOW ──────────────────────────────────────────────────────────
 *    CAM mode:  proximityISR (GPIO5) → esp_timer one-shot (fire_delay_us) →
 *               coil_fire_cb → Peak & Hold on active injector channels.
 *               Angle→delay is RECOMPUTED every revolution from the measured
 *               period. GPIO26 = HIGH at ISR, LOW at fire (delay marker).
 *    RAIL mode: internal scheduler fires ch2/ch3 at RPM/60 Hz. PID loop
 *               (100 Hz) drives PCV duty on GPIO18 (LEDC, default 1 kHz) from
 *               the GPIO14 pressure feedback. GPIO26 marks each P&H pulse.
 *
 *  ── SERIAL @ 115200 ──────────────────────────────────────────────────────
 *    Preserved: start | stop | w<us> | f<Hz> | a<deg> | mode
 *               SET_PH <peak_us> <hold_on_us> <hold_off_us>
 *    New:       TARGET_P <bar> | PID <Kp> <Ki> <Kd>
 *               PSCALE <v0> <vmax> <pmax> | PCV_FREQ <hz> | STATUS
 *
 *  Peak & Hold chop rate is 10 kHz (see injector_driver.h) — intentionally
 *  NOT 25 kHz, to avoid the coil overheating proven on the V4 bench.
 * ============================================================================
 */

#include "esp_timer.h"
#include "injector_driver.h"
#include "pid_control.h"

// ── Pins ─────────────────────────────────────────────────────────────
#define PIN_PROX      5        // X4 proximity (cam trigger)
#define PIN_PCV       INJ_PIN_CH1   // GPIO18 — PCV in rail mode
#define PIN_INJ2      INJ_PIN_CH2   // GPIO23
#define PIN_INJ3      INJ_PIN_CH3   // GPIO4
#define PIN_PRESSURE  14       // X1 pressure ADC
#define PIN_BUZZER    15

// ── Modes ────────────────────────────────────────────────────────────
#define MODE_CAM   0
#define MODE_RAIL  1

// ── Defaults ─────────────────────────────────────────────────────────
#define DEF_PW_US     1000
#define DEF_ANGLE_DEG    0
#define DEF_FREQ_HZ     25
#define DEG_FULL     360.0f

// ── Cam filtering (ported from V4, proven) ───────────────────────────
#define CAM_DEBOUNCE_US   5000UL             // reject EMI bursts < 5 ms
#define CAM_MAX_RPM       8000
#define CAM_MIN_PERIOD_US (60000000UL / CAM_MAX_RPM)   // 7500 µs
#define RPM_WINDOW        5                  // median window
#define RPM_STALE_US      2000000UL

// ── PID / pressure ───────────────────────────────────────────────────
#define PID_DT_MS         10                 // 100 Hz
#define PCV_LOG_MS        100
#define TELEM_MS          10

// ════════════════════════════════════════════════════════════════════
//  STATE
// ════════════════════════════════════════════════════════════════════
volatile uint64_t s_last_trigger_us = 0;
volatile uint64_t s_period_us       = 0;     // most-recent revolution period
volatile uint64_t s_fire_delay_us   = 0;
volatile uint32_t s_rev_count       = 0;     // total valid revolutions
volatile bool     s_cam_seeded      = false;

volatile uint64_t s_rpm_win[RPM_WINDOW];
volatile int      s_rpm_wptr = 0;
volatile int      s_rpm_wcnt = 0;

bool     s_running   = false;
int      s_mode      = MODE_CAM;
int      s_pw_us     = DEF_PW_US;
int      s_angle_deg = DEF_ANGLE_DEG;
int      s_freq_hz   = DEF_FREQ_HZ;

// Rail-mode injector scheduler
uint64_t s_next_fire_us = 0;

// Rail-mode PCV / PID
float    s_target_bar  = 0.0f;
float    s_actual_bar  = 0.0f;
float    s_pcv_duty    = 0.0f;     // 0..255
int      s_pcv_freq    = 1000;     // Hz

// Pressure sensor scaling (PSCALE): voltage(V) → bar
float    s_p_v0   = 0.5f;          // volts at 0 bar
float    s_p_vmax = 4.5f;          // volts at max bar
float    s_p_pmax = 2000.0f;       // max bar

// Timing bookkeeping
uint32_t s_last_logged_rev = 0;
unsigned long s_pid_last_ms   = 0;
unsigned long s_pcvlog_last_ms= 0;
unsigned long s_telem_last_ms = 0;
unsigned long s_buzz_end_ms   = 0;

String   s_serial_buf = "";

esp_timer_handle_t s_coil_timer = NULL;

// ── Forward declarations ─────────────────────────────────────────────
void enter_mode(int m);
void fire_cam_shot();
void fire_rail_shot();
void handle_serial();
void process_command(const String& cmd);
void pid_tick();
void log_pcv();
void send_telemetry();
void beep_start(int ms);
void beep_update();
float read_pressure_bar();
int   current_rpm();

// ════════════════════════════════════════════════════════════════════
//  COIL TIMER CALLBACK  —  fires at cam_time + fire_delay_us
//  GPIO26 → LOW here marks the fire instant (delay = HIGH..LOW width).
// ════════════════════════════════════════════════════════════════════
void IRAM_ATTR coil_fire_cb(void* arg) {
    GPIO.out_w1tc = (1UL << (uint32_t)DEBUG_PIN);   // DBG LOW = fire instant
    fire_cam_shot();
}

// ════════════════════════════════════════════════════════════════════
//  PROXIMITY ISR  —  1 pulse/rev, recompute delay EVERY revolution
// ════════════════════════════════════════════════════════════════════
void IRAM_ATTR proximityISR() {
    uint64_t now = esp_timer_get_time();

    // First edge after (re)start — seed only, no gap yet.
    if (!s_cam_seeded) {
        s_last_trigger_us = now;
        s_cam_seeded = true;
        return;
    }

    uint64_t gap = now - s_last_trigger_us;

    // Stage 1: electrical debounce (EMI bursts arrive µs apart)
    if (gap < CAM_DEBOUNCE_US) return;
    // Stage 2: physical plausibility (> CAM_MAX_RPM ⇒ noise)
    if (gap < CAM_MIN_PERIOD_US) return;
    // Stage 3: adaptive half-period refractory (one edge per rev)
    if (s_period_us > 0 && gap < (s_period_us >> 1)) return;

    // Valid revolution.
    s_period_us       = gap;
    s_last_trigger_us = now;
    s_rev_count++;

    // Rolling median buffer for RPM display.
    s_rpm_win[s_rpm_wptr % RPM_WINDOW] = gap;
    s_rpm_wptr++;
    if (s_rpm_wcnt < RPM_WINDOW) s_rpm_wcnt++;

    if (!s_running || s_mode != MODE_CAM) return;

    // Angle → delay, recomputed from THIS revolution's period.
    s_fire_delay_us = (uint64_t)(((float)s_angle_deg / DEG_FULL) * (float)gap);

    // Debug pin HIGH at ISR; coil_fire_cb drops it LOW at the fire instant.
    GPIO.out_w1ts = (1UL << (uint32_t)DEBUG_PIN);

    // Always fire from the timer task (never block inside this ISR). A 0°
    // angle uses a 1 µs minimum so the pulse still runs in coil_fire_cb.
    esp_timer_stop(s_coil_timer);                 // cancel any pending shot
    uint64_t d = (s_fire_delay_us < 1) ? 1 : s_fire_delay_us;
    esp_timer_start_once(s_coil_timer, d);
}

// ════════════════════════════════════════════════════════════════════
//  FIRE — CAM shot: Peak & Hold on all active injector channels.
//  (Sequential/blocking. On a single-injector bench only ch2 is wired;
//   see FIRMWARE_REPORT.md for the high-RPM blocking-budget note.)
// ════════════════════════════════════════════════════════════════════
void fire_cam_shot() {
    // In CAM mode GPIO18 is a plain injector output (not PCV).
    fire_peak_hold(PIN_PCV,  (uint32_t)s_pw_us, false);
    fire_peak_hold(PIN_INJ2, (uint32_t)s_pw_us, false);
    fire_peak_hold(PIN_INJ3, (uint32_t)s_pw_us, false);
}

// ── RAIL shot: injectors ch2 & ch3 only (GPIO18 is PCV/LEDC here) ─────
void fire_rail_shot() {
    fire_peak_hold(PIN_INJ2, (uint32_t)s_pw_us, true);   // mark peak on scope
    fire_peak_hold(PIN_INJ3, (uint32_t)s_pw_us, false);
}

// ════════════════════════════════════════════════════════════════════
//  SETUP
// ════════════════════════════════════════════════════════════════════
void setup() {
    Serial.begin(115200);

    injector_pins_init();          // GPIO18/23/4 outputs + relay + debug pin
    pinMode(PIN_BUZZER, OUTPUT);
    digitalWrite(PIN_BUZZER, LOW);

    pinMode(PIN_PROX, INPUT_PULLUP);

    analogReadResolution(12);
    analogSetAttenuation(ADC_11db);
    pinMode(PIN_PRESSURE, INPUT);

    // One-shot esp_timer for the cam injection delay.
    esp_timer_create_args_t targs = {};
    targs.callback = &coil_fire_cb;
    targs.dispatch_method = ESP_TIMER_TASK;
    targs.name = "coil";
    esp_timer_create(&targs, &s_coil_timer);

    enter_mode(MODE_CAM);          // default mode

    Serial.println("CamBox Pro V5 - Ready");
}

// ════════════════════════════════════════════════════════════════════
//  MAIN LOOP
// ════════════════════════════════════════════════════════════════════
void loop() {
    handle_serial();

    unsigned long now_ms = millis();

    if (s_running && s_mode == MODE_RAIL) {
        // Fire injectors at RPM/60 Hz  (freq = s_freq_hz).
        uint64_t now_us = esp_timer_get_time();
        uint64_t period = 1000000ULL / (uint64_t)(s_freq_hz > 0 ? s_freq_hz : 1);
        if (now_us >= s_next_fire_us) {
            s_next_fire_us = now_us + period;
            fire_rail_shot();
        }
        // PID @ 100 Hz
        if (now_ms - s_pid_last_ms >= PID_DT_MS) {
            s_pid_last_ms = now_ms;
            pid_tick();
        }
        // PCV log @ 10 Hz
        if (now_ms - s_pcvlog_last_ms >= PCV_LOG_MS) {
            s_pcvlog_last_ms = now_ms;
            log_pcv();
        }
    }

    // CAM 10-revolution log
    if (s_running && s_mode == MODE_CAM) {
        uint32_t rc = s_rev_count;
        if (rc - s_last_logged_rev >= 10) {
            s_last_logged_rev = rc;
            Serial.printf("[CAM] RPM=%d angle=%ddeg delay=%luus pw=%dus\n",
                          current_rpm(), s_angle_deg,
                          (unsigned long)s_fire_delay_us, s_pw_us);
        }
    }

    // Compact telemetry for the dashboard (kept from V4 format)
    if (now_ms - s_telem_last_ms >= TELEM_MS) {
        s_telem_last_ms = now_ms;
        send_telemetry();
    }

    beep_update();
}

// ════════════════════════════════════════════════════════════════════
//  MODE MANAGEMENT — reconfigures GPIO18 between injector output and PCV
// ════════════════════════════════════════════════════════════════════
void enter_mode(int m) {
    // Leaving: always stop firing + detach prox + release LEDC on GPIO18.
    detachInterrupt(digitalPinToInterrupt(PIN_PROX));
    esp_timer_stop(s_coil_timer);
    ledcDetach(PIN_PCV);                 // no-op if not attached
    // Restore GPIO18 as a plain LOW output by default.
    pinMode(PIN_PCV, OUTPUT);
    digitalWrite(PIN_PCV, LOW);

    s_mode = m;

    // Reset cam state.
    noInterrupts();
    s_cam_seeded = false;
    s_period_us  = 0;
    s_rpm_wptr = 0; s_rpm_wcnt = 0;
    s_rev_count = 0; s_last_logged_rev = 0;
    interrupts();

    if (m == MODE_CAM) {
        relay_set(true);                 // 28 V available for Peak phase
        attachInterrupt(digitalPinToInterrupt(PIN_PROX), proximityISR, RISING);
    } else { // MODE_RAIL
        relay_set(true);
        // GPIO18 becomes the PCV PWM output.
        ledcAttach(PIN_PCV, s_pcv_freq, 8);   // 8-bit duty (0..255)
        ledcWrite(PIN_PCV, 0);
        pid_reset();
        s_next_fire_us = esp_timer_get_time();
    }
}

// ════════════════════════════════════════════════════════════════════
//  PID TICK — read pressure, compute duty, drive PCV
// ════════════════════════════════════════════════════════════════════
void pid_tick() {
    s_actual_bar = read_pressure_bar();
    float dt = PID_DT_MS / 1000.0f;
    s_pcv_duty = pid_compute(s_target_bar, s_actual_bar, dt);
    ledcWrite(PIN_PCV, (uint32_t)(s_pcv_duty + 0.5f));
}

float read_pressure_bar() {
    float mv = (float)analogReadMilliVolts(PIN_PRESSURE);
    float v  = mv / 1000.0f;
    float span = (s_p_vmax - s_p_v0);
    if (span <= 0.0001f) return 0.0f;
    float bar = (v - s_p_v0) / span * s_p_pmax;
    if (bar < 0) bar = 0;
    return bar;
}

int current_rpm() {
    if (s_rpm_wcnt == 0) return 0;
    uint64_t age = esp_timer_get_time() - s_last_trigger_us;
    if (age > RPM_STALE_US) return 0;

    noInterrupts();
    int cnt = s_rpm_wcnt;
    uint64_t buf[RPM_WINDOW];
    for (int i = 0; i < cnt; i++) buf[i] = s_rpm_win[i];
    interrupts();

    for (int i = 1; i < cnt; i++) {           // insertion sort → median
        uint64_t k = buf[i]; int j = i - 1;
        while (j >= 0 && buf[j] > k) { buf[j+1] = buf[j]; j--; }
        buf[j+1] = k;
    }
    uint64_t med = buf[cnt/2];
    return med ? (int)(60000000ULL / med) : 0;
}

// ════════════════════════════════════════════════════════════════════
//  LOGGING
// ════════════════════════════════════════════════════════════════════
void log_pcv() {
    Serial.printf("[PCV] target=%.0fbar actual=%.0fbar duty=%d%% rpm=%d\n",
                  s_target_bar, s_actual_bar,
                  (int)(s_pcv_duty / 255.0f * 100.0f + 0.5f),
                  s_freq_hz * 60);
}

void send_telemetry() {
    Serial.print("P:");  Serial.print(s_actual_bar, 1);
    Serial.print(",A:"); Serial.print(s_angle_deg);
    Serial.print(",R:"); Serial.print(current_rpm());
    Serial.print(",I:"); Serial.print(s_mode == MODE_RAIL ? s_freq_hz : 0);
    Serial.print(",C:"); Serial.println((int)s_rev_count);
}

// ════════════════════════════════════════════════════════════════════
//  SERIAL
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

static bool parse3(const String& s, int start, float& a, float& b, float& c) {
    int p1 = s.indexOf(' ', start);
    int p2 = (p1 > 0) ? s.indexOf(' ', p1 + 1) : -1;
    if (p1 < 0 || p2 < 0) return false;
    a = s.substring(start, p1).toFloat();
    b = s.substring(p1 + 1, p2).toFloat();
    c = s.substring(p2 + 1).toFloat();
    return true;
}

void process_command(const String& cmd) {
    beep_start(40);

    if (cmd == "start") {
        s_running = true;
        noInterrupts();
        s_cam_seeded = false; s_period_us = 0;
        s_rpm_wptr = 0; s_rpm_wcnt = 0;
        s_rev_count = 0; s_last_logged_rev = 0;
        interrupts();
        if (s_mode == MODE_RAIL) { pid_reset(); s_next_fire_us = esp_timer_get_time(); }
        Serial.println("OK:START");

    } else if (cmd == "stop") {
        s_running = false;
        esp_timer_stop(s_coil_timer);
        if (s_mode == MODE_RAIL) ledcWrite(PIN_PCV, 0);
        Serial.println("OK:STOP");

    } else if (cmd == "mode") {
        s_running = false;
        enter_mode(s_mode == MODE_CAM ? MODE_RAIL : MODE_CAM);
        Serial.print("OK:MODE:");
        Serial.println(s_mode == MODE_CAM ? "CAM" : "COMMON_RAIL");

    } else if (cmd.startsWith("w")) {
        int v = cmd.substring(1).toInt();
        if (v >= (int)PH_PW_MIN_US && v <= (int)PH_PW_MAX_US) {
            s_pw_us = v; Serial.print("OK:PW:"); Serial.println(s_pw_us);
        } else Serial.println("ERR:PW_RANGE_100-5000");

    } else if (cmd.startsWith("f")) {
        int v = cmd.substring(1).toInt();
        if (v >= 1 && v <= 200) {
            s_freq_hz = v; Serial.print("OK:FREQ:"); Serial.println(s_freq_hz);
        } else Serial.println("ERR:FREQ_RANGE_1-200");

    } else if (cmd.startsWith("a")) {
        int v = cmd.substring(1).toInt();
        if (v >= 0 && v <= 359) {
            s_angle_deg = v; Serial.print("OK:ANGLE:"); Serial.println(s_angle_deg);
        } else Serial.println("ERR:ANGLE_RANGE_0-359");

    } else if (cmd.startsWith("SET_PH")) {
        float p, on, off;
        if (!parse3(cmd, 7, p, on, off)) { Serial.println("PH_CONFIG_ERR:BAD_FORMAT"); return; }
        uint32_t total = (uint32_t)p + (uint32_t)on;   // min plausible pulse
        if (p < 50 || p > 2000 || on < 1 || off < 1 || (on + off) > 500 ||
            total < PH_PW_MIN_US) {
            Serial.println("PH_CONFIG_ERR:OUT_OF_RANGE");
        } else {
            g_ph_config.peak_us     = (uint32_t)p;
            g_ph_config.hold_on_us  = (uint32_t)on;
            g_ph_config.hold_off_us = (uint32_t)off;
            Serial.println("PH_CONFIG_OK");
        }

    } else if (cmd.startsWith("TARGET_P")) {
        float v = cmd.substring(8).toFloat();
        if (v >= 0 && v <= 3000) {
            s_target_bar = v; Serial.print("OK:TARGET_P:"); Serial.println(s_target_bar, 0);
        } else Serial.println("ERR:TARGET_P_RANGE_0-3000");

    } else if (cmd.startsWith("PID")) {
        float kp, ki, kd;
        if (!parse3(cmd, 4, kp, ki, kd)) { Serial.println("ERR:PID_BAD_FORMAT"); return; }
        pid_set_gains(kp, ki, kd);
        Serial.printf("OK:PID:Kp=%.4f Ki=%.4f Kd=%.4f\n", kp, ki, kd);

    } else if (cmd.startsWith("PSCALE")) {
        float v0, vmax, pmax;
        if (!parse3(cmd, 7, v0, vmax, pmax)) { Serial.println("ERR:PSCALE_BAD_FORMAT"); return; }
        if (vmax <= v0 || pmax <= 0) { Serial.println("ERR:PSCALE_INVALID"); return; }
        s_p_v0 = v0; s_p_vmax = vmax; s_p_pmax = pmax;
        Serial.printf("OK:PSCALE:v0=%.3f vmax=%.3f pmax=%.0f\n", v0, vmax, pmax);

    } else if (cmd.startsWith("PCV_FREQ")) {
        int v = cmd.substring(8).toInt();
        if (v >= 100 && v <= 20000) {
            s_pcv_freq = v;
            if (s_mode == MODE_RAIL) { ledcDetach(PIN_PCV); ledcAttach(PIN_PCV, s_pcv_freq, 8); }
            Serial.print("OK:PCV_FREQ:"); Serial.println(s_pcv_freq);
        } else Serial.println("ERR:PCV_FREQ_RANGE_100-20000");

    } else if (cmd == "STATUS") {
        Serial.println("── STATUS ──────────────────────────────");
        Serial.printf("mode      : %s\n", s_mode == MODE_CAM ? "CAM" : "COMMON_RAIL");
        Serial.printf("running   : %s\n", s_running ? "yes" : "no");
        Serial.printf("pulse_us  : %d\n", s_pw_us);
        Serial.printf("angle_deg : %d\n", s_angle_deg);
        Serial.printf("freq_hz   : %d  (rpm=%d)\n", s_freq_hz, s_freq_hz * 60);
        Serial.printf("rpm_meas  : %d\n", current_rpm());
        Serial.printf("P&H       : peak=%luus on=%luus off=%luus (%.1fkHz)\n",
                      (unsigned long)g_ph_config.peak_us,
                      (unsigned long)g_ph_config.hold_on_us,
                      (unsigned long)g_ph_config.hold_off_us,
                      1000.0f / (g_ph_config.hold_on_us + g_ph_config.hold_off_us));
        Serial.printf("target_bar: %.0f\n", s_target_bar);
        Serial.printf("actual_bar: %.1f\n", s_actual_bar);
        Serial.printf("pcv_duty  : %.0f/255  freq=%dHz\n", s_pcv_duty, s_pcv_freq);
        Serial.printf("PID       : Kp=%.4f Ki=%.4f Kd=%.4f\n", g_pid.Kp, g_pid.Ki, g_pid.Kd);
        Serial.printf("PSCALE    : v0=%.3f vmax=%.3f pmax=%.0f\n", s_p_v0, s_p_vmax, s_p_pmax);
        Serial.println("────────────────────────────────────────");

    } else {
        Serial.print("ERR:UNKNOWN:"); Serial.println(cmd);
    }
}

// ════════════════════════════════════════════════════════════════════
//  BUZZER — non-blocking
// ════════════════════════════════════════════════════════════════════
void beep_start(int ms) {
    digitalWrite(PIN_BUZZER, HIGH);
    s_buzz_end_ms = millis() + (unsigned long)ms;
}
void beep_update() {
    if (s_buzz_end_ms > 0 && millis() >= s_buzz_end_ms) {
        digitalWrite(PIN_BUZZER, LOW);
        s_buzz_end_ms = 0;
    }
}
