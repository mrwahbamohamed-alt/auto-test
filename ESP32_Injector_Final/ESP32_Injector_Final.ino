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
//    P:<pressure>,A:<angle>\n  كل 100ms
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
#define PRESSURE_SAMPLES  16        // عدد القراءات للمتوسط

// ---- DEFAULTS ----
#define DEFAULT_PW_US     1000      // Pulse Width افتراضي
#define DEFAULT_DELAY_DEG 0         // Delay Angle افتراضي
#define DEFAULT_FREQ_HZ   25        // تردد افتراضي للـ Custom Mode

// ---- TIMING ----
#define TELEMETRY_MS      100       // إرسال Telemetry كل 100ms
#define DEG_PER_REV       360.0f    // درجات اللفة الكاملة

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

unsigned long  beep_end_ms     = 0;  // وقت انتهاء الـ beep

// ============================================================
//  INTERRUPT - CamBox Pulse (RISING EDGE
// ============================================================
void IRAM_ATTR cambox_isr() {
  unsigned long now = micros();
  rpm_period_us    = now - last_cam_us;  // حساب الفترة = قياس RPM
  last_cam_us      = now;
  cam_pulse_time_us = now;
  cam_fired        = true;
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

  // 2. منطق الإطلاق
  if (is_running) {
    handle_injection();
  }

  // 3. إرسال Telemetry كل 100ms
  unsigned long now = millis();
  if (now - last_telemetry >= TELEMETRY_MS) {
    send_telemetry();
    last_telemetry = now;
  }

  // 4. إيقاف الـ buzzer لما ينتهي وقته
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
//  PRESSURE SENSOR
//  0 BAR  = 1.0V
//  1600 BAR = 4.5V
//  ESP32 ADC: 0-3.3V / 12-bit (0-4095)
//  ملاحظة: لو السنسور بيوصل 4.5V استخدم voltage divider
//  عشان تحميه من الـ 3.3V المسموح بيها على ESP32
// ============================================================
float read_pressure_bar() {
  long adc_sum = 0;
  for (int i = 0; i < PRESSURE_SAMPLES; i++) {
    adc_sum += analogRead(PRESSURE_PIN);
    delayMicroseconds(50);
  }
  float adc_avg = (float)adc_sum / PRESSURE_SAMPLES;

  // تحويل ADC لفولت (مع مراعاة الـ voltage divider لو موجود)
  // لو عندك voltage divider 4.5V -> 3.3V اضرب في 1.364
  float voltage = (adc_avg / 4095.0f) * 3.3f * 1.364f;

  // تحويل فولت لـ BAR
  float pressure = ((voltage - PRESSURE_V_MIN) /
                    (PRESSURE_V_MAX - PRESSURE_V_MIN)) * PRESSURE_BAR_MAX;

  // تحديد الحدود
  if (pressure < 0.0f)            pressure = 0.0f;
  if (pressure > PRESSURE_BAR_MAX) pressure = PRESSURE_BAR_MAX;

  return pressure;
}

// ============================================================
//  SEND TELEMETRY TO PC
//  Format: P:<pressure>,A:<angle>
// ============================================================
void send_telemetry() {
  float pressure = read_pressure_bar();

  // حساب RPM من فترة الكام (اختياري للعرض)
  // int rpm = (rpm_period_us > 0) ? (60000000UL / rpm_period_us) : 0;

  Serial.print("P:");
  Serial.print(pressure, 1);
  Serial.print(",A:");
  Serial.println(delay_angle_deg);
}
