/**
 * ================================================================
 *  CamBox Pro V4  —  ESP32 Firmware  (Arduino Core v3 / IDF 5.x)
 *  Diesel Common Rail Injector Test System
 * ================================================================
 *
 *  CHANGES in V4:
 *    1. config.h  — all constants centralised (no more scattered #defines)
 *    2. Hold phase — hw_timer_t polling at 1 MHz (±0.5 µs vs ±2 µs before)
 *    3. Watchdog   — esp_task_wdt_config_t (IDF5 API) guards against stalls
 *    4. OTA        — ArduinoOTA WiFi update (non-blocking in loop)
 *
 *  ARCHITECTURE:
 *  ┌─────────────────────────────────────────────────────────┐
 *  │  CAM ISR  (IRAM_ATTR, RISING)                          │
 *  │   Stage-1 debounce  → rejects EMI bursts  < 5 ms       │
 *  │   Stage-2 plausibility → rejects > 8000 RPM pulses     │
 *  │   Rolling RPM window  → stores last 8 periods           │
 *  │   Sets s_cam_fired flag (main loop reads)               │
 *  └──────────────────────────┬──────────────────────────────┘
 *                             │ flag
 *                             ▼
 *  ┌─────────────────────────────────────────────────────────┐
 *  │  MAIN LOOP  (purely reactive — zero blocking)          │
 *  │  esp_task_wdt_reset()   watchdog kick (V4)              │
 *  │  ArduinoOTA.handle()    OTA check     (V4)              │
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
 *  │  RMT TX  (hardware pulse — GPIO 5)                     │
 *  │  Resolution  1 µs/tick  (1 MHz clock)                  │
 *  │  Idle level  LOW  (automatic after pulse)               │
 *  └─────────────────────────────────────────────────────────┘
 *
 *  PIN MAP:  (all defined in config.h)
 *    GPIO  5  Injector gate      (TLP250 → IRFP260N)
 *    GPIO  4  Pressure sensor    (ADC, 0.5–4.5 V via divider)
 *    GPIO 16  Cam proximity      (Interrupt RISING, INPUT_PULLUP)
 *    GPIO  2  Status LED
 *    GPIO 15  Buzzer             (active-HIGH, pull-down 10 kΩ)
 *    GPIO 26  Debug trigger      (oscilloscope — P&H pulse edges)
 *
 *  SERIAL PROTOCOL @ 115200 baud (unchanged from V3):
 *    PC → ESP32:
 *      start              Start injection
 *      stop               Stop injection
 *      mode               Toggle Custom ↔ CamBox
 *      w<200-3000>        Pulse width (µs)
 *      f<1-100>           Frequency Hz  [Custom mode]
 *      a<0-45>            Delay angle ° [CamBox mode]
 *      SET_PH <p> <T> <on>  Configure Peak & Hold
 *    ESP32 → PC:
 *      P:<mV>,A:<°>,R:<rpm>,I:<inj>,C:<cam>  @ 10 ms
 *
 * ================================================================
 */

#include "driver/rmt_tx.h"
#include "injector_driver.h"    // Peak & Hold — Common Rail (includes config.h)

// V4 additions
#include "esp_task_wdt.h"       // hardware task watchdog
#include <WiFi.h>               // OTA WiFi
#include <ArduinoOTA.h>         // OTA update handler

// ════════════════════════════════════════════════════════════════════
//  RMT HANDLES
// ════════════════════════════════════════════════════════════════════
static rmt_channel_handle_t s_rmt_chan = NULL;
static rmt_encoder_handle_t s_rmt_enc  = NULL;
static rmt_transmit_config_t k_rmt_cfg;

// ════════════════════════════════════════════════════════════════════
//  CAM / RPM STATE  (written in ISR → volatile)
// ════════════════════════════════════════════════════════════════════
volatile unsigned long  s_cam_time_us  = 0;
volatile unsigned long  s_last_cam_us  = 0;
volatile unsigned long  s_rpm_period   = 0;
volatile bool           s_cam_fired    = false;
volatile int            s_cam_telem    = 0;

volatile unsigned long  s_rpm_win[RPM_WINDOW];
volatile int            s_rpm_wptr     = 0;
volatile int            s_rpm_wcnt     = 0;

