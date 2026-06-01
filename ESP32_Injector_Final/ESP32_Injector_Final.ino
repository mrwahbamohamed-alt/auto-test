// ============================================================
//  INJECTOR PRO - ESP32 Firmware FINAL
//  Single Injector | Pressure Sensor | CamBox Sync | Custom Freq
// ============================================================
//
//  PIN CONNECTIONS:
//  -----------------------------------------------
//  Injector Output    --> GPIO 23
//  Pressure Sensor    --> GPIO 4 (Analog 0.5V-4.5V)
//  CamBox Sync Input  --> GPIO 16 (Interrupt, RISING)
//  Status LED         --> GPIO 2  (Built-in)
//  Buzzer             --> GPIO 15 (pull-down 10kΩ to GND)
//  -----------------------------------------------
//
//  PRESSURE SENSOR SPECS:
//  0 BAR   = 1.0V
//  1600 BAR = 4.5V
//
//  MODES:
//  0 = Custom Mode  : حقن بتردد ثابت (Hz) مستقل عن الكام
//  1 = CamBox Mode  : حقن مزامن مع إشارة الكام + delay angle
//
//  SERIAL PROTOCOL (115200 baud):
//  PC --> ESP32:
//    start\n      = تشغيل
//    stop\n       = إيقاف
//    mode\n       = تبديل بين Custom و CamBox
//    w<val>\n     = Pulse Width بالميكروثانية (200-3000)
//    f<val>\n     = Frequency بالـ Hz (1-100)  [Custom Mode]
//    a<val>\n     = Delay Angle بالدرجات (0-45) [CamBox Mode]
//
//  ESP32 --> PC:
//    P:<pressure>,A:<angle>,R:<rpm>,I:<inj_count>,C:<cam_count>\n  كل 5ms
// ============================================================

// ---- PINS ----
#define INJECTOR_PIN      23
#define PRESSURE_PIN      4
#define CAMBOX_PIN        16
#define STATUS_LED_PIN    2
#define BUZZER_PIN        15

// ---- PRESSURE SENSOR CALIBRATION ----
#define PRESSURE_V_MIN    1.0f      // فولت عند 0 BAR
#define PRESSURE_V_MAX    4.5f      // فولت عند 1600 BAR
#define PRESSURE_BAR_MAX  1600.0f   // أقصى ضغط
#define PRESSURE_SAMPLES  32        // أكتر عينات = أنعم (non-blocking فمفيش مشكلة)
#define RPM_EMA_ALPHA     0.15f     // فلتر RPM — 0=لا تغيير, 1=بدون فلتر

// ---- DEFAULTS ----
#define DEFAULT_PW_US     1000      // Pulse Width افتراضي
#define DEFAULT_DELAY_DEG 0         // Delay Angle افتراضي
#define DEFAULT_FREQ_HZ   25        // تردد افتراضي للـ Custom Mode

// ---- TIMING ----
#define TELEMETRY_MS      5         // إرسال Telemetry كل 5ms (200Hz)
#define DEG_PER_REV       360.0f    // درجات اللفة الكاملة
#define CAM_DEBOUNCE_US   5000UL    // 5ms debounce — يتجاهل النويز حتى 6000 RPM

// ============================================================
//  GLOBALS
// ============================================================
volatile unsigned long  cam_pulse_time_us  = 0;   // وقت آخر إشارة كام
volatile bool           cam_fired          = false;
volatile unsigned long  last_cam_us        = 0;
volatile unsigned long  rpm_period_us      = 0;   // الفترة بين إشارتين كام

bool           is_running      = false;
int            pulse_width_us  = DEFAULT_PW_US;
int            delay_angle_deg = DEFAULT_DELAY_DEG;
int            freq_hz         = DEFAULT_FREQ_HZ;
int            active_mode     = 0;      // 0=Custom, 1=CamBox
bool           injector_armed  = false;  // هل تم تسليح الحقنة بعد الكام؟
unsigned long  fire_at_us      = 0;      // الوقت المحسوب للإطلاق
unsigned long  last_custom_fire_us = 0;  // آخر إطلاق في Custom Mode

unsigned long  last_telemetry  = 0;
String         serial_buffer   = "";

unsigned long  beep_end_ms          = 0;
int            injector_pulse_count = 0;
volatile int   cambox_pulse_count   = 0;

// قراءة الضغط في الـ Background — نبضة ADC واحدة per loop بدون blocking
float          g_pressure_bar = 0.0f;
long           g_adc_sum      = 0;
int            g_adc_count    = 0;

