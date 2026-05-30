// ============================================================
//  INJECTOR PRO - ESP32 Firmware FINAL
//  Single Injector | Pressure Sensor | CamBox Sync
// ============================================================
//
//  PIN CONNECTIONS:
//  -----------------------------------------------
//  Injector Output    --> GPIO 25
//  Pressure Sensor    --> GPIO 34 (Analog 0.5V-4.5V)
//  CamBox Sync Input  --> GPIO 18 (Interrupt, RISING)
//  Status LED         --> GPIO 2  (Built-in)
//  -----------------------------------------------
//
//  PRESSURE SENSOR SPECS:
//  0 BAR   = 1.0V
//  1600 BAR = 4.5V
//
//  CAMBOX:
//  - إشارة واحدة per revolution
//  - الرشاش يطلق بعد delay_angle درجة من الإشارة
//
//  SERIAL PROTOCOL (115200 baud):
//  PC --> ESP32:
//    start\n      = تشغيل
//    stop\n       = إيقاف
//    w<val>\n     = Pulse Width بالميكروثانية (200-3000)
//    a<val>\n     = Delay Angle بالدرجات (0-45)
//
//  ESP32 --> PC:
//    P:<pressure>,A:<angle>\n  كل 100ms
// ============================================================

// ---- PINS ----
#define INJECTOR_PIN      25
#define PRESSURE_PIN      34
#define CAMBOX_PIN        18
#define STATUS_LED_PIN    2

// ---- PRESSURE SENSOR CALIBRATION ----
#define PRESSURE_V_MIN    1.0f      // فولت عند 0 BAR
#define PRESSURE_V_MAX    4.5f      // فولت عند 1600 BAR
#define PRESSURE_BAR_MAX  1600.0f   // أقصى ضغط
#define PRESSURE_SAMPLES  16        // عدد القراءات للمتوسط

// ---- DEFAULTS ----
#define DEFAULT_PW_US     1000      // Pulse Width افتراضي
#define DEFAULT_DELAY_DEG 0         // Delay Angle افتراضي

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
bool           injector_armed  = false;  // هل تم تسليح الحقنة بعد الكام؟
unsigned long  fire_at_us      = 0;      // الوقت المحسوب للإطلاق

unsigned long  last_telemetry  = 0;
String         serial_buffer   = "";

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
  pinMode(PRESSURE_PIN,   INPUT);
  pinMode(CAMBOX_PIN,     INPUT_PULLUP);

  digitalWrite(INJECTOR_PIN,   LOW);
  digitalWrite(STATUS_LED_PIN, LOW);

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
}

// ============================================================
//  INJECTION LOGIC
//  عند كل إشارة كام، نحسب وقت التأخير بناءً على delay_angle
//  ثم نطلق الرشاش بعد هذا الوقت بالظبط
// ============================================================
void handle_injection() {

  // هل جاءت إشارة كام جديدة؟
  if (cam_fired) {
    cam_fired = false;

    if (delay_angle_deg == 0) {
      // لا يوجد تأخير - أطلق فوراً
      fire_injector();
    } else {
      // احسب وقت التأخير من الزاوية
      // delay_us = (delay_angle / 360) * rpm_period_us
      if (rpm_period_us > 0) {
        unsigned long delay_us = (unsigned long)(
          ((float)delay_angle_deg / DEG_PER_REV) * (float)rpm_period_us
        );
        fire_at_us     = cam_pulse_time_us + delay_us;
        injector_armed = true;
      } else {
        // مفيش RPM معروف - أطلق فوراً
        fire_injector();
      }
    }
  }

  // هل حان وقت الإطلاق المؤجل؟
  if (injector_armed && micros() >= fire_at_us) {
    injector_armed = false;
    fire_injector();
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