// ════════════════════════════════════════════════════════════════════
//  INJECTION STATE
// ════════════════════════════════════════════════════════════════════
bool           s_running        = false;
int            s_pw_us          = DEF_PW_US;
int            s_delay_deg      = DEF_DELAY_DEG;
int            s_freq_hz        = DEF_FREQ_HZ;
int            s_mode           = 0;          // 0=Custom  1=CamBox

bool           s_armed          = false;
unsigned long  s_fire_at_us     = 0;
unsigned long  s_last_fire_us   = 0;

// ════════════════════════════════════════════════════════════════════
//  TELEMETRY / SERIAL
// ════════════════════════════════════════════════════════════════════
unsigned long  s_telem_last     = 0;
String         s_serial_buf     = "";
int            s_inj_count      = 0;

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
void setup_watchdog();
void setup_wifi_ota();
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
//  FIRE INJECTOR  —  dispatches to P&H (Common Rail) or RMT
// ════════════════════════════════════════════════════════════════════
void fire_injector() {
    if (g_use_peak_hold) {
        fire_common_rail((uint32_t)s_pw_us);
        s_inj_count++;
        return;
    }
    static rmt_symbol_word_t sym;
    sym.level0    = 1;
    sym.duration0 = (uint16_t)s_pw_us;
    sym.level1    = 0;
    sym.duration1 = 0;
    rmt_transmit(s_rmt_chan, s_rmt_enc, &sym, sizeof(sym), &k_rmt_cfg);
    s_inj_count++;
}

// ════════════════════════════════════════════════════════════════════
//  CAM ISR  —  IRAM, three-stage debounce (unchanged from V3)
// ════════════════════════════════════════════════════════════════════
void IRAM_ATTR cambox_isr() {
    unsigned long now = micros();
    unsigned long gap = now - s_last_cam_us;

    // Stage 1: electrical debounce — rejects EMI bursts
    if (gap < CAM_DEBOUNCE_US) return;

    // Stage 2: physical plausibility — rejects implied RPM > CAM_MAX_RPM
    if (gap < CAM_MIN_PERIOD_US) return;

    // Stage 3: rate-of-change — rejects > 60 % period jumps
    if (s_rpm_period > 0) {
        unsigned long ratio = (gap > s_rpm_period)
                              ? (gap * 100UL / s_rpm_period)
                              : (s_rpm_period * 100UL / gap);
        if (ratio > 160UL) return;
    }

    s_rpm_period  = gap;
    s_cam_time_us = now;
    s_last_cam_us = now;
    s_cam_fired   = true;
    s_cam_telem++;

    s_rpm_win[s_rpm_wptr % RPM_WINDOW] = gap;
    s_rpm_wptr++;
    if (s_rpm_wcnt < RPM_WINDOW) s_rpm_wcnt++;
}

// ════════════════════════════════════════════════════════════════════
//  RMT INIT  (unchanged from V3 — uses PIN_INJECTOR from config.h)
// ════════════════════════════════════════════════════════════════════
void rmt_init() {
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

    memset(&k_rmt_cfg, 0, sizeof(k_rmt_cfg));
    k_rmt_cfg.loop_count       = 0;
    k_rmt_cfg.flags.eot_level  = 0;   // pin → LOW after pulse
}

// ════════════════════════════════════════════════════════════════════
//  SETUP WATCHDOG
//  CHANGE: New — IDF5 / Arduino ESP32 v3 task WDT API.
//
//  esp_task_wdt_config_t replaces the old esp_task_wdt_init(t, panic)
//  signature (IDF4 / Arduino v2). Do NOT use the old two-arg form.
//
//  esp_task_wdt_reconfigure() adjusts the already-running system WDT
//  (Arduino v3 enables it at boot). esp_task_wdt_add(NULL) enrolls
//  the current task. esp_task_wdt_reset() in loop() resets the timer.
// ════════════════════════════════════════════════════════════════════
void setup_watchdog() {
    esp_task_wdt_config_t wdt_cfg = {
        .timeout_ms     = (uint32_t)WDT_TIMEOUT_S * 1000U,
        .idle_core_mask = 0,     // do not watch idle tasks
        .trigger_panic  = true,  // panic + reboot on timeout
    };
    esp_err_t err = esp_task_wdt_reconfigure(&wdt_cfg);
    if (err != ESP_OK) {
        Serial.printf("WDT config err: %s\n", esp_err_to_name(err));
    }
    esp_task_wdt_add(NULL);     // enrol loop() task
    Serial.printf("WDT: %d s timeout OK\n", WDT_TIMEOUT_S);
}