// RPM مفلتر
float          g_rpm_ema      = 0.0f;
volatile bool  g_new_cam_rpm  = false;  // flag لما تيجي نبضة كام جديدة

// ============================================================
//  INTERRUPT - CamBox Pulse (RISING EDGE
// ============================================================
void IRAM_ATTR cambox_isr() {
  unsigned long now = micros();
  if (now - last_cam_us < CAM_DEBOUNCE_US) return;  // تجاهل النويز
  rpm_period_us     = now - last_cam_us;
  last_cam_us       = now;
  cam_pulse_time_us = now;
  cam_fired         = true;
  cambox_pulse_count++;
  g_new_cam_rpm     = true;  // إشارة للـ main loop يحدّث الـ RPM
}

// ============================================================
//  SETUP
// ============================================================
void setup() {
  Serial.begin(115200);

  pinMode(INJECTOR_PIN,   OUTPUT);
  pinMode(STATUS_LED_PIN, OUTPUT);
  pinMode(BUZZER_PIN,     OUTPUT);
  pinMode(PRESSURE_PIN,   INPUT);
  pinMode(CAMBOX_PIN,     INPUT_PULLUP);

  digitalWrite(INJECTOR_PIN,   LOW);
  digitalWrite(STATUS_LED_PIN, LOW);
  digitalWrite(BUZZER_PIN,     LOW);

  attachInterrupt(digitalPinToInterrupt(CAMBOX_PIN), cambox_isr, RISING);

  Serial.println("INJECTOR PRO - Ready");
}

// ============================================================
//  MAIN LOOP
// ============================================================
void loop() {

  // 1. قراءة الأوامر القادمة من البرنامج
  handle_serial();

  // 2. منطق الإطلاق — أعلى أولوية
  if (is_running) {
    handle_injection();
  }

  // 3. قراءة ADC في الـ Background (نبضة واحدة per loop — بدون blocking)
  update_pressure_bg();

  // 4. إرسال Telemetry
  unsigned long now = millis();
  if (now - last_telemetry >= TELEMETRY_MS) {
    send_telemetry();
    last_telemetry = now;
  }

  // 5. إيقاف الـ buzzer
  beep_update();
}

// ============================================================
//  INJECTION LOGIC - يختار المنطق حسب الـ active_mode
// ============================================================
void handle_injection() {
  if (active_mode == 0) {
    handle_custom_mode();
  } else {
    handle_cambox_mode();
  }
}

// ---- Custom Mode: حقن بتردد ثابت ----
void handle_custom_mode() {
  unsigned long now = micros();
  unsigned long period_us = 1000000UL / (unsigned long)freq_hz;
  if (now - last_custom_fire_us >= period_us) {
    last_custom_fire_us = now;
    fire_injector();
  }
}

// ---- CamBox Mode: حقن مزامن مع إشارة الكام ----
void handle_cambox_mode() {
  if (cam_fired) {
    cam_fired = false;

    if (delay_angle_deg == 0) {
      fire_injector();
    } else {
      if (rpm_period_us > 0) {
        unsigned long delay_us = (unsigned long)(
          ((float)delay_angle_deg / DEG_PER_REV) * (float)rpm_period_us
        );
        fire_at_us     = cam_pulse_time_us + delay_us;
        injector_armed = true;
      } else {
        fire_injector();
      }
    }
  }

  if (injector_armed && micros() >= fire_at_us) {
    injector_armed = false;
    fire_injector();
  }
}

// ============================================================
//  BUZZER BEEP - non-blocking, بيشغّل الـ buzzer في الـ loop
// ============================================================
void beep_start(int duration_ms = 60) {
  digitalWrite(BUZZER_PIN, HIGH);
  beep_end_ms = millis() + duration_ms;
}

void beep_update() {
  if (beep_end_ms > 0 && millis() >= beep_end_ms) {
    digitalWrite(BUZZER_PIN, LOW);
    beep_end_ms = 0;
  }
}

// ============================================================
//  FIRE INJECTOR
// ============================================================
void fire_injector() {
  digitalWrite(INJECTOR_PIN, HIGH);
  delayMicroseconds(pulse_width_us);
  digitalWrite(INJECTOR_PIN, LOW);
  injector_pulse_count++;
}

// ============================================================
//  SERIAL COMMAND HANDLER
// ============================================================
void handle_serial() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n') {
      serial_buffer.trim();
      process_command(serial_buffer);
      serial_buffer = "";
    } else {
      serial_buffer += c;
    }
  }
}