// ════════════════════════════════════════════════════════════════════
//  SETUP WiFi + OTA
//  CHANGE: New — ArduinoOTA for remote firmware updates over WiFi.
//
//  Non-blocking design:
//    • WiFi connect attempt is bounded by WIFI_TIMEOUT_MS.
//    • If no AP found, returns silently — serial + injection continue.
//    • ArduinoOTA.handle() in loop() takes < 1 µs when idle.
//    • OTA onStart() stops injection first (safe state).
//
//  Flash via Arduino IDE:  Tools → Port → cambox-pro-v4 (network port)
//         PlatformIO:  pio run -t upload --upload-port <IP>
// ════════════════════════════════════════════════════════════════════
void setup_wifi_ota() {
    Serial.print("WiFi connecting");
    WiFi.begin(WIFI_SSID, WIFI_PASS);

    unsigned long t0 = millis();
    while (WiFi.status() != WL_CONNECTED &&
           (millis() - t0) < (unsigned long)WIFI_TIMEOUT_MS) {
        delay(200);
        Serial.print('.');
    }

    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("\nWiFi timeout — OTA disabled");
        return;
    }

    Serial.print("\nIP: ");
    Serial.println(WiFi.localIP());

    ArduinoOTA.setHostname(OTA_HOSTNAME);
    ArduinoOTA.setPassword(OTA_PASSWORD);

    ArduinoOTA.onStart([]() {
        // Stop injection before flashing — leave pins in safe LOW state
        s_running = false;
        s_armed   = false;
        INJ_LOW_OTA();   // macro defined below
        Serial.println("OTA:START");
    });
    ArduinoOTA.onEnd([]() {
        Serial.println("OTA:END");
    });
    ArduinoOTA.onProgress([](unsigned int done, unsigned int total) {
        Serial.printf("OTA %u%%\n", done * 100U / total);
    });
    ArduinoOTA.onError([](ota_error_t e) {
        Serial.printf("OTA ERR[%u]\n", (unsigned)e);
        // Errors don't restart here — let the WDT handle a hung OTA
    });

    ArduinoOTA.begin();
    Serial.printf("OTA ready: %s\n", OTA_HOSTNAME);
}

// Helper — force injector LOW from non-IRAM OTA callback
#define INJ_LOW_OTA()  GPIO.out_w1tc = (1UL << PIN_INJECTOR)

// ════════════════════════════════════════════════════════════════════
//  SETUP
// ════════════════════════════════════════════════════════════════════
void setup() {
    Serial.begin(115200);

    rmt_init();                  // RMT owns PIN_INJECTOR — no pinMode
    init_debug_pin();            // GPIO26 output (oscilloscope trigger)
    init_hold_timer();           // CHANGE: 1 MHz hw_timer for hold phase

    pinMode(PIN_LED,     OUTPUT);
    pinMode(PIN_BUZZER,  OUTPUT);
    pinMode(PIN_CAM,     INPUT_PULLUP);

    analogReadResolution(12);
    analogSetAttenuation(ADC_11db);
    pinMode(PIN_PRESSURE, INPUT);

    digitalWrite(PIN_LED,    LOW);
    digitalWrite(PIN_BUZZER, LOW);

    setup_watchdog();            // CHANGE: task WDT (5 s timeout, panic)
    setup_wifi_ota();            // CHANGE: WiFi + ArduinoOTA

    Serial.printf("INJECTOR PRO V%s - Ready\n", FW_VERSION);
}

// ════════════════════════════════════════════════════════════════════
//  MAIN LOOP  —  zero blocking, all operations return immediately
// ════════════════════════════════════════════════════════════════════
void loop() {
    esp_task_wdt_reset();           // CHANGE: kick watchdog every iteration

    ArduinoOTA.handle();            // CHANGE: OTA check (< 1 µs when idle)

    handle_serial();                // parse serial commands

    if (s_running) {
        if (s_mode == 0) handle_custom();
        else             handle_cambox();
    }

    update_pressure();

    unsigned long now_ms = millis();
    if (now_ms - s_telem_last >= TELEMETRY_MS) {
        send_telemetry();
        s_telem_last += TELEMETRY_MS;
    }

    beep_update();
}

// ════════════════════════════════════════════════════════════════════
//  CUSTOM MODE  —  fixed-frequency injection (unchanged)
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
//  At 3000 RPM (T=20 ms), ±15 µs loop latency ≡ ±0.27° — within spec.
// ════════════════════════════════════════════════════════════════════
void handle_cambox() {
    if (s_cam_fired) {
        s_cam_fired = false;
        unsigned long delay_us = 0;

        if (s_delay_deg > 0 && s_rpm_period > 0) {
            delay_us = (unsigned long)(
                ((float)s_delay_deg / DEG_FULL) * (float)s_rpm_period
            );
        }

        if (delay_us < 20UL) {
            fire_injector();
        } else {
            s_fire_at_us = s_cam_time_us + delay_us;
            s_armed      = true;
        }
    }

    if (s_armed && (micros() >= s_fire_at_us)) {
        s_armed = false;
        fire_injector();
    }
}

// ════════════════════════════════════════════════════════════════════
//  BACKGROUND PRESSURE  —  1 ADC read per loop iteration (unchanged)
// ════════════════════════════════════════════════════════════════════
void update_pressure() {
    s_adc_sum += analogReadMilliVolts(PIN_PRESSURE);
    s_adc_cnt++;
    if (s_adc_cnt >= P_SAMPLES) {
        s_pressure = (float)s_adc_sum / (float)s_adc_cnt;
        s_adc_sum  = 0;
        s_adc_cnt  = 0;
    }
}

// ════════════════════════════════════════════════════════════════════
//  TELEMETRY  (unchanged — format: P:<mV>,A:<°>,R:<rpm>,I:<inj>,C:<cam>)
// ════════════════════════════════════════════════════════════════════
void send_telemetry() {
    int rpm = 0;
    unsigned long cam_age = micros() - (unsigned long)s_last_cam_us;

    if (s_rpm_wcnt > 0 && cam_age < RPM_STALE_US) {
        noInterrupts();
        int           cnt = s_rpm_wcnt;
        unsigned long buf[RPM_WINDOW];
        for (int i = 0; i < cnt; i++) buf[i] = s_rpm_win[i];
        interrupts();

        for (int i = 1; i < cnt; i++) {
            unsigned long k = buf[i]; int j = i - 1;
            while (j >= 0 && buf[j] > k) { buf[j + 1] = buf[j]; j--; }
            buf[j + 1] = k;
        }
        unsigned long median_period = buf[cnt / 2];
        if (median_period > 0) rpm = (int)(60000000UL / median_period);
    }

    noInterrupts();
    int inj        = s_inj_count;  s_inj_count = 0;
    int cam_pulses = s_cam_telem;  s_cam_telem = 0;
    interrupts();

    Serial.print("P:");  Serial.print(s_pressure, 1);
    Serial.print(",A:"); Serial.print(s_delay_deg);
    Serial.print(",R:"); Serial.print(rpm);
    Serial.print(",I:"); Serial.print(inj);
    Serial.print(",C:"); Serial.println(cam_pulses);
}

// ════════════════════════════════════════════════════════════════════
//  SERIAL HANDLER  (unchanged — protocol preserved)
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
    beep_start(40);

    if (cmd == "start") {
        s_running      = true;
        s_armed        = false;
        s_last_fire_us = 0;
        digitalWrite(PIN_LED, HIGH);
        Serial.println("OK:START");

    } else if (cmd == "stop") {
        s_running = false;
        s_armed   = false;
        digitalWrite(PIN_LED, LOW);
        Serial.println("OK:STOP");

    } else if (cmd == "mode") {
        s_mode = (s_mode == 0) ? 1 : 0;
        s_armed        = false;
        s_cam_fired    = false;
        s_last_fire_us = 0;

        if (s_mode == 0) {
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
        // SET_PH <peak_us> <period_us> <on_us>
        // Example:  SET_PH 175 100 10   (Bosch)
        //           SET_PH 175 100 7    (Denso)
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
//  BUZZER  —  non-blocking, duration-based (unchanged)
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