void process_command(String cmd) {
  if (cmd.length() == 0) return;

  beep_start();  // بيب عند كل أمر وارد

  if (cmd == "start") {
    is_running     = true;
    injector_armed = false;
    digitalWrite(STATUS_LED_PIN, HIGH);
    Serial.println("OK:START");

  } else if (cmd == "stop") {
    is_running     = false;
    injector_armed = false;
    digitalWrite(INJECTOR_PIN,   LOW);
    digitalWrite(STATUS_LED_PIN, LOW);
    Serial.println("OK:STOP");

  } else if (cmd.startsWith("w")) {
    // Pulse Width
    int val = cmd.substring(1).toInt();
    if (val >= 200 && val <= 3000) {
      pulse_width_us = val;
      Serial.print("OK:PW:");
      Serial.println(pulse_width_us);
    } else {
      Serial.println("ERR:PW_OUT_OF_RANGE");
    }

  } else if (cmd.startsWith("a")) {
    // Delay Angle
    int val = cmd.substring(1).toInt();
    if (val >= 0 && val <= 45) {
      delay_angle_deg = val;
      Serial.print("OK:ANGLE:");
      Serial.println(delay_angle_deg);
    } else {
      Serial.println("ERR:ANGLE_OUT_OF_RANGE");
    }

  } else if (cmd.startsWith("f")) {
    // Frequency (Custom Mode)
    int val = cmd.substring(1).toInt();
    if (val >= 1 && val <= 100) {
      freq_hz = val;
      Serial.print("OK:FREQ:");
      Serial.println(freq_hz);
    } else {
      Serial.println("ERR:FREQ_OUT_OF_RANGE");
    }

  } else if (cmd == "mode") {
    // تبديل الوضع
    active_mode    = (active_mode == 0) ? 1 : 0;
    injector_armed = false;
    cam_fired      = false;
    last_custom_fire_us = 0;
    Serial.print("OK:MODE:");
    Serial.println(active_mode == 0 ? "CUSTOM" : "CAMBOX");

  } else if (cmd.length() > 0) {
    Serial.print("ERR:UNKNOWN:");
    Serial.println(cmd);
  }
}

// ============================================================
//  PRESSURE — قراءة في الـ Background (نبضة واحدة per loop)
// ============================================================
void update_pressure_bg() {
  g_adc_sum += analogRead(PRESSURE_PIN);
  g_adc_count++;
  if (g_adc_count >= PRESSURE_SAMPLES) {
    float avg  = (float)g_adc_sum / PRESSURE_SAMPLES;
    float volt = (avg / 4095.0f) * 3.3f * 1.364f;
    float p    = ((volt - PRESSURE_V_MIN) / (PRESSURE_V_MAX - PRESSURE_V_MIN)) * PRESSURE_BAR_MAX;
    if (p < 0.0f)             p = 0.0f;
    if (p > PRESSURE_BAR_MAX) p = PRESSURE_BAR_MAX;
    g_pressure_bar = p;
    g_adc_sum   = 0;
    g_adc_count = 0;
  }
}

// ============================================================
//  SEND TELEMETRY TO PC
//  Format: P:<pressure>,A:<angle>
// ============================================================
void send_telemetry() {
  // الضغط جاهز من الـ background — مفيش blocking هنا
  float pressure = g_pressure_bar;

  // RPM — يتحدث بس لما تيجي نبضة جديدة (مش كل 5ms)
  unsigned long cam_age_us = micros() - last_cam_us;
  if (cam_age_us >= 2000000UL) {
    // الكام وقف من أكتر من 2 ثانية
    g_rpm_ema     = 0.0f;
    g_new_cam_rpm = false;
  } else if (g_new_cam_rpm && rpm_period_us > 0) {
    // نبضة جديدة وصلت — حدّث الـ EMA
    g_new_cam_rpm = false;
    float raw_rpm = 60000000.0f / (float)rpm_period_us;
    g_rpm_ema = RPM_EMA_ALPHA * raw_rpm + (1.0f - RPM_EMA_ALPHA) * g_rpm_ema;
  }
  int rpm = (int)g_rpm_ema;

  // قراءة العدادات مع حماية من الـ ISR
  noInterrupts();
  int inj_pulses = injector_pulse_count;  injector_pulse_count = 0;
  int cam_pulses = cambox_pulse_count;    cambox_pulse_count   = 0;
  interrupts();

  Serial.print("P:");  Serial.print(pressure, 1);
  Serial.print(",A:"); Serial.print(delay_angle_deg);
  Serial.print(",R:"); Serial.print(rpm);
  Serial.print(",I:"); Serial.print(inj_pulses);
  Serial.print(",C:"); Serial.println(cam_pulses);
}
