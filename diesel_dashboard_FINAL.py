import sys
import time
import logging
import socket
import datetime
import json
import os
import csv as _csv
from pathlib import Path
from collections import deque

# Hide the console window on Windows (no black terminal popping up)
if sys.platform == 'win32':
    import ctypes
    ctypes.windll.user32.ShowWindow(
        ctypes.windll.kernel32.GetConsoleWindow(), 0)

logging.basicConfig(level=logging.WARNING)   # suppress INFO logs to console

from PyQt6.QtCore import QObject, pyqtSignal, QThread, Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QGroupBox, QLabel, QComboBox, QPushButton, QSlider,
    QSpinBox, QDoubleSpinBox, QRadioButton, QButtonGroup, QLCDNumber,
    QMessageBox, QFrame, QFileDialog, QScrollArea, QCheckBox, QLineEdit
)
from PyQt6.QtGui import QFont, QColor, QPainter, QPixmap, QPalette

import serial
import serial.tools.list_ports
import pyqtgraph as pg

# logging already configured above (WARNING level, no console output)

# ── constants ─────────────────────────────────────────────────────────
N_SAMPLES    = 300
TELEMETRY_MS = 10
GRAPH_FPS    = 30

# Display-only localization catalog. Protocol commands, profile keys, and
# exported field names remain English and are intentionally not translated.
UI_TRANSLATIONS = {
    "en": {
        "language_toggle": "العربية",
        "connection": "CONNECTION", "connect": "CONNECT", "disconnect": "DISCONNECT",
        "disconnected": "DISCONNECTED", "connected": "CONNECTED", "no_data": "NO DATA",
        "calibration": "CALIBRATION TABLE  —  DELIVERY SPEC  (ml / 1000 pulses)",
        "injector_model": "INJECTOR MODEL", "save_as": "SAVE AS…", "update": "UPDATE",
        "delete": "DELETE", "q_inject": "Q INJECT  —  ml", "waveform": "WAVEFORM",
        "freeze": "FREEZE", "live": "LIVE", "frozen": "FROZEN", "injector_profile": "INJECTOR PROFILE",
        "add": "+ ADD", "injection_mode": "INJECTION MODE", "common_rail": "Common Rail",
        "cambox_sync": "CamBox  (Sync)", "parameters": "PARAMETERS", "coils": "COILS",
        "relay": "RELAY  ·  PEAK SUPPLY", "single_shot": "VALVE SINGLE-SHOT", "actuators": "ACTUATORS",
        "measurements": "MEASUREMENTS", "auto_reconnect": "Auto-Reconnect", "off": "OFF",
        "test_mode": "Test Mode", "rpm": "RPM", "pulse_header": "PW (µs)", "time": "Time (s)",
        "target_ml": "Target (ml)", "min": "Min", "max": "Max", "unit": "Unit",
        "actual": "Actual", "status": "Status", "pulse_width": "PULSE WIDTH (µs)",
        "frequency_hz": "FREQUENCY (Hz)", "delay_angle": "DELAY ANGLE (°)", "delay_ms": "DELAY  —  ms",
        "delay": "DELAY", "waiting_rpm": "DELAY  —  waiting for RPM signal",
        "rpm_divisor": "RPM DIVISOR", "pressure_divisor": "PRESSURE DIVISOR", "injector_id": "INJECTOR ID",
        "brand": "BRAND", "model": "MODEL", "port": "PORT", "baud": "BAUD",
        "on": "ON", "enabled": "ENABLED", "disabled": "DISABLED", "fault": "FAULT", "ok": "OK",
        "shot": "▶  SHOT", "run": "▶  RUN", "stop_run": "■  STOP", "fire_shot": "▶  FIRE SHOT",
        "start": "  START", "stop": "  STOP", "sync": "↺  SYNC PARAMS", "save_pdf": "  SAVE PDF REPORT",
        "export_csv": "  EXPORT CSV", "set_zero": "◎  SET ZERO PRESSURE", "engine": "ENGINE",
        "stopped": "STOPPED", "running": "RUNNING", "inj_pulse": "INJ PULSE", "target_rpm": "Target RPM",
        "leak_test": "LEAK TEST (no injection)", "common_rail_mode": "COMMON RAIL", "cambox_mode": "CAMBOX",
        "cam_box": "⇄  CAM BOX", "common_rail_switch": "⇄  COMMON RAIL", "pulses": "PULSES:",
        "packet_rate": "PKT:", "bar": "bar", "duty": "duty:", "frequency": "f:",
        "pressure": "PRESSURE", "injection": "INJECTION", "cam": "CAM", "pass": "PASS", "fail": "FAIL",
        "not_tested": "— not tested", "no_measurements": "NO MEASUREMENTS ENTERED", "overall": "OVERALL:",
        "report_saved": "Report Saved", "exit": "EXIT", "select_system": "SELECT OPERATING SYSTEM",
        "language_english": "English", "light_mode": "LIGHT MODE", "dark_mode": "DARK MODE",
    },
    "ar": {
        "language_toggle": "English",
        "connection": "الاتصال", "connect": "اتصال", "disconnect": "قطع الاتصال",
        "disconnected": "غير متصل", "connected": "متصل", "no_data": "لا توجد بيانات",
        "calibration": "جدول المعايرة  —  مواصفات التدفق (مل / 1000 نبضة)",
        "injector_model": "طراز الحاقن", "save_as": "حفظ باسم…", "update": "تحديث",
        "delete": "حذف", "q_inject": "كمية الحقن  —  مل", "waveform": "شكل الموجة",
        "freeze": "تجميد", "live": "مباشر", "frozen": "مجمد", "injector_profile": "ملف الحاقن",
        "add": "+ إضافة", "injection_mode": "وضع الحقن", "common_rail": "سكة مشتركة",
        "cambox_sync": "كام بوكس  (متزامن)", "parameters": "المعلمات", "coils": "الملفات",
        "relay": "المرحل  ·  تغذية الذروة", "single_shot": "طلقة صمام مفردة", "actuators": "المشغلات",
        "measurements": "القياسات", "auto_reconnect": "إعادة اتصال تلقائية", "off": "إيقاف",
        "test_mode": "وضع الاختبار", "rpm": "دورة/دقيقة", "pulse_header": "عرض النبضة (ميكروثانية)",
        "time": "الوقت (ث)", "target_ml": "الهدف (مل)", "min": "الأدنى", "max": "الأقصى",
        "unit": "الوحدة", "actual": "الفعلي", "status": "الحالة", "pulse_width": "عرض النبضة (ميكروثانية)",
        "frequency_hz": "التردد (هرتز)", "delay_angle": "زاوية التأخير (°)", "delay_ms": "التأخير  —  مللي ثانية",
        "delay": "التأخير", "waiting_rpm": "التأخير  —  في انتظار إشارة سرعة المحرك",
        "rpm_divisor": "مقسم سرعة المحرك", "pressure_divisor": "مقسم الضغط", "injector_id": "معرف الحاقن",
        "brand": "العلامة", "model": "الطراز", "port": "المنفذ", "baud": "معدل النقل",
        "on": "تشغيل", "enabled": "مفعل", "disabled": "معطل", "fault": "عطل", "ok": "سليم",
        "shot": "▶  طلقة", "run": "▶  تشغيل", "stop_run": "■  إيقاف", "fire_shot": "▶  إطلاق طلقة",
        "start": "  بدء", "stop": "  إيقاف", "sync": "↺  مزامنة المعلمات", "save_pdf": "  حفظ تقرير PDF",
        "export_csv": "  تصدير CSV", "set_zero": "◎  ضبط ضغط الصفر", "engine": "المحرك",
        "stopped": "متوقف", "running": "يعمل", "inj_pulse": "نبضة الحقن", "target_rpm": "سرعة المحرك المطلوبة",
        "leak_test": "اختبار التسرب (بدون حقن)", "common_rail_mode": "سكة مشتركة", "cambox_mode": "كام بوكس",
        "cam_box": "⇄  كام بوكس", "common_rail_switch": "⇄  السكة المشتركة", "pulses": "النبضات:",
        "packet_rate": "الحزم:", "bar": "بار", "duty": "نسبة التشغيل:", "frequency": "التردد:",
        "pressure": "الضغط", "injection": "الحقن", "cam": "الكام", "pass": "ناجح", "fail": "فشل",
        "not_tested": "— لم يُختبر", "no_measurements": "لم تُدخل قياسات", "overall": "النتيجة:",
        "report_saved": "تم حفظ التقرير", "exit": "خروج", "select_system": "اختر نظام التشغيل",
        "language_english": "العربية", "light_mode": "الوضع الفاتح", "dark_mode": "الوضع الداكن",
    },
}

# ══════════════════════════════════════════════════════════════════════
#  PRESSURE CALIBRATION — all done in Python (ESP32 sends raw VX4 mV)
#  Sensor supply : 5V
#  VP @ 0 BAR   : 0.3 V   (sensor zero offset)
#  VP @ 1600 BAR: 5.0 V   (sensor full-scale)
#  Divider      : VX4 = VP × 0.297  →  VP = VX4 / 0.297
#  EMA alpha    : 0.02 (strong smoothing, eliminates EMI jitter)
#  P_CAL_OFFSET : fine zero trim in BAR — increase if display reads
#                 non-zero at rest (e.g. P_CAL_OFFSET = -5.0)
# ══════════════════════════════════════════════════════════════════════
# ── Calibration points (measured) ────────────────────────────────────
#   0 BAR  → VX4 = 112 mV
#   260 BAR→ VX4 = 227 mV
#   540 BAR→ VX4 = 339 mV
#   slope  = least-squares fit forcing through zero
P_VX4_ZERO_MV   = 112.0   # mV ← عدّل بـ SET ZERO أو يدوياً
P_SLOPE_BAR_MV  = 2.355   # BAR/mV ← slope من regression الثلاث نقاط
P_BAR_MAX_VAL   = 1600.0
P_EMA_ALPHA     = 0.05    # ← 0.01=أبطأ/أثبت  0.1=أسرع  (كان 0.20 — الآن أثقل بـ 4×)
P_DEAD_BAND     = 5.0     # BAR ← أقل من ده = صفر
P_CAL_OFFSET    = -9.0    # fine trim (BAR) ← عدّل هنا لو القراية عالية أو واطية
RPM_DIVISOR     = 2.0     # ← عدّل هنا لو قراية الـ RPM غلط (actual ÷ displayed)
PRESSURE_DIVISOR = 1.90   # ← displayed bar = raw bar / this. Persisted in QSettings.
# ══════════════════════════════════════════════════════════════════════

# ── Safety alarm thresholds ───────────────────────────────────────────
PRESSURE_WARN  = 1400.0   # BAR  — amber warning  (~87% of 1600)
PRESSURE_ALARM = 1600.0   # BAR  — red alarm     (sensor max)
RPM_WARN       =  3000    # RPM  — amber warning
RPM_ALARM      =  4000    # RPM  — red alarm

# ── Test Plan Presets  (Solenoid Common Rail only — no Piezo) ─────────
# Format: { display_name : (pulse_width_µs, freq_hz, delay_deg) }
PRESETS = {
    "-- Select Preset --":     None,
    "Bosch CRI 1  (Gen 1)":    (1050, 25, 0),
    "Bosch CRI 2  (Gen 2)":    ( 850, 25, 5),
    "Bosch CRI 3  (Gen 3)":    ( 650, 25, 8),
    "Delphi DFI 1.x":          ( 950, 25, 3),
    "Delphi DFI 2.x":          ( 800, 25, 4),
    "Denso HP3":               (1100, 25, 2),
    "Denso HP4":               ( 750, 25, 4),
    "Siemens / Conti VDO":     ( 880, 25, 6),
}

# ── Apple-inspired Industrial Dark Design System ──────────────────────
BG        = '#121214'   # Main window — Deep Charcoal
PANEL     = '#1C1C1E'   # Cards / GroupBoxes
HEADER    = '#0A0A0C'   # Header bar
BORDER    = '#2C2C2E'   # Subtle card border
BORDER2   = '#3A3A3C'   # Widget / interactive borders

PH_GREEN  = '#30D158'   # Muted Emerald — success / running
PH_AMBER  = '#FF9F0A'   # System Orange — warnings
PH_BLUE   = '#0A84FF'   # Tech Blue — primary accent
PH_PURPLE = '#BF5AF2'   # System Purple — RPM
PH_RED    = '#FF453A'   # Deep Crimson — alarms / disconnected
PH_CYAN   = '#30B0C7'   # Sleek Teal — sliders / radio

TXT_PRI   = '#E5E5EA'   # High-contrast off-white
TXT_SEC   = '#8E8E93'   # Muted gray — secondary text / units
TXT_DIM   = '#48484A'   # Very muted — dim labels

# ── Oscilloscope graph colors (match window BG for seamless blend) ─────
G_BG    = '#121214'   # Exact BG match — no visible seam
G_AMBER = '#FF9F0A'   # Pressure trace
G_GREEN = '#30D158'   # Injection trace
G_BLUE  = '#30B0C7'   # CAM trace

# ── data ──────────────────────────────────────────────────────────────
X_DATA = list(range(N_SAMPLES))
X_STEP = []
for _i in range(N_SAMPLES):
    X_STEP.extend([_i, _i + 0.999])

def make_step(buf):
    out = []
    for v in buf:
        out.extend([v, v])
    return out

# ══════════════════════════════════════════════════════════════════════
#  STYLESHEETS  (dark default + light mode)
# ══════════════════════════════════════════════════════════════════════
STYLE_DARK = f"""
/* ── Base ─────────────────────────────────────────────────────────── */
QMainWindow, QWidget {{
    background: {BG};
    color: {TXT_PRI};
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 12px;
}}

/* ── Cards / GroupBoxes ───────────────────────────────────────────── */
QGroupBox {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
    margin-top: 24px;
    padding-top: 4px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    background: {PANEL};
    color: {TXT_DIM};
    font-size: 9px;
    font-weight: bold;
    letter-spacing: 2px;
    text-transform: uppercase;
}}

/* ── Labels ───────────────────────────────────────────────────────── */
QLabel {{
    color: {TXT_SEC};
    font-size: 12px;
    background: transparent;
}}

/* ── ComboBox ─────────────────────────────────────────────────────── */
QComboBox {{
    background: {BORDER};
    border: 1px solid {BORDER2};
    border-radius: 6px;
    padding: 5px 34px 5px 10px;
    color: {TXT_PRI};
    font-size: 12px;
    font-family: 'Consolas', monospace;
    min-height: 28px;
    selection-background-color: {PH_BLUE};
    selection-color: #FFFFFF;
}}
QComboBox:hover {{
    border-color: {PH_BLUE};
    background: #1E1E22;
}}
QComboBox:focus {{
    border: 1px solid {PH_BLUE};
    background: #1A1A20;
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 28px;
    border-left: 1px solid {BORDER2};
    border-radius: 0 6px 6px 0;
    background: {BORDER2};
}}
QComboBox::drop-down:hover {{
    background: {PH_BLUE};
}}
QComboBox::down-arrow {{
    image: none;
    width: 0;
    height: 0;
}}
QComboBox QAbstractItemView {{
    background: {PANEL};
    border: 1px solid {BORDER2};
    border-radius: 6px;
    color: {TXT_PRI};
    selection-background-color: {PH_BLUE};
    selection-color: #FFFFFF;
    padding: 2px;
    outline: none;
}}
QComboBox QAbstractItemView::item {{
    padding: 6px 10px;
    min-height: 26px;
    border-radius: 4px;
}}
QComboBox QAbstractItemView::item:hover {{
    background: {BORDER2};
    color: {TXT_PRI};
}}

/* ── SpinBox ──────────────────────────────────────────────────────── */
QSpinBox {{
    background: {BORDER};
    border: 1px solid {BORDER2};
    border-radius: 6px;
    padding: 5px 8px;
    color: {TXT_PRI};
    font-size: 12px;
    font-family: 'Consolas', monospace;
    min-height: 28px;
    selection-background-color: {PH_BLUE};
}}
QSpinBox:hover {{
    border-color: {PH_BLUE};
    background: #1E1E22;
}}
QSpinBox:focus {{
    border: 1px solid {PH_BLUE};
    background: #1A1A20;
}}
QSpinBox::up-button, QSpinBox::down-button {{
    background: {BORDER2};
    border: none;
    width: 18px;
}}
QSpinBox::up-button {{ border-radius: 0 6px 0 0; }}
QSpinBox::down-button {{ border-radius: 0 0 6px 0; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
    background: {PH_BLUE};
}}
QSpinBox::up-arrow, QSpinBox::down-arrow {{ image: none; width: 0; height: 0; }}

/* ── Slider ───────────────────────────────────────────────────────── */
QSlider::groove:horizontal {{
    border: none;
    height: 4px;
    background: {BORDER};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {PH_CYAN};
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
    border: 2px solid {BG};
}}
QSlider::handle:horizontal:hover {{ background: #3EC5D8; }}
QSlider::sub-page:horizontal {{
    background: {PH_CYAN};
    border-radius: 2px;
}}

/* ── PushButton (general) ─────────────────────────────────────────── */
QPushButton {{
    background: {BORDER};
    border: 1px solid {BORDER2};
    color: {TXT_SEC};
    padding: 7px 16px;
    border-radius: 7px;
    font-size: 12px;
    font-weight: 500;
}}
QPushButton:hover {{
    background: {BORDER2};
    color: {TXT_PRI};
    border-color: {PH_BLUE};
}}
QPushButton:pressed {{
    background: {BG};
    color: {TXT_PRI};
    border-color: {PH_BLUE};
}}
QPushButton:disabled {{
    color: {TXT_DIM};
    border-color: {BORDER};
    background: {PANEL};
}}

/* ── LCD Number ───────────────────────────────────────────────────── */
QLCDNumber {{
    background: {G_BG};
    border: 1px solid {BORDER};
    border-radius: 6px;
    color: {TXT_PRI};
}}

/* ── Radio Button ─────────────────────────────────────────────────── */
QRadioButton {{
    color: {TXT_SEC};
    font-size: 12px;
    spacing: 8px;
    background: transparent;
}}
QRadioButton:hover {{ color: {TXT_PRI}; }}
QRadioButton::indicator {{
    width: 15px;
    height: 15px;
    border: 2px solid {BORDER2};
    border-radius: 8px;
    background: {BORDER};
}}
QRadioButton::indicator:checked {{
    background: {PH_CYAN};
    border-color: {PH_CYAN};
}}
QRadioButton::indicator:hover {{ border-color: {PH_BLUE}; }}

/* ── Scrollbar ────────────────────────────────────────────────────── */
QScrollBar:vertical {{
    background: {PANEL};
    width: 8px;
    margin: 0;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER2};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: {TXT_DIM}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ height: 0; }}

/* ── ToolTip ──────────────────────────────────────────────────────── */
QToolTip {{
    background: {PANEL};
    color: {TXT_PRI};
    border: 1px solid {BORDER2};
    border-radius: 5px;
    font-size: 11px;
    padding: 5px 8px;
}}

/* ── Separator ────────────────────────────────────────────────────── */
QFrame[frameShape="4"] {{ color: {BORDER2}; }}
"""

STYLE_LIGHT = """
/* ── Base ─────────────────────────────────────────────────────────── */
QMainWindow, QWidget {
    background: #F8F9FA;
    color: #1C1C1E;
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 12px;
}

/* ── Cards / GroupBoxes ───────────────────────────────────────────── */
QGroupBox {
    background: #FFFFFF;
    border: 1px solid #E0E0E6;
    border-radius: 8px;
    margin-top: 24px;
    padding-top: 4px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    background: #FFFFFF;
    color: #0056B3;
    font-size: 9px;
    font-weight: bold;
    letter-spacing: 2px;
}

/* ── Labels ───────────────────────────────────────────────────────── */
QLabel {
    color: #1C1C1E;
    font-size: 12px;
    font-weight: 500;
    background: transparent;
}

/* ── ComboBox ─────────────────────────────────────────────────────── */
QComboBox {
    background: #FFFFFF;
    border: 1px solid #D1D1D6;
    border-radius: 6px;
    padding: 5px 34px 5px 10px;
    color: #1C1C1E;
    font-size: 12px;
    font-family: 'Consolas', monospace;
    min-height: 28px;
    selection-background-color: #0A84FF;
    selection-color: #FFFFFF;
}
QComboBox:hover {
    border-color: #0A84FF;
    background: #F5F5F9;
}
QComboBox:focus {
    border: 1px solid #0A84FF;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 28px;
    border-left: 1px solid #D1D1D6;
    border-radius: 0 6px 6px 0;
    background: #EBEBF0;
}
QComboBox::drop-down:hover { background: #0A84FF; }
QComboBox::down-arrow { image: none; width: 0; height: 0; }
QComboBox QAbstractItemView {
    background: #FFFFFF;
    border: 1px solid #D1D1D6;
    border-radius: 6px;
    color: #1C1C1E;
    selection-background-color: #0A84FF;
    selection-color: #FFFFFF;
    padding: 2px;
    outline: none;
}
QComboBox QAbstractItemView::item {
    padding: 6px 10px;
    min-height: 26px;
    border-radius: 4px;
}
QComboBox QAbstractItemView::item:hover { background: #F2F2F7; }

/* ── SpinBox ──────────────────────────────────────────────────────── */
QSpinBox {
    background: #FFFFFF;
    border: 1px solid #D1D1D6;
    border-radius: 6px;
    padding: 5px 8px;
    color: #1C1C1E;
    font-size: 12px;
    font-family: 'Consolas', monospace;
    min-height: 28px;
    selection-background-color: #0A84FF;
}
QSpinBox:hover { border-color: #0A84FF; background: #F5F5F9; }
QSpinBox:focus { border: 1px solid #0A84FF; }
QSpinBox::up-button, QSpinBox::down-button {
    background: #EBEBF0; border: none; width: 18px;
}
QSpinBox::up-button { border-radius: 0 6px 0 0; }
QSpinBox::down-button { border-radius: 0 0 6px 0; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: #0A84FF; }
QSpinBox::up-arrow, QSpinBox::down-arrow { image: none; width: 0; height: 0; }

/* ── Slider ───────────────────────────────────────────────────────── */
QSlider::groove:horizontal {
    border: none; height: 4px;
    background: #D1D1D6; border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #0A84FF; width: 14px; height: 14px;
    margin: -5px 0; border-radius: 7px; border: 2px solid #F8F9FA;
}
QSlider::handle:horizontal:hover { background: #0077E6; }
QSlider::sub-page:horizontal { background: #0A84FF; border-radius: 2px; }

/* ── PushButton (general) ─────────────────────────────────────────── */
QPushButton {
    background: #FFFFFF;
    border: 1px solid #D1D1D6;
    color: #1C1C1E;
    padding: 7px 16px;
    border-radius: 7px;
    font-size: 12px;
    font-weight: 500;
}
QPushButton:hover {
    background: #F2F2F7;
    color: #1C1C1E;
    border-color: #0A84FF;
}
QPushButton:pressed {
    background: #E5E5EA;
    color: #1C1C1E;
    border-color: #0A84FF;
}
QPushButton:disabled {
    color: #AEAEB2;
    border-color: #E5E5EA;
    background: #F8F9FA;
}

/* ── LCD Number (stays dark — better readability for digits) ──────── */
QLCDNumber {
    background: #1C1C1E;
    border: 1px solid #D1D1D6;
    border-radius: 6px;
}

/* ── Radio Button ─────────────────────────────────────────────────── */
QRadioButton {
    color: #1C1C1E;
    font-size: 12px;
    spacing: 8px;
    background: transparent;
}
QRadioButton:hover { color: #000000; }
QRadioButton::indicator {
    width: 15px; height: 15px;
    border: 2px solid #D1D1D6;
    border-radius: 8px;
    background: #FFFFFF;
}
QRadioButton::indicator:checked { background: #0A84FF; border-color: #0A84FF; }
QRadioButton::indicator:hover { border-color: #0A84FF; }

/* ── Scrollbar ────────────────────────────────────────────────────── */
QScrollBar:vertical {
    background: #F2F2F7; width: 8px; margin: 0; border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #C7C7CC; border-radius: 4px; min-height: 24px;
}
QScrollBar::handle:vertical:hover { background: #AEAEB2; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { height: 0; }

/* ── ToolTip ──────────────────────────────────────────────────────── */
QToolTip {
    background: #FFFFFF; color: #1C1C1E;
    border: 1px solid #D1D1D6; border-radius: 5px;
    font-size: 11px; padding: 5px 8px;
}

/* ── Separator ────────────────────────────────────────────────────── */
QFrame[frameShape="4"] { color: #D1D1D6; }
"""


class CylinderGauge(QWidget):
    """
    Draws a vertical graduated cylinder (like a lab measuring tube).
    Shows: target volume, acceptable range (green zone), and
    the user-entered actual measured value (blue fill).
    """

    def __init__(self, label: str, unit: str,
                 target: float, low: float, high: float,
                 scale_max: float = None, parent=None):
        super().__init__(parent)
        self._label   = label
        self._unit    = unit
        self._target  = target
        self._low     = low
        self._high    = high
        self._scale   = scale_max or max(high * 1.25, target * 1.5, 5.0)
        self._actual  = None        # None = not measured yet
        self._dark    = True        # theme — drives bg / text colors
        self.setMinimumSize(45, 120)

    def set_actual(self, value: float | None):
        self._actual = value
        self.update()

    def set_dark(self, dark: bool):
        self._dark = dark
        self.update()

    def set_spec(self, target, low, high, scale_max=None):
        self._target = target
        self._low    = low
        self._high   = high
        self._scale  = scale_max or max(high * 1.25, target * 1.5, 5.0)
        self._actual = None
        self.update()

    # ─────────────────────────────────────────────────────────────────
    def paintEvent(self, _event):
        p  = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()

        cx   = W // 2
        cw   = max(20, min(32, W - 40))   # cylinder width — leave room for tick labels
        top  = 30                          # top of cylinder body
        bot  = H - 48                      # bottom of cylinder body
        ch   = bot - top                   # cylinder height (pixels)
        x0   = cx - cw // 2

        def y_for(val):
            """Convert value → pixel y (0 at bottom, max at top)."""
            frac = max(0.0, min(1.0, val / self._scale)) if self._scale > 0 else 0
            return int(bot - frac * ch)

        # ── theme-aware colors (dark vs light) ────────────────────────
        c_bg      = BG      if self._dark else '#FFFFFF'
        c_outline = BORDER2 if self._dark else '#C7C7CC'
        c_dim     = TXT_DIM if self._dark else '#9A9AA0'
        c_sec     = TXT_SEC if self._dark else '#1C1C1E'

        # ── background ────────────────────────────────────────────────
        p.fillRect(0, 0, W, H, QColor(c_bg))

        # ── green acceptable zone ─────────────────────────────────────
        if self._high > 0:
            y_hi = y_for(self._high)
            y_lo = y_for(self._low)
            zone = QColor(PH_GREEN); zone.setAlpha(35)
            p.fillRect(x0, y_hi, cw, y_lo - y_hi, zone)

        # ── actual fill (blue) ────────────────────────────────────────
        if self._actual is not None:
            y_act = y_for(self._actual)
            fill_c = QColor(PH_GREEN) if self._low <= self._actual <= self._high else QColor(PH_RED)
            fill_c.setAlpha(150)
            p.fillRect(x0 + 2, y_act, cw - 4, bot - y_act, fill_c)

        # ── cylinder outline ──────────────────────────────────────────
        pen = p.pen(); pen.setColor(QColor(c_outline)); pen.setWidth(1); p.setPen(pen)
        p.drawRect(x0, top, cw, ch)

        # ── graduations ───────────────────────────────────────────────
        steps = 5
        p.setFont(QFont("Consolas", 7))
        for i in range(steps + 1):
            val = self._scale * i / steps
            yg  = y_for(val)
            tick_w = 8 if i % 2 == 0 else 4
            pen.setColor(QColor(c_dim)); pen.setWidth(1); p.setPen(pen)
            p.drawLine(x0 + cw, yg, x0 + cw + tick_w, yg)
            if i % 2 == 0 and (x0 + cw + 11 + 28) <= W:
                pen.setColor(QColor(c_dim)); p.setPen(pen)
                txt = f"{val:.0f}"
                p.drawText(x0 + cw + 11, yg + 4, txt)

        # ── target line (amber dashed) ────────────────────────────────
        if self._target > 0:
            yt = y_for(self._target)
            pen.setColor(QColor(PH_AMBER)); pen.setWidth(2)
            pen.setStyle(Qt.PenStyle.DashLine); p.setPen(pen)
            p.drawLine(x0 - 4, yt, x0 + cw + 4, yt)
            pen.setStyle(Qt.PenStyle.SolidLine); p.setPen(pen)
            p.setFont(QFont("Consolas", 7, QFont.Weight.Bold))
            p.drawText(x0 - 4, yt - 3, f"►{self._target:.1f}")

        # ── label (bottom) ────────────────────────────────────────────
        p.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        pen.setColor(QColor(c_sec)); p.setPen(pen)
        p.drawText(0, bot + 8, W, 14,
                   Qt.AlignmentFlag.AlignHCenter, self._label)
        p.setFont(QFont("Consolas", 7))
        pen.setColor(QColor(c_dim)); p.setPen(pen)
        p.drawText(0, bot + 22, W, 12,
                   Qt.AlignmentFlag.AlignHCenter, self._unit)

        # ── actual value readout ──────────────────────────────────────
        if self._actual is not None:
            p.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
            c = QColor(PH_GREEN) if self._low <= self._actual <= self._high else QColor(PH_RED)
            pen.setColor(c); p.setPen(pen)
            p.drawText(0, bot + 34, W, 14,
                       Qt.AlignmentFlag.AlignHCenter, f"{self._actual:.2f}")
        else:
            p.setFont(QFont("Consolas", 7))
            pen.setColor(QColor(c_dim)); p.setPen(pen)
            p.drawText(0, bot + 34, W, 14,
                       Qt.AlignmentFlag.AlignHCenter, "—.—")

        # ── top cap ───────────────────────────────────────────────────
        p.setFont(QFont("Consolas", 7))
        pen.setColor(QColor(c_dim)); p.setPen(pen)
        p.drawText(0, 6, W, 14,
                   Qt.AlignmentFlag.AlignHCenter, f"max {self._scale:.0f}")


# ══════════════════════════════════════════════════════════════════════
#  INJECTOR DATABASE
# ══════════════════════════════════════════════════════════════════════
# ── Resolve database path (works both as .py script and PyInstaller .exe) ──
def _resolve_db_path() -> Path:
    # Writable folder: %APPDATA%\CAM PRO\
    app_data = Path(os.environ.get("APPDATA", Path.home())) / "CAM PRO"
    app_data.mkdir(parents=True, exist_ok=True)
    writable = app_data / "injector_db.json"
    if not writable.exists():
        # First run — seed from bundled copy
        if getattr(sys, "frozen", False):
            seed = Path(sys._MEIPASS) / "injector_db.json"
        else:
            seed = Path(__file__).parent / "injector_db.json"
        if seed.exists():
            import shutil
            shutil.copy2(seed, writable)
    return writable

_DB_PATH = _resolve_db_path()


# ══════════════════════════════════════════════════════════════════════
#  COIL NAMES  —  user-editable labels, persisted between sessions
# ══════════════════════════════════════════════════════════════════════
COIL_COUNT         = 3
COIL_PIN_LABELS    = ("COIL 1", "COIL 2", "COIL 3")
COIL_DEFAULT_NAMES = ("COIL 1", "COIL 2", "COIL 3")
COIL_NAME_MAXLEN   = 24

def _resolve_coil_cfg_path() -> Path:
    app_data = Path(os.environ.get("APPDATA", Path.home())) / "CAM PRO"
    app_data.mkdir(parents=True, exist_ok=True)
    return app_data / "coil_names.json"

_COIL_CFG_PATH = _resolve_coil_cfg_path()

def load_coil_names() -> list:
    """Read coil_names.json; fall back to defaults for anything missing/blank."""
    names = list(COIL_DEFAULT_NAMES)
    try:
        with open(_COIL_CFG_PATH, encoding="utf-8") as f:
            saved = json.load(f).get("names", [])
        for i in range(min(COIL_COUNT, len(saved))):
            if isinstance(saved[i], str) and saved[i].strip():
                names[i] = saved[i].strip()[:COIL_NAME_MAXLEN]
    except FileNotFoundError:
        pass
    except (json.JSONDecodeError, AttributeError, TypeError) as e:
        logging.error(f"coil_names.json parse error: {e} — using defaults.")
    return names

def save_coil_names(names) -> None:
    try:
        with open(_COIL_CFG_PATH, "w", encoding="utf-8") as f:
            json.dump({"names": list(names)}, f, indent=2, ensure_ascii=False)
    except OSError as e:
        logging.error(f"coil_names.json save error: {e}")


class InjectorDatabase:
    """Load, query, and save the injector profile database."""

    def __init__(self):
        self._data = {"version": "1.1", "profiles": []}
        self._load()

    def _load(self):
        try:
            with open(_DB_PATH, encoding="utf-8") as f:
                self._data = json.load(f)
        except FileNotFoundError:
            logging.warning("injector_db.json not found — using empty database.")
        except json.JSONDecodeError as e:
            logging.error(f"injector_db.json parse error: {e}")

    def save(self):
        with open(_DB_PATH, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    @property
    def profiles(self):
        return self._data.get("profiles", [])

    def brands(self):
        return sorted(set(p["brand"] for p in self.profiles))

    def by_brand(self, brand):
        return [p for p in self.profiles if p["brand"] == brand]

    def by_id(self, pid):
        return next((p for p in self.profiles if p["id"] == pid), None)

    def cambox_profiles(self):
        """Return the global CamBox mode profiles dict."""
        return self._data.get("cambox_profiles", {})

    def add_profile(self, profile: dict):
        self._data["profiles"].append(profile)
        self.save()

    def delete_profile(self, pid: str):
        self._data["profiles"] = [p for p in self.profiles if p["id"] != pid]
        self.save()

    def update_profile(self, pid: str, updated: dict):
        for i, p in enumerate(self._data["profiles"]):
            if p["id"] == pid:
                self._data["profiles"][i] = updated
                self.save()
                return


# ══════════════════════════════════════════════════════════════════════
#  SAFETY VALIDATOR
# ══════════════════════════════════════════════════════════════════════
class SafetyValidator:
    """Hard-limit validation before any command reaches the ESP32."""

    # Absolute hardware limits (never exceeded regardless of profile)
    ABS_MAX_PULSE_US  = 5000
    ABS_MIN_PULSE_US  = 200
    ABS_MAX_FREQ_HZ   = 100
    ABS_MIN_FREQ_HZ   = 1
    ABS_MAX_DELAY_DEG = 45
    ABS_MIN_DELAY_DEG = 0

    def __init__(self, profile: dict = None):
        self._profile = profile  # currently loaded injector profile

    def set_profile(self, profile: dict):
        self._profile = profile

    def _profile_limits(self):
        if self._profile and "safety" in self._profile:
            s = self._profile["safety"]
            return (
                s.get("max_pulse_us",  self.ABS_MAX_PULSE_US),
                s.get("max_freq_hz",   self.ABS_MAX_FREQ_HZ),
            )
        return self.ABS_MAX_PULSE_US, self.ABS_MAX_FREQ_HZ

    def validate_pulse(self, us: int) -> tuple[bool, int, str]:
        max_pw, _ = self._profile_limits()
        clamped   = max(self.ABS_MIN_PULSE_US, min(int(us), min(max_pw, self.ABS_MAX_PULSE_US)))
        if clamped != us:
            return False, clamped, f"Pulse clamped {us}→{clamped} µs (limit {max_pw} µs)"
        return True, clamped, ""

    def validate_freq(self, hz: int) -> tuple[bool, int, str]:
        _, max_f  = self._profile_limits()
        clamped   = max(self.ABS_MIN_FREQ_HZ, min(int(hz), min(max_f, self.ABS_MAX_FREQ_HZ)))
        if clamped != hz:
            return False, clamped, f"Freq clamped {hz}→{clamped} Hz (limit {max_f} Hz)"
        return True, clamped, ""

    def validate_delay(self, deg: int) -> tuple[bool, int, str]:
        clamped = max(self.ABS_MIN_DELAY_DEG, min(int(deg), self.ABS_MAX_DELAY_DEG))
        if clamped != deg:
            return False, clamped, f"Delay clamped {deg}→{clamped}°"
        return True, clamped, ""


# ══════════════════════════════════════════════════════════════════════
#  SESSION LOGGER
# ══════════════════════════════════════════════════════════════════════
_LOG_PATH = Path.home() / "Desktop" / "injector_sessions.csv"

class SessionLogger:
    """Append-only CSV log of every test session."""

    _HEADER = [
        "timestamp", "injector_id", "brand", "model",
        "mode", "pulse_us", "freq_hz", "delay_deg",
        "duration_s", "total_pulses", "max_pressure_bar", "avg_pkt_s"
    ]

    def __init__(self):
        try:
            _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            if not _LOG_PATH.exists():
                with open(_LOG_PATH, "w", newline="", encoding="utf-8") as f:
                    _csv.writer(f).writerow(self._HEADER)
        except Exception as e:
            logging.warning(f"Session log initialization failed: {e}")

    def log(self, row: dict):
        try:
            with open(_LOG_PATH, "a", newline="", encoding="utf-8") as f:
                w = _csv.writer(f)
                w.writerow([row.get(k, "") for k in self._HEADER])
        except Exception as e:
            logging.warning(f"Session log write failed: {e}")


# ══════════════════════════════════════════════════════════════════════
#  SERIAL WORKER
# ══════════════════════════════════════════════════════════════════════
class SerialWorker(QObject):
    data_received     = pyqtSignal(str)
    error_occurred    = pyqtSignal(str)
    connection_status = pyqtSignal(bool)
    packet_tick       = pyqtSignal(int)   # packets received in last second
    _cmd              = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.port          = None
        self.is_running    = False
        self._keep_running = True
        self._last_port    = ''
        self._last_baud    = 115200
        self._pkt_buf      = 0          # packet counter (reset each second)
        self._pkt_tick_t   = time.time()
        self._cmd.connect(self._write)

    def connect_device(self, port, baud):
        try:
            # Open the port WITHOUT toggling DTR/RTS — otherwise the ESP32
            # would reset on connect and the mode-picker replay commands
            # (MODE PUMP, MV_ENABLE ON, ...) would land during boot and be
            # lost. Only when a reset already happened (first-ever open on
            # a fresh boot) do we still wait a moment for readiness.
            p = serial.Serial()
            p.port     = port
            p.baudrate = baud
            p.timeout  = 0.1
            p.dtr      = None    # do NOT touch DTR
            p.rts      = None    # do NOT touch RTS
            p.open()
            # brief settle so any pending banner from the ESP32 side drains,
            # then flush both directions — clean slate for the auto-prime.
            import time as _t; _t.sleep(0.3)
            try:
                p.reset_input_buffer(); p.reset_output_buffer()
            except Exception:
                pass
            self.port       = p
            self.is_running = True
            self._last_port = port
            self._last_baud = baud
            self.connection_status.emit(True)
        except Exception as e:
            self.error_occurred.emit(str(e))
            self.connection_status.emit(False)

    def reconnect(self):
        """Try to reconnect to the last used port."""
        if self._last_port and not self.is_running:
            self.connect_device(self._last_port, self._last_baud)

    def disconnect_device(self):
        self.is_running = False
        if self.port and self.port.is_open:
            self.port.close()
        self.connection_status.emit(False)

    def read_loop(self):
        while self._keep_running:
            if self.is_running and self.port and self.port.is_open:
                try:
                    latest = None
                    while self.port.in_waiting > 0:
                        raw = self.port.readline().decode('utf-8', errors='ignore').strip()
                        if not raw:
                            continue
                        if 'P:' in raw:
                            latest = raw
                            self._pkt_buf += 1
                        else:
                            self.data_received.emit(raw)
                    if latest:
                        self.data_received.emit(latest)
                    # emit packet rate once per second
                    now = time.time()
                    if now - self._pkt_tick_t >= 1.0:
                        self.packet_tick.emit(self._pkt_buf)
                        self._pkt_buf    = 0
                        self._pkt_tick_t = now
                except Exception as e:
                    self.error_occurred.emit(f"Lost: {e}")
                    self.disconnect_device()
            time.sleep(0.010)

    def send_command(self, cmd):
        # Direct write — the previous signal indirection sometimes dropped
        # commands issued from the connect callback because the queued signal
        # wasn't delivered before the next code ran. Direct call is safe here
        # because only the main (GUI) thread ever calls send_command.
        self._write(cmd)

    def _write(self, cmd):
        if self.port and self.port.is_open:
            try:
                self.port.write(f"{cmd}\n".encode())
                logging.info(f"TX: {cmd}")
            except Exception as e:
                self.error_occurred.emit(f"Write: {e}")


def _find_esp32_port(baud=115200):
    """Return the first serial port that answers the ESP32 COILS query."""
    ports = list(serial.tools.list_ports.comports())
    esp32_usb_ids = {(0x303A, None), (0x10C4, 0xEA60), (0x1A86, 0x7523),
                     (0x0403, 0x6001)}

    def priority(info):
        usb_id = (info.vid, info.pid)
        description = f"{info.description} {info.manufacturer} {info.product}".lower()
        return (0 if usb_id in esp32_usb_ids or "esp32" in description else 1,
                info.device)

    for info in sorted(ports, key=priority):
        probe = None
        try:
            probe = serial.Serial()
            probe.port = info.device
            probe.baudrate = baud
            probe.timeout = 0.2
            probe.dsrdtr = False
            probe.rtscts = False
            probe.dtr = None
            probe.rts = None
            probe.open()
            probe.reset_input_buffer()
            probe.write(b"COILS\n")
            deadline = time.time() + 0.8
            while time.time() < deadline:
                line = probe.readline().decode("utf-8", errors="ignore").strip()
                if line.startswith("COILS:"):
                    return info.device
        except (OSError, serial.SerialException):
            pass
        finally:
            if probe and probe.is_open:
                probe.close()
    return None


# ══════════════════════════════════════════════════════════════════════
#  MAIN WINDOW
# ══════════════════════════════════════════════════════════════════════
class DieselDashboard(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("INJECTOR PRO  ·  Diesel Injection Test System")
        self.resize(1400, 860)
        self.setMinimumSize(0, 0)
        self.setStyleSheet(STYLE_DARK)
        self._language = "en"

        # ── buffers ───────────────────────────────────────────────────
        self.pressure_buf = deque([0.0] * N_SAMPLES, maxlen=N_SAMPLES)
        self.inj_buf      = deque([0.0] * N_SAMPLES, maxlen=N_SAMPLES)
        self.cam_buf      = deque([0.0] * N_SAMPLES, maxlen=N_SAMPLES)

        # ── state ─────────────────────────────────────────────────────
        self.total_pulses    = 0
        self.graph_paused    = False   # stops data buffering (on STOP cmd)
        self._display_frozen = False   # freezes graph display only (Feature 3)
        self._graph_dirty    = False
        self._mode_id        = 0
        self._dark_mode      = True    # Feature 5 — default: Dark Mode

        # ── Pressure filter state ─────────────────────────────────────
        self._p_vx4_ema = 0.0   # EMA slow (alpha=0.02) → LCD display
        self._p_graph   = 0.0   # EMA fast (alpha=0.15) → graph dynamics
        self._p_ema_raw = 0.0   # latest raw VX4 mV (debug display)
        self._rpm_ema     = 0.0
        self._rpm_win     = deque(maxlen=25)   # median window — rejects EMI spikes
        # ── Divisors: load persisted values (QSettings = Qt's localStorage) ──
        # Windows: HKCU\Software\DIT3000\InjectorPro. Falls back to the
        # module defaults on first run or if the stored value is invalid.
        from PyQt6.QtCore import QSettings
        self._settings = QSettings("DIT3000", "InjectorPro")
        try:
            self._rpm_divisor = float(self._settings.value("rpm_divisor", RPM_DIVISOR))
        except (TypeError, ValueError):
            self._rpm_divisor = RPM_DIVISOR
        try:
            self._pressure_divisor = float(self._settings.value("pressure_divisor", PRESSURE_DIVISOR))
        except (TypeError, ValueError):
            self._pressure_divisor = PRESSURE_DIVISOR
        self._inj_ema     = 0.0
        self._inj_win     = deque(maxlen=20)   # 20 × 10ms = 200ms sliding window

        # ── pulse hold ────────────────────────────────────────────────
        self._inj_hold    = 0
        self._cam_hold    = 0
        self._pressure_ema = 0.0   # EMA accumulator for slew-rate limiter

        # ── LCD snapshot (updated at 30fps) ───────────────────────────
        self._snap_p = 0.0
        self._snap_r = 0
        self._snap_a = 0
        self._snap_i = 0.0
        self._snap_d = 0

        # ── Feature 4: alarm state ────────────────────────────────────
        self._blink_state  = False
        self._p_alarm      = False
        self._r_alarm      = False
        self._alarm_timer  = QTimer()
        self._alarm_timer.timeout.connect(self._blink_tick)
        self._alarm_timer.start(420)

        # ── Session tracking ──────────────────────────────────────────
        self._session_start    = None        # datetime when START pressed
        self._session_elapsed  = 0           # seconds elapsed this session
        self._auto_stop_secs   = 0           # 0 = disabled
        self._session_timer    = QTimer()
        self._session_timer.timeout.connect(self._session_tick)
        self._session_timer.start(1000)      # 1 Hz tick

        # ── Watchdog — detect stale / lost connection ─────────────────
        self._last_data_time   = 0.0         # epoch of last good packet
        self._watchdog_stale   = False
        self._watchdog_timer   = QTimer()
        self._watchdog_timer.timeout.connect(self._watchdog_tick)
        self._watchdog_timer.start(2000)     # check every 2 s

        # ── Auto-reconnect ────────────────────────────────────────────
        self._auto_reconnect   = False
        self._reconnect_timer  = QTimer()
        self._reconnect_timer.timeout.connect(self._try_reconnect)
        self._reconnect_timer.start(4000)    # attempt every 4 s

        # ── Packet rate ───────────────────────────────────────────────
        self._pkt_rate         = 0           # packets/s from worker

        # ── Injector profile system ───────────────────────────────────
        self._injector_db      = InjectorDatabase()
        self._safety           = SafetyValidator()
        self._session_logger   = SessionLogger()
        self._active_profile   = None        # currently loaded profile dict
        self._active_mode      = "Full Load" # last selected test mode
        self._max_pressure     = 0.0         # peak pressure this session
        # ── Session time-series statistics ───────────────────────────
        self._min_pressure     = None        # lowest pressure seen (BAR)
        self._sum_pressure     = 0.0         # running sum → average
        self._cnt_pressure     = 0           # sample count
        self._sum_rpm          = 0.0
        self._cnt_rpm          = 0
        self._max_rpm          = 0           # peak RPM this session

        # ── serial ────────────────────────────────────────────────────
        self.thread = QThread()
        self.worker = SerialWorker()
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.read_loop)
        self.worker.data_received.connect(self._on_data)
        self.worker.error_occurred.connect(lambda m: logging.error(m))
        self.worker.connection_status.connect(self._on_conn)
        self.worker.connection_status.connect(
            lambda ok: QTimer.singleShot(700, self._sync) if ok else None)
        self.worker.packet_tick.connect(self._on_pkt_tick)
        self.thread.start()

        self._build_ui()
        self._apply_theme_widgets()          # sync all inline styles with startup mode
        QApplication.processEvents()         # force Qt to repaint with new styles

        self._port_timer = QTimer()
        self._port_timer.timeout.connect(self._refresh_ports)
        self._port_timer.start(2000)
        self._refresh_ports()
        QTimer.singleShot(250, self._auto_connect_esp32)

        self._graph_timer = QTimer()
        self._graph_timer.timeout.connect(self._tick)
        self._graph_timer.start(1000 // GRAPH_FPS)

        self._setup_shortcuts()

    def _display_text(self, text: str) -> str:
        """Translate an exact display term or its known status fragments."""
        if not text:
            return text
        catalog = UI_TRANSLATIONS
        for key, english in catalog["en"].items():
            arabic = catalog["ar"].get(key, english)
            if text == english or text == arabic:
                return catalog[self._language].get(key, english)

        translated = text
        pairs = []
        for key, english in catalog["en"].items():
            arabic = catalog["ar"].get(key, english)
            if english != arabic:
                pairs.append((english, arabic, key))
        for english, arabic, key in sorted(pairs, key=lambda pair: len(pair[0]), reverse=True):
            source = english if self._language == "ar" else arabic
            target = arabic if self._language == "ar" else english
            if source in translated:
                translated = translated.replace(source, target)
        return translated

    def _refresh_language(self):
        """Refresh visible display text while preserving internal widget data."""
        for widget in [self, *self.findChildren(QWidget)]:
            class_name = widget.__class__.__name__
            if class_name == "QGroupBox":
                widget.setTitle(self._display_text(widget.title()))
            elif class_name in {"QLabel", "QPushButton", "QRadioButton", "QCheckBox", "QToolButton"}:
                widget.setText(self._display_text(widget.text()))
            if class_name == "QLineEdit":
                widget.setPlaceholderText(self._display_text(widget.placeholderText()))
            if widget.toolTip():
                widget.setToolTip(self._display_text(widget.toolTip()))

            if class_name == "QComboBox":
                for index in range(widget.count()):
                    widget.setItemText(index, self._display_text(widget.itemText(index)))

        if hasattr(self, "_calib_table"):
            header = self._calib_table.horizontalHeader()
            labels = [header.model().headerData(i, Qt.Orientation.Horizontal)
                      for i in range(self._calib_table.columnCount())]
            self._calib_table.setHorizontalHeaderLabels(
                [self._display_text(str(label)) for label in labels])
        if hasattr(self, "language_btn"):
            self.language_btn.setText(UI_TRANSLATIONS[self._language]["language_toggle"])
        direction = (Qt.LayoutDirection.RightToLeft if self._language == "ar"
                     else Qt.LayoutDirection.LeftToRight)
        QApplication.instance().setLayoutDirection(direction)
        self.setLayoutDirection(direction)

    def _toggle_language(self):
        self._language = "ar" if self._language == "en" else "en"
        self._refresh_language()

    # ──────────────────────────────────────────────────────────────────
    #  KEYBOARD SHORTCUTS  (test-bench ergonomics + emergency stop)
    # ──────────────────────────────────────────────────────────────────
    def _setup_shortcuts(self):
        from PyQt6.QtGui import QShortcut, QKeySequence

        def sc(key, slot):
            s = QShortcut(QKeySequence(key), self)
            s.activated.connect(slot)
            return s

        sc("F5",      self._on_start)    # START
        sc("F6",      self._on_stop)     # STOP
        sc("Esc",     self._on_stop)     # emergency STOP
        sc("Ctrl+S",  self._save_pdf)    # save PDF report
        sc("Ctrl+E",  self._export_csv)  # export CSV
        sc("Ctrl+R",  self._sync)        # re-sync params
        sc("Ctrl+L",  self._toggle_theme)  # toggle Light/Dark

        # Surface the shortcuts in tooltips
        self.start_btn.setToolTip("Start injection  ·  F5")
        self.stop_btn.setToolTip("Stop injection  ·  F6 / Esc")
        self.report_btn.setToolTip("Save PDF report  ·  Ctrl+S")
        self.csv_btn.setToolTip("Export CSV  ·  Ctrl+E")
        self.theme_btn.setToolTip("Toggle Light / Dark  ·  Ctrl+L")

    # ──────────────────────────────────────────────────────────────────
    #  UI BUILD
    # ──────────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QWidget(); self.setCentralWidget(root)
        main = QVBoxLayout(root)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        main.addWidget(self._make_header())

        body = QHBoxLayout()
        body.setContentsMargins(12, 10, 12, 12)
        body.setSpacing(12)

        body.addWidget(self._make_left(),  stretch=1)
        body.addWidget(self._make_right(), stretch=3)
        body.setStretch(0, 1)
        body.setStretch(1, 3)

        main.addLayout(body)

    # ──────────────────────────────────────────────────────────────────
    #  HEADER BAR
    # ──────────────────────────────────────────────────────────────────
    def _make_header(self):
        bar = QWidget()
        bar.setFixedHeight(44)
        bar.setStyleSheet(
            f"background:{HEADER}; border-bottom:1px solid {BORDER2};")
        self._header_bar = bar

        h = QHBoxLayout(bar)
        h.setContentsMargins(16, 0, 16, 0)

        logo = QLabel("  INJECTOR PRO")
        logo.setStyleSheet(
            f"color:{PH_GREEN}; font-size:15px; font-weight:bold;"
            f" font-family:monospace; letter-spacing:2px;")

        self.hdr_mode = QLabel("  COMMON RAIL")
        self.hdr_mode.setStyleSheet(
            f"color:{PH_BLUE}; font-size:11px; font-family:monospace; letter-spacing:1px;")

        # ── Mode switch button ────────────────────────────────────────
        self.mode_switch_btn = QPushButton("⇄  CAM BOX")
        self.mode_switch_btn.setFixedHeight(28)
        self.mode_switch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mode_switch_btn.setStyleSheet(f"""
            QPushButton       {{background:#18102A;border:1px solid {PH_PURPLE};
                                color:{PH_PURPLE};padding:0 12px;border-radius:6px;
                                font-size:10px;font-weight:bold;letter-spacing:1px;
                                font-family:monospace;}}
            QPushButton:hover {{background:{PH_PURPLE};color:#FFFFFF;}}
            QPushButton:pressed {{background:#9040C8;color:#FFFFFF;}}
        """)
        self.mode_switch_btn.clicked.connect(self._toggle_mode)

        self.hdr_conn = QLabel("●  DISCONNECTED")
        self.hdr_conn.setStyleSheet(
            f"color:{PH_RED}; font-size:11px; font-family:monospace; letter-spacing:1px;")

        self.hdr_pulses = QLabel("PULSES: 0")
        self.hdr_pulses.setStyleSheet(
            f"color:{TXT_DIM}; font-size:11px; font-family:monospace;")

        # ── Packet rate ───────────────────────────────────────────────
        self.hdr_pkt = QLabel("PKT: — /s")
        self.hdr_pkt.setStyleSheet(
            f"color:{TXT_DIM}; font-size:11px; font-family:monospace;")

        # ── Session elapsed timer ─────────────────────────────────────
        self.hdr_timer = QLabel("⏱  00:00:00")
        self.hdr_timer.setStyleSheet(
            f"color:{TXT_DIM}; font-size:11px; font-family:monospace;")

        # Feature 5 — Theme toggle button
        self.theme_btn = QPushButton("LIGHT MODE")
        self.theme_btn.setFixedHeight(28)
        self.theme_btn.setStyleSheet(f"""
            QPushButton       {{background:{BORDER};color:{TXT_SEC};
                                border:1px solid {BORDER2};border-radius:6px;
                                font-size:10px;padding:0 10px;font-weight:500;}}
            QPushButton:hover {{background:{BORDER2};color:{TXT_PRI};border-color:{PH_BLUE};}}
            QPushButton:pressed {{background:{BG};color:{TXT_PRI};}}
        """)
        self.theme_btn.clicked.connect(self._toggle_theme)

        self.language_btn = QPushButton(UI_TRANSLATIONS[self._language]["language_toggle"])
        self.language_btn.setFixedHeight(28)
        self.language_btn.setToolTip("Toggle Arabic / English")
        self.language_btn.setStyleSheet(f"""
            QPushButton {{background:{BORDER};color:{TXT_SEC};
                          border:1px solid {BORDER2};border-radius:6px;
                          font-size:10px;padding:0 10px;font-weight:600;}}
            QPushButton:hover {{background:{BORDER2};color:{TXT_PRI};border-color:{PH_GREEN};}}
        """)
        self.language_btn.clicked.connect(self._toggle_language)

        h.addWidget(logo)
        h.addSpacing(30)
        h.addWidget(self.hdr_mode)
        h.addSpacing(10)
        h.addWidget(self.mode_switch_btn)
        h.addStretch()
        h.addWidget(self.hdr_timer)
        h.addSpacing(20)
        h.addWidget(self._vsep())
        h.addSpacing(20)
        h.addWidget(self.hdr_pkt)
        h.addSpacing(20)
        h.addWidget(self._vsep())
        h.addSpacing(20)
        h.addWidget(self.hdr_pulses)
        h.addSpacing(20)
        h.addWidget(self._vsep())
        h.addSpacing(10)
        h.addWidget(self.language_btn)
        h.addSpacing(10)
        h.addWidget(self.theme_btn)
        h.addSpacing(10)
        h.addWidget(self._vsep())
        h.addSpacing(20)
        h.addWidget(self.hdr_conn)
        return bar

    # ──────────────────────────────────────────────────────────────────
    #  LEFT CONTROL PANEL
    # ──────────────────────────────────────────────────────────────────
    def _make_left(self):
        # inner widget holds all panels
        inner = QWidget()
        v = QVBoxLayout(inner); v.setSpacing(10); v.setContentsMargins(0, 0, 4, 0)
        v.addWidget(self._panel_conn())
        v.addWidget(self._panel_presets())
        # INJECTION MODE panel is chosen from the startup dialog now — but we
        # still build it (hidden) so `rb_cam`/`rb_custom` and the mode logic
        # they own stay wired up. Keep a reference on self so it isn't GC'd.
        self._hidden_mode_panel = self._panel_mode()
        self._hidden_mode_panel.hide()
        v.addWidget(self._panel_params())
        v.addWidget(self._panel_coils())
        v.addWidget(self._panel_relay())
        v.addWidget(self._panel_actions())
        v.addStretch()

        # wrap in a scroll area so nothing ever hides under the taskbar
        scroll = QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(220)
        scroll.setMaximumWidth(360)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        return scroll

    # ──────────────────────────────────────────────────────────────────
    #  RIGHT DISPLAY PANEL
    # ──────────────────────────────────────────────────────────────────
    def _make_right(self):
        inner = QWidget()
        v = QVBoxLayout(inner); v.setSpacing(8); v.setContentsMargins(0, 0, 0, 0)

        # Row 1: Live measurement meters (BAR / RPM / INJ)
        v.addWidget(self._panel_meters(), stretch=1)

        # Row 3: Main body — calibration table | cylinders
        body = QHBoxLayout(); body.setSpacing(8)
        body.addWidget(self._panel_cylinders(), stretch=2)
        body.addWidget(self._panel_calib_table(), stretch=1)
        v.addLayout(body, stretch=4)
        v.setStretch(0, 1)
        v.setStretch(1, 4)

        return inner

    # ── Calibration table styling (theme-aware) ───────────────────────
    def _calib_table_style(self, dark: bool) -> str:
        if dark:
            bg, txt, grid   = PANEL, TXT_PRI, BG
            hdr_bg, hdr_txt = HEADER, TXT_DIM
            hdr_line        = BORDER2
        else:
            bg, txt, grid   = '#FFFFFF', '#1C1C1E', '#E0E0E6'
            hdr_bg, hdr_txt = '#EBEBF0', '#3A3A4A'
            hdr_line        = '#C7C7CC'
        return f"""
            QTableWidget {{
                background:{bg}; color:{txt}; border:none;
                font-family:Consolas,monospace; font-size:14px;
                gridline-color:{grid};
            }}
            QTableWidget::item {{ padding: 8px 3px; border: none; }}
            QTableWidget::item:selected {{ background:{PH_BLUE}22; color:{txt}; }}
            QHeaderView::section {{
                background:{hdr_bg}; color:{hdr_txt}; border:none;
                font-size:10px; font-weight:bold; letter-spacing:1px;
                padding:6px; border-bottom:1px solid {hdr_line};
            }}
        """

    # ── Calibration table ─────────────────────────────────────────────
    # ══════════════════════════════════════════════════════════════════
    #  INJECTOR PRESETS  (Common Rail calibration table)
    #  A preset is a named collection of test-mode rows. Stored in
    #  `presets_common_rail.json` next to the app. Extra fields the current
    #  table doesn't render (pressure_bar, freq_hz, return_min/max,
    #  leak_limit_bar) are preserved on save/update so nothing gets lost.
    # ══════════════════════════════════════════════════════════════════
    PRESETS_JSON = "presets_common_rail.json"
    PRESET_MODES = ("Idle", "Medium", "Full Load", "CamBox")

    def _presets_path(self) -> str:
        import os, sys
        # Sibling of the running .py (or exe). Kept outside code so the tech
        # can edit / add presets without a rebuild.
        base = os.path.dirname(os.path.abspath(sys.argv[0]))
        return os.path.join(base, self.PRESETS_JSON)

    def _load_presets_json(self):
        import json, os
        self._presets_data = {"version": 1, "presets": []}
        path = self._presets_path()
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self._presets_data = json.load(f)
            except Exception as e:
                logging.warning(f"presets: load failed ({e}) — starting empty")
                self._presets_data = {"version": 1, "presets": []}
        else:
            # first run — write an empty template so the tech can find/edit it
            self._save_presets_json()

    def _save_presets_json(self):
        import json
        try:
            with open(self._presets_path(), "w", encoding="utf-8") as f:
                json.dump(self._presets_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logging.error(f"presets: save failed — {e}")

    def _refresh_preset_combo(self):
        # Placeholder + user-saved presets + all injector_db profiles.
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItem("— pick a preset —", userData=None)
        # ── User-saved presets (from presets_common_rail.json) ──
        user_presets = self._presets_data.get("presets", [])
        if user_presets:
            self.preset_combo.addItem("── Saved Presets ──", userData="__sep__")
            for p in user_presets:
                self.preset_combo.addItem(p.get("name", "(unnamed)"), userData=None)
        # ── injector_db.json profiles ──
        self.preset_combo.addItem("── Injector DB ──", userData="__sep__")
        for p in self._injector_db.profiles:
            label = f"{p.get('brand','')}  —  {p.get('model','')}  [{p.get('type','')}]"
            self.preset_combo.addItem(label, userData=p["id"])
        self.preset_combo.setCurrentIndex(0)
        self.preset_combo.blockSignals(False)

    def _preset_by_name(self, name: str):
        for p in self._presets_data.get("presets", []):
            if p.get("name") == name:
                return p
        return None

    def _on_preset_pick(self, idx: int):
        if idx <= 0:
            return                                    # placeholder, no-op
        pid = self.preset_combo.itemData(idx)
        # Skip separator items
        if pid == "__sep__":
            self.preset_combo.blockSignals(True)
            self.preset_combo.setCurrentIndex(0)
            self.preset_combo.blockSignals(False)
            return
        def _s(v):
            if v is None or v == "": return "—"
            return v
        # ── Load from injector_db.json ──
        if pid:
            db_profile = self._injector_db.by_id(pid)
            if not db_profile:
                return
            self._populate_calib_table(db_profile)
            # Also sync the brand/model combos and injector ID field
            self._select_profile_by_id(pid)
            self._comm_log(f"LOADED DB profile: {db_profile.get('brand')} — {db_profile.get('model')}", PH_BLUE)
            return
        # ── Load from user-saved presets ──
        name = self.preset_combo.currentText()
        preset = self._preset_by_name(name)
        if not preset:
            return
        profile = {"modes": {}}
        for m in self.PRESET_MODES:
            src = preset.get("modes", {}).get(m, {}) or {}
            profile["modes"][m] = {
                "rpm":        _s(src.get("freq_hz")),
                "pulse_us":   _s(src.get("pulse_us")),
                "duration_s": _s(src.get("duration_s")),
                "vol_target": _s(src.get("vol_target")),
                "vol_min":    _s(src.get("vol_min")),
                "vol_max":    _s(src.get("vol_max")),
                "vol_unit":   "ml/1000",
            }
        self._populate_calib_table(profile)
        self._comm_log(f"LOADED preset: {name}", PH_BLUE)

    def _current_table_as_preset_modes(self) -> dict:
        """Read the visible table back into a preset-shaped dict.
           Extra fields (pressure_bar, return_min/max, leak_limit_bar) are
           preserved from the currently-selected preset if any, otherwise
           written as null so the JSON stays a stable shape."""
        t = self._calib_table
        # column indices (matches _populate_calib_table)
        C_NAME, C_RPM, C_PW, C_TIME, C_TGT, C_MIN, C_MAX = 0, 1, 2, 3, 4, 5, 6
        display_to_key = {"Idle": "Idle", "Medium": "Medium",
                          "Full Load": "Full Load", "VE": "CamBox"}
        def num(item):
            if item is None: return None
            s = item.text().strip().replace(",", ".")
            if not s or s == "—": return None
            try:  return float(s)
            except ValueError: return None

        # keep any extras the selected preset already carried
        cur_name = self.preset_combo.currentText()
        cur = self._preset_by_name(cur_name) if self.preset_combo.currentIndex() > 0 else None
        extras_by_mode = {m: (cur.get("modes", {}).get(m, {}) if cur else {})
                          for m in self.PRESET_MODES}

        modes = {}
        for row in range(t.rowCount()):
            disp = t.item(row, C_NAME).text()
            key  = display_to_key.get(disp, disp)
            ex   = extras_by_mode.get(key, {}) or {}
            modes[key] = {
                "pressure_bar":   ex.get("pressure_bar"),
                "freq_hz":        num(t.item(row, C_RPM)),
                "pulse_us":       num(t.item(row, C_PW)),
                "duration_s":     num(t.item(row, C_TIME)),
                "vol_target":     num(t.item(row, C_TGT)),
                "vol_min":        num(t.item(row, C_MIN)),
                "vol_max":        num(t.item(row, C_MAX)),
                "return_min":     ex.get("return_min"),
                "return_max":     ex.get("return_max"),
                "leak_limit_bar": ex.get("leak_limit_bar"),
            }
        return modes

    def _on_preset_save_as(self):
        from PyQt6.QtWidgets import QInputDialog, QMessageBox
        name, ok = QInputDialog.getText(self, "Save Preset",
                                        "Injector model name:")
        name = (name or "").strip()
        if not ok or not name:
            return
        if self._preset_by_name(name):
            r = QMessageBox.question(self, "Overwrite?",
                                     f"A preset named '{name}' already exists. Overwrite?")
            if r != QMessageBox.StandardButton.Yes:
                return
            # Remove the old one before appending fresh
            self._presets_data["presets"] = [
                p for p in self._presets_data["presets"] if p.get("name") != name
            ]
        self._presets_data.setdefault("presets", []).append({
            "name":  name,
            "modes": self._current_table_as_preset_modes(),
        })
        self._save_presets_json()
        self._refresh_preset_combo()
        # select the one we just saved
        i = self.preset_combo.findText(name)
        if i > 0:
            self.preset_combo.blockSignals(True)
            self.preset_combo.setCurrentIndex(i)
            self.preset_combo.blockSignals(False)
        self._comm_log(f"SAVED preset: {name}", PH_GREEN)

    def _on_preset_update(self):
        from PyQt6.QtWidgets import QMessageBox
        if self.preset_combo.currentIndex() <= 0:
            QMessageBox.information(self, "No preset selected",
                                    "Pick a preset from the dropdown first.")
            return
        name = self.preset_combo.currentText()
        p = self._preset_by_name(name)
        if not p:
            return
        p["modes"] = self._current_table_as_preset_modes()
        self._save_presets_json()
        self._comm_log(f"UPDATED preset: {name}", PH_AMBER)

    def _on_preset_delete(self):
        from PyQt6.QtWidgets import QMessageBox
        if self.preset_combo.currentIndex() <= 0:
            QMessageBox.information(self, "No preset selected",
                                    "Pick a preset from the dropdown first.")
            return
        name = self.preset_combo.currentText()
        r = QMessageBox.question(self, "Delete preset?",
                                 f"Delete preset '{name}'?  This cannot be undone.")
        if r != QMessageBox.StandardButton.Yes:
            return
        self._presets_data["presets"] = [
            p for p in self._presets_data.get("presets", []) if p.get("name") != name
        ]
        self._save_presets_json()
        self._refresh_preset_combo()
        # blank the table so the tech doesn't confuse it with the deleted preset
        self._populate_calib_table(None)
        self._comm_log(f"DELETED preset: {name}", PH_RED)

    def _panel_calib_table(self):
        from PyQt6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView
        box = QGroupBox("CALIBRATION TABLE  —  DELIVERY SPEC  (ml / 1000 pulses)")
        box.setMinimumWidth(0)          # allow shrinking to fit any screen
        v   = QVBoxLayout(box); v.setContentsMargins(6, 6, 6, 6)

        # ── INJECTOR PRESETS toolbar ──────────────────────────────────
        # Load JSON of injector-model presets from disk (creates a blank file
        # on first run). Dropdown lists them; Save-As / Update / Delete keep
        # the JSON in sync so the tech can build up a library over time.
        self._load_presets_json()
        pv = QHBoxLayout(); pv.setSpacing(6); pv.setContentsMargins(0, 0, 0, 4)
        pv.addWidget(self._dim("INJECTOR MODEL"))
        self.preset_combo = QComboBox()
        self.preset_combo.setMinimumWidth(80)
        self.preset_combo.setToolTip("Pick an injector model to auto-fill the calibration table.\n"
                                     "You can still edit any cell after loading.")
        self._refresh_preset_combo()
        self.preset_combo.currentIndexChanged.connect(self._on_preset_pick)
        pv.addWidget(self.preset_combo, stretch=1)

        self.preset_save_btn = QPushButton("SAVE AS…")
        self.preset_save_btn.setToolTip("Save the current table values as a new preset")
        self.preset_save_btn.clicked.connect(self._on_preset_save_as)
        pv.addWidget(self.preset_save_btn)

        self.preset_update_btn = QPushButton("UPDATE")
        self.preset_update_btn.setToolTip("Overwrite the selected preset with the current table values")
        self.preset_update_btn.clicked.connect(self._on_preset_update)
        pv.addWidget(self.preset_update_btn)

        self.preset_delete_btn = QPushButton("DELETE")
        self.preset_delete_btn.setToolTip("Delete the selected preset (confirmation required)")
        self.preset_delete_btn.clicked.connect(self._on_preset_delete)
        pv.addWidget(self.preset_delete_btn)

        # apply theme-neutral styling to the buttons
        for b in (self.preset_save_btn, self.preset_update_btn, self.preset_delete_btn):
            b.setMinimumWidth(0)
            b.setStyleSheet(
                "QPushButton { padding:4px 6px; font-size:10px; font-weight:600;"
                " letter-spacing:1px; border-radius:5px; }"
            )
        v.addLayout(pv)

        cols = ["Test Mode", "RPM", "PW (µs)", "Time (s)",
                "Target (ml)", "Min", "Max", "Unit", "Actual", "Status"]
        self._calib_table = QTableWidget(0, len(cols))
        self._calib_table.setMinimumWidth(0)     # allow layout to shrink table
        self._calib_table.setHorizontalHeaderLabels(cols)
        self._calib_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self._calib_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Fixed)
        self._calib_table.setColumnWidth(0, 110)
        self._calib_table.horizontalHeader().setMinimumSectionSize(0)
        self._calib_table.verticalHeader().setVisible(False)
        self._calib_table.verticalHeader().setDefaultSectionSize(72)
        self._calib_table.setWordWrap(False)
        self._calib_table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked |
            QTableWidget.EditTrigger.SelectedClicked)
        self._calib_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows)
        self._calib_table.setStyleSheet(self._calib_table_style(self._dark_mode))
        # Connect cell changed so technician can enter actual values
        self._calib_table.cellChanged.connect(self._on_calib_actual_changed)
        # Right-click to edit spec values (PIN protected)
        self._calib_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._calib_table.customContextMenuRequested.connect(self._table_context_menu)
        self._dev_unlocked = False   # session-level unlock cache
        v.addWidget(self._calib_table)

        # Populate with default empty rows
        self._populate_calib_table(None)
        return box

    def _populate_calib_table(self, profile: dict | None):
        from PyQt6.QtWidgets import QTableWidgetItem
        t = self._calib_table
        t.blockSignals(True)
        t.setRowCount(0)

        mode_names = ["Idle", "Medium", "Full Load", "CamBox"]
        modes = profile.get("modes", {}) if profile else {}

        display_names = {
            "Idle":      "Idle",
            "Medium":    "Medium",
            "Full Load": "Full Load",
            "CamBox":    "VE",
        }

        if self._dark_mode:
            row_colors = {
                "Idle":      "#0A1820",
                "Medium":    "#0A1808",
                "Full Load": "#1A0808",
                "CamBox":    "#100A20",
            }
            default_bg  = PANEL
            default_txt = TXT_PRI
        else:
            row_colors = {
                "Idle":      "#EAF4FA",
                "Medium":    "#EDF7E8",
                "Full Load": "#FBECEC",
                "CamBox":    "#F1EBFA",
            }
            default_bg  = "#FFFFFF"
            default_txt = "#1C1C1E"

        for mname in mode_names:
            mp = modes.get(mname, {})
            dname = display_names.get(mname, mname)
            row_idx = t.rowCount()
            t.insertRow(row_idx)

            def cell(txt, editable=False, color=None):
                item = QTableWidgetItem(str(txt))
                if not editable:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setForeground(QColor(color if color else default_txt))
                bg = QColor(row_colors.get(mname, default_bg))
                item.setBackground(bg)
                return item

            rpm  = mp.get("rpm", "—")
            pw   = mp.get("pulse_us", "—")
            dur  = mp.get("duration_s", "—")
            tgt  = mp.get("vol_target", "—")
            lo   = mp.get("vol_min", "—")
            hi   = mp.get("vol_max", "—")

            name_item = cell(dname, color=PH_CYAN)
            name_item.setFont(QFont("Consolas", 18, QFont.Weight.Bold))
            t.setItem(row_idx, 0, name_item)
            # spec columns are now editable so the tech can tweak a preset in-place
            t.setItem(row_idx, 1, cell(str(rpm) if rpm != "—" else "—", editable=True, color=PH_PURPLE))
            t.setItem(row_idx, 2, cell(str(pw)  if pw  != "—" else "—", editable=True, color=PH_AMBER))
            t.setItem(row_idx, 3, cell(str(dur) if dur != "—" else "—", editable=True, color=TXT_SEC))
            t.setItem(row_idx, 4, cell(f"{tgt}" if tgt != "—" else "—", editable=True, color=PH_GREEN))
            t.setItem(row_idx, 5, cell(f"{lo}"  if lo  != "—" else "—", editable=True))
            t.setItem(row_idx, 6, cell(f"{hi}"  if hi  != "—" else "—", editable=True))
            t.setItem(row_idx, 7, cell("ml/1k"))
            t.setItem(row_idx, 8, cell("", editable=True))   # Actual — editable
            t.setItem(row_idx, 9, cell("—"))                  # Status

        t.blockSignals(False)

    def _on_calib_actual_changed(self, row, col):
        """When technician enters actual measurement, update status + cylinders."""
        if col != 8:   # only the Actual column
            return
        t   = self._calib_table
        try:
            actual = float(t.item(row, 8).text().replace(",", "."))
        except (ValueError, AttributeError):
            t.item(row, 9).setText("—")
            return
        try:
            lo  = float(t.item(row, 5).text())
            hi  = float(t.item(row, 6).text())
            ok = lo <= actual <= hi
            status = "✓  PASS" if ok else "✗  FAIL"
            color  = PH_GREEN  if ok else PH_RED
            status_item = t.item(row, 9)
            status_item.setText(status)
            status_item.setForeground(QColor(color))
            # Update the corresponding cylinder gauge
            mode_name = t.item(row, 0).text()
            cyl_key = "CamBox" if mode_name == "VE" else mode_name
            if hasattr(self, '_cylinders') and cyl_key in self._cylinders:
                self._cylinders[cyl_key].set_actual(actual)
        except (ValueError, AttributeError):
            pass

    # ── Cylinder gauges panel ─────────────────────────────────────────
    def _panel_cylinders(self):
        box = QGroupBox("Q INJECT  —  ml")
        h   = QHBoxLayout(box); h.setSpacing(4); h.setContentsMargins(4, 4, 4, 4)

        self._cylinders = {}
        mode_colors = {
            "Idle":      PH_CYAN,
            "Medium":    PH_GREEN,
            "Full Load": PH_AMBER,
            "CamBox":    PH_PURPLE,
        }
        gauge_labels = {
            "Idle":      "Idle",
            "Medium":    "Medium",
            "Full Load": "Full Load",
            "CamBox":    "VE",
        }
        for mname, color in mode_colors.items():
            cg = CylinderGauge(
                label=gauge_labels.get(mname, mname), unit="ml",
                target=0.0, low=0.0, high=5.0, scale_max=25.0
            )
            self._cylinders[mname] = cg
            h.addWidget(cg, stretch=1)
        box.setMinimumWidth(0)
        return box

    def _refresh_cylinders(self, profile: dict | None):
        """Update cylinder gauges from the loaded profile."""
        if not hasattr(self, '_cylinders'):
            return
        modes = profile.get("modes", {}) if profile else {}
        for mname, cg in self._cylinders.items():
            mp = modes.get(mname, {})
            tgt = mp.get("vol_target", 0.0)
            lo  = mp.get("vol_min",    0.0)
            hi  = mp.get("vol_max",    5.0)
            scale = max(hi * 1.3, tgt * 1.6, 5.0)
            cg.set_spec(tgt, lo, hi, scale)

    # ── Mini oscilloscope (3 small graphs) ───────────────────────────
    def _panel_mini_graphs(self):
        box = QGroupBox("WAVEFORM")
        v   = QHBoxLayout(box); v.setContentsMargins(4, 4, 4, 4); v.setSpacing(4)

        def mini(color, label):
            glw = pg.GraphicsLayoutWidget()
            glw.setBackground(G_BG)
            glw.setStyleSheet(
                f"border:1px solid {color}30; border-radius:4px;")
            p = glw.addPlot()
            p.hideAxis('bottom')
            p.getAxis('left').setTextPen(pg.mkPen(color=TXT_DIM))
            p.getAxis('left').setWidth(32)
            p.getAxis('left').setPen(pg.mkPen(color=BORDER))
            p.setLabel('left', label, color=color,
                       **{'font-size': '7pt'})
            p.setMenuEnabled(False)
            p.setMouseEnabled(False, False)
            curve = p.plot(pen=pg.mkPen(color=color, width=1))
            glw.setFixedHeight(50)
            return glw, curve

        self.glw_p, self.curve_p = mini(G_AMBER, "BAR")
        self.glw_i, self.curve_i = mini(G_GREEN, "INJ")
        self.glw_c, self.curve_c = mini(G_BLUE,  "CAM")

        # Override pyqtgraph's large default sizeHint — allow equal stretch
        for glw in (self.glw_p, self.glw_i, self.glw_c):
            glw.setMinimumWidth(50)

        v.addWidget(self.glw_p, stretch=1)
        v.addWidget(self.glw_i, stretch=1)
        v.addWidget(self.glw_c, stretch=1)

        # Freeze button
        from PyQt6.QtWidgets import QHBoxLayout as QHL
        row = QWidget(); rh = QHL(row); rh.setContentsMargins(0,0,0,0)
        self.freeze_btn = QPushButton("FREEZE")
        self.freeze_btn.setCheckable(True)
        self.freeze_btn.setFixedHeight(22)
        self.freeze_btn.setStyleSheet(f"""
            QPushButton         {{background:{BORDER};color:{PH_BLUE};
                                  border:1px solid {BORDER2};border-radius:4px;
                                  font-size:9px;padding:0 8px;}}
            QPushButton:checked {{background:#241E08;color:{PH_AMBER};
                                  border-color:{PH_AMBER};}}
        """)
        self.freeze_btn.toggled.connect(self._toggle_freeze)
        self._freeze_status = QLabel("LIVE")
        self._freeze_status.setStyleSheet(
            f"color:{PH_GREEN}; font-size:9px; font-family:monospace;")
        rh.addWidget(self.freeze_btn)
        rh.addWidget(self._freeze_status)
        rh.addStretch()
        v.addWidget(row)
        return box

    # Keep old _panel_scope as alias so PDF report and other references don't break
    def _panel_scope(self):
        return self._panel_mini_graphs()

    # ── Communication log widget ───────────────────────────────────────
    def _comm_log(self, msg: str, color: str = None):
        pass

    # ── connection ────────────────────────────────────────────────────
    def _panel_conn(self):
        box = QGroupBox("CONNECTION")
        g   = QGridLayout(box); g.setSpacing(8)

        g.addWidget(self._dim("PORT"), 0, 0)
        self.port_combo = QComboBox()
        g.addWidget(self.port_combo, 0, 1)

        g.addWidget(self._dim("BAUD"), 1, 0)
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["115200", "57600", "9600"])
        g.addWidget(self.baud_combo, 1, 1)

        self.conn_btn = QPushButton("CONNECT")
        self._style_conn_btn(connected=False)
        self.conn_btn.clicked.connect(self._toggle_conn)
        g.addWidget(self.conn_btn, 2, 0, 1, 2)

        self.conn_lbl = QLabel("●  DISCONNECTED")
        self.conn_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.conn_lbl.setStyleSheet(
            f"color:{PH_RED}; font-weight:bold; font-size:11px; font-family:monospace;")
        g.addWidget(self.conn_lbl, 3, 0, 1, 2)

        # ── Auto-reconnect checkbox ───────────────────────────────────
        self.autoreconn_cb = QCheckBox("Auto-Reconnect")
        self.autoreconn_cb.setStyleSheet(
            f"color:{TXT_SEC}; font-size:10px;")
        self.autoreconn_cb.toggled.connect(
            lambda v: setattr(self, '_auto_reconnect', v))
        g.addWidget(self.autoreconn_cb, 4, 0, 1, 2)

        # ── Injector ID field ─────────────────────────────────────────
        g.addWidget(self._dim("INJECTOR ID"), 5, 0)
        self.inj_id_edit = QLineEdit()
        self.inj_id_edit.setPlaceholderText("e.g. 0445110xxx  (Enter to lookup)")
        self.inj_id_edit.setMaxLength(40)
        self.inj_id_edit.setStyleSheet(
            f"background:{BORDER}; border:1px solid {BORDER2}; border-radius:5px;"
            f" padding:4px 8px; color:{TXT_PRI}; font-family:monospace; font-size:11px;")
        self.inj_id_edit.returnPressed.connect(self._on_injector_id_entered)
        g.addWidget(self.inj_id_edit, 5, 1)
        return box

    # ── Injector Profile System ────────────────────────────────────────
    def _panel_presets(self):
        box = QGroupBox("INJECTOR PROFILE")
        g   = QGridLayout(box); g.setSpacing(6)

        # ── Search bar + ADD button ───────────────────────────────────
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("🔍  Search brand / model...")
        self._search_edit.setStyleSheet(f"""
            QLineEdit {{
                background:{BORDER}; color:{TXT_PRI};
                border:1px solid {BORDER2}; border-radius:6px;
                padding:4px 8px; font-size:11px;
            }}
            QLineEdit:focus {{ border-color:{PH_BLUE}; }}
        """)
        self._search_edit.textChanged.connect(self._on_search_changed)

        self._add_btn = QPushButton("+ ADD")
        self._add_btn.setFixedWidth(60)
        self._add_btn.setStyleSheet(f"""
            QPushButton       {{background:#081428;color:{PH_BLUE};
                                border:1px solid #102248;border-radius:6px;
                                font-size:11px;font-weight:600;padding:4px;}}
            QPushButton:hover {{background:#102248;color:{TXT_PRI};border-color:{PH_BLUE};}}
            QPushButton:pressed {{background:#050C18;}}
        """)
        self._add_btn.clicked.connect(self._on_add_profile)

        search_row = QHBoxLayout(); search_row.setSpacing(4)
        search_row.addWidget(self._search_edit)
        search_row.addWidget(self._add_btn)
        g.addLayout(search_row, 0, 0, 1, 2)

        # Brand selector
        g.addWidget(self._dim("BRAND"), 1, 0)
        self.brand_combo = QComboBox()
        self.brand_combo.addItem("— Select Brand —")
        self.brand_combo.addItems(self._injector_db.brands())
        self.brand_combo.currentTextChanged.connect(self._on_brand_change)
        g.addWidget(self.brand_combo, 1, 1)

        # Model selector
        g.addWidget(self._dim("MODEL"), 2, 0)
        self.model_combo = QComboBox()
        self.model_combo.addItem("— Select Model —")
        self.model_combo.currentTextChanged.connect(self._on_model_change)
        self.model_combo.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.model_combo.customContextMenuRequested.connect(self._model_context_menu)
        g.addWidget(self.model_combo, 2, 1)

        # Test mode selector
        g.addWidget(self._dim("TEST MODE"), 3, 0)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Full Load", "Idle", "Medium", "VE"])
        self.mode_combo.currentTextChanged.connect(self._on_mode_combo_change)
        g.addWidget(self.mode_combo, 3, 1)

        # CamBox sub-mode selector (visible only when CamBox selected)
        g.addWidget(self._dim("CAM PROFILE"), 4, 0)
        self.cambox_combo = QComboBox()
        cb_names = list(self._injector_db.cambox_profiles().keys())
        self.cambox_combo.addItems(cb_names if cb_names else ["Idle"])
        self.cambox_combo.currentTextChanged.connect(self._on_cambox_profile_change)
        g.addWidget(self.cambox_combo, 4, 1)
        self._cambox_row_lbl = g.itemAtPosition(4, 0).widget()
        self.cambox_combo.setVisible(False)
        self._cambox_row_lbl.setVisible(False)

        # Target RPM label (reference only — not sent to ESP32)
        self._rpm_target_lbl = QLabel("Target RPM: —")
        self._rpm_target_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._rpm_target_lbl.setStyleSheet(
            f"color:{PH_PURPLE}; font-size:10px; font-family:monospace; padding:1px 0;")
        g.addWidget(self._rpm_target_lbl, 5, 0, 1, 2)

        # Profile info card
        self._profile_info = QLabel("No profile loaded")
        self._profile_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._profile_info.setWordWrap(True)
        self._profile_info.setStyleSheet(
            f"color:{TXT_DIM}; font-size:9px; font-family:monospace;"
            f" padding:4px; border:1px solid {BORDER}; border-radius:4px;")
        g.addWidget(self._profile_info, 6, 0, 1, 2)

        # Safety limits badge
        self._safety_lbl = QLabel("")
        self._safety_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._safety_lbl.setStyleSheet(
            f"color:{PH_AMBER}; font-size:9px; font-family:monospace; padding:2px 0;")
        g.addWidget(self._safety_lbl, 7, 0, 1, 2)

        # Keep backward-compat alias for _apply_preset (called from _save_pdf etc.)
        self.preset_combo = self.model_combo

        return box

    # ── mode ──────────────────────────────────────────────────────────
    def _panel_mode(self):
        box = QGroupBox("INJECTION MODE")
        h   = QHBoxLayout(box); h.setSpacing(0)

        self.mode_grp  = QButtonGroup(self)
        self.rb_custom = QRadioButton("Common Rail")
        self.rb_cam    = QRadioButton("CamBox  (Sync)")
        self.rb_custom.setChecked(True)
        self.mode_grp.addButton(self.rb_custom, 0)
        self.mode_grp.addButton(self.rb_cam,    1)
        self.mode_grp.idToggled.connect(
            lambda id, chk: self._on_mode(id) if chk else None)

        h.addWidget(self.rb_custom)
        h.addWidget(self.rb_cam)
        return box

    # ── parameters ────────────────────────────────────────────────────
    def _panel_params(self):
        box = QGroupBox("PARAMETERS")
        g   = QGridLayout(box); g.setSpacing(6)

        def row(lbl_txt, lo, hi, val, step=1):
            lbl = self._dim(lbl_txt)
            sp  = QSpinBox(); sp.setRange(lo, hi); sp.setValue(val); sp.setSingleStep(step)
            sl  = QSlider(Qt.Orientation.Horizontal); sl.setRange(lo, hi); sl.setValue(val)
            sp.valueChanged.connect(sl.setValue)
            sl.valueChanged.connect(sp.setValue)
            return lbl, sp, sl

        self.pw_lbl, self.pw_sp, self.pw_sl = row(
            "PULSE WIDTH (µs)", SafetyValidator.ABS_MIN_PULSE_US,
            SafetyValidator.ABS_MAX_PULSE_US, 1000, 50)
        self.fr_lbl, self.fr_sp, self.fr_sl = row("FREQUENCY (Hz)",     1,  100,   25)
        self.an_lbl, self.an_sp, self.an_sl = row("DELAY ANGLE (°)",    0,   45,    0)

        self.pw_sp.valueChanged.connect(lambda v: self._send_validated(f"w{v}"))
        self.fr_sp.valueChanged.connect(lambda v: self._send_validated(f"f{v}"))
        # Delay angle: send only on slider release to avoid flooding serial
        self.an_sl.sliderReleased.connect(
            lambda: self._send_validated(f"a{self.an_sp.value()}"))
        self.an_sp.editingFinished.connect(
            lambda: self._send_validated(f"a{self.an_sp.value()}"))

        for i, (lbl, sp, sl) in enumerate([
            (self.pw_lbl, self.pw_sp, self.pw_sl),
            (self.fr_lbl, self.fr_sp, self.fr_sl),
            (self.an_lbl, self.an_sp, self.an_sl),
        ]):
            g.addWidget(lbl, i * 2,     0, 1, 2)
            g.addWidget(sp,  i * 2,     2)
            g.addWidget(sl,  i * 2 + 1, 0, 1, 3)

        self.delay_lbl = QLabel("DELAY  —  ms")
        self.delay_lbl.setStyleSheet(
            f"color:{PH_PURPLE}; font-size:11px; font-family:monospace; padding:2px 0;")
        g.addWidget(self.delay_lbl, 6, 0, 1, 3)

        # ── RPM Divisor calibration ───────────────────────────────────
        rpm_div_lbl = self._dim("RPM DIVISOR")
        self.rpm_div_sp = QDoubleSpinBox()
        self.rpm_div_sp.setRange(0.1, 10.0)
        self.rpm_div_sp.setSingleStep(0.01)
        self.rpm_div_sp.setDecimals(2)
        self.rpm_div_sp.setValue(self._rpm_divisor)   # persisted or default
        self.rpm_div_sp.valueChanged.connect(self._on_rpm_divisor)
        g.addWidget(rpm_div_lbl,      7, 0, 1, 2)
        g.addWidget(self.rpm_div_sp,  7, 2)

        # ── Pressure Divisor calibration ──────────────────────────────
        # displayed_bar = raw_bar_from_device / pressure_divisor.
        # Same UI pattern as RPM DIVISOR (persisted in QSettings).
        p_div_lbl = self._dim("PRESSURE DIVISOR")
        self.p_div_sp = QDoubleSpinBox()
        self.p_div_sp.setRange(0.1, 10.0)
        self.p_div_sp.setSingleStep(0.01)
        self.p_div_sp.setDecimals(2)
        self.p_div_sp.setValue(self._pressure_divisor)
        self.p_div_sp.setToolTip(
            "Rail-pressure display divisor.\n"
            "Displayed BAR = raw BAR from the device ÷ this.\n"
            "Also scales TARGET_P: dashboard sends target × divisor so the\n"
            "closed-loop PID acts on TRUE bar. Persisted across restarts.")
        self.p_div_sp.valueChanged.connect(self._on_pressure_divisor)
        g.addWidget(p_div_lbl,     8, 0, 1, 2)
        g.addWidget(self.p_div_sp, 8, 2)

        self._cam_visible(False)
        return box

    # ══════════════════════════════════════════════════════════════════
    #  COILS  —  three independently named / switched Peak & Hold channels
    #
    #  Each box: editable name (persisted to coil_names.json) + status dot
    #  + ON/OFF toggle (→ "COIL n ON|OFF") + FIRE momentary (→ "FIRE n").
    #  The firmware owns the truth: its COILS:<c1>,<c2>,<c3> report re-syncs
    #  the toggles, so the UI cannot drift out of step with the board.
    # ══════════════════════════════════════════════════════════════════
    def _panel_coils(self):
        box = QGroupBox("COILS")
        v   = QVBoxLayout(box); v.setSpacing(6)

        self._coil_names    = load_coil_names()
        self._coil_on       = [False] * COIL_COUNT
        self._coil_running  = [False] * COIL_COUNT
        self._coil_deadline = [None]  * COIL_COUNT   # local run-end (perf_counter)
        self._coil_pcount   = [0]     * COIL_COUNT   # last pulse count from board
        self._coil_prate    = [0.0]   * COIL_COUNT   # measured Hz
        self._coil_prev_pc  = [0]     * COIL_COUNT
        self._coil_prev_pt  = [None]  * COIL_COUNT
        self._coil_led_lit  = [0.0]   * COIL_COUNT   # perf_counter of last blink
        self._coil_frames   = []
        self._coil_edits    = []
        self._coil_dots     = []
        self._coil_pins     = []
        self._coil_toggles  = []
        self._coil_fires    = []
        self._coil_freq_sp  = []
        self._coil_pw_sp    = []
        self._coil_dur_sp   = []
        self._coil_run_btns = []
        self._coil_leds     = []
        self._coil_pulse_lbl = []

        for i in range(COIL_COUNT):
            v.addWidget(self._make_coil_row(i))

        hint = self._dim("RUN = FREE-RUN AT FREQ FOR TIME  ·  FIRE = ONE PULSE")
        hint.setWordWrap(True)
        v.addWidget(hint)

        # 4 Hz timer: run-duration countdown text + LED fade for all coils.
        self._coil_ui_timer = QTimer(self)
        self._coil_ui_timer.setInterval(250)
        self._coil_ui_timer.timeout.connect(self._coil_ui_tick)
        self._coil_ui_timer.start()
        return box

    def _make_coil_row(self, i: int):
        # Coil 1 (index 0) is the fuel-Metering-Valve channel — build a MV
        # panel instead of the injector-pulse row. Coil 2/3 stay untouched.
        if i == 0:
            return self._make_mv_row()

        frame = QWidget()
        fv = QVBoxLayout(frame); fv.setContentsMargins(8, 7, 8, 7); fv.setSpacing(6)

        # ── row 1: status dot + editable name + pin label ──────────────
        top = QHBoxLayout(); top.setSpacing(6)

        dot = QLabel("●")
        dot.setFixedWidth(12)
        self._coil_dots.append(dot)
        top.addWidget(dot)

        edit = QLineEdit(self._coil_names[i])
        edit.setMaxLength(COIL_NAME_MAXLEN)
        edit.setPlaceholderText(COIL_DEFAULT_NAMES[i])
        edit.setToolTip("Click to rename this coil — saved between sessions")
        edit.editingFinished.connect(lambda idx=i: self._on_coil_rename(idx))
        self._coil_edits.append(edit)
        top.addWidget(edit, stretch=1)

        # Own stylesheet (not _dim) — the frame's border would otherwise
        # cascade onto the label and draw a box around the pin name.
        pin = QLabel(COIL_PIN_LABELS[i])
        self._coil_pins.append(pin)
        top.addWidget(pin)
        fv.addLayout(top)

        # ── row 2: ON/OFF toggle + FIRE ────────────────────────────────
        bot = QHBoxLayout(); bot.setSpacing(6)

        tog = QPushButton("OFF")
        tog.setCheckable(True)
        tog.setMinimumHeight(28)
        tog.setToolTip(f"Enable / disable coil {i+1} (COIL {i+1} ON|OFF)")
        tog.toggled.connect(lambda on, idx=i: self._on_coil_toggle(idx, on))
        self._coil_toggles.append(tog)
        bot.addWidget(tog, stretch=2)

        fire = QPushButton("▶  SHOT")
        fire.setMinimumHeight(28)
        fire.setToolTip(f"One STRONG square pulse on coil {i+1} — 100% full HIGH\n"
                        f"for the coil's PW µs (SQFIRE {i+1} <pw>). No Peak & Hold, no chop.")
        fire.clicked.connect(lambda _=False, idx=i: self._on_coil_fire(idx))
        self._coil_fires.append(fire)
        bot.addWidget(fire, stretch=1)
        fv.addLayout(bot)

        # ── row 3: per-coil FREQUENCY + PULSE WIDTH + run DURATION ──────
        p = QGridLayout(); p.setSpacing(4)
        # Coil 2 (index 1) = EUI on GPIO23 → cam-synced, no frequency needed.
        # Hide the FREQ widget but keep the spinbox object so sync/theme code
        # keeps working. PW slides to the left to fill the space.
        freq = QSpinBox()
        freq.setRange(1, 20)          # thermal cap: 20 Hz max
        freq.setValue(10)
        freq.setToolTip(f"Coil {i+1} free-run frequency, 1–20 Hz (CFREQ {i+1} <hz>)")
        freq.valueChanged.connect(lambda hz, idx=i: self._on_coil_freq(idx, hz))
        self._coil_freq_sp.append(freq)
        if i == 1:
            freq.hide()
            p.addWidget(self._dim("PW (µs)"), 0, 0)
            pw_col = 1
        else:
            p.addWidget(self._dim("FREQ (Hz)"), 0, 0)
            p.addWidget(freq, 0, 1)
            p.addWidget(self._dim("PW (µs)"), 0, 2)
            pw_col = 3
        pw = QSpinBox()
        pw.setRange(50, 100000)                     # SQ range (100 % HIGH square)
        pw.setSingleStep(50)
        pw.setValue(1000)
        pw.setToolTip(f"Coil {i+1} SQUARE pulse width — 50 µs .. 100 ms\n"
                      f"(SQFIRE {i+1} <us> / used by SHOT and RUN)")
        pw.valueChanged.connect(lambda us, idx=i: self._on_coil_pw(idx, us))
        self._coil_pw_sp.append(pw)
        p.addWidget(pw, 0, pw_col)

        # (per-coil TIME removed — run duration is set in the shared panel below)
        # keep a headless spinbox so existing _on_coil_run / theme code stays valid
        dur = QSpinBox(); dur.setRange(0, 3600); dur.setValue(0); dur.hide()
        self._coil_dur_sp.append(dur)
        fv.addLayout(p)

        # ── row 4: RUN toggle + live pulse indicator ───────────────────
        r = QHBoxLayout(); r.setSpacing(6)
        run = QPushButton("▶  RUN")
        run.setCheckable(True)
        run.setMinimumHeight(28)
        run.setToolTip(f"Free-run coil {i+1} at its freq for the set time "
                       f"(CRUN {i+1} / CSTOP {i+1})")
        run.toggled.connect(lambda on, idx=i: self._on_coil_run(idx, on))
        self._coil_run_btns.append(run)
        r.addWidget(run, stretch=2)

        led = QLabel("◉")
        led.setFixedWidth(14)
        self._coil_leds.append(led)
        r.addWidget(led)

        plbl = QLabel("0 · 0 Hz")
        self._coil_pulse_lbl.append(plbl)
        r.addWidget(plbl, stretch=1)
        fv.addLayout(r)

        self._coil_frames.append(frame)
        self._style_coil_row(i)
        return frame

    # ══════════════════════════════════════════════════════════════════
    #  METERING VALVE row  (replaces Coil-1 injector row at index 0)
    #  Controls: ENABLE toggle · MODE(MANUAL/PRESSURE) · Duty %(clamped 30)
    #            · Target Pressure(bar) · live readouts (P, duty%, fault)
    #  Talks to the firmware via MV_ENABLE / MV_MODE / MV_DUTY / TARGET_P.
    # ══════════════════════════════════════════════════════════════════
    def _make_mv_row(self):
        i = 0
        frame = QWidget()
        fv = QVBoxLayout(frame); fv.setContentsMargins(8, 7, 8, 7); fv.setSpacing(6)

        # ── row 1: dot + fixed label + pin label ───────────────────────
        top = QHBoxLayout(); top.setSpacing(6)
        dot = QLabel("●"); dot.setFixedWidth(12)
        self._coil_dots.append(dot); top.addWidget(dot)

        edit = QLineEdit("METERING VALVE")
        edit.setReadOnly(True); edit.setMaxLength(COIL_NAME_MAXLEN)
        self._coil_edits.append(edit)
        top.addWidget(edit, stretch=1)

        pin = QLabel("COIL 1 · 12V")
        self._coil_pins.append(pin); top.addWidget(pin)
        fv.addLayout(top)

        # ── row 2: ENABLE toggle + FAULT indicator (replaces OFF/SHOT) ─
        bot = QHBoxLayout(); bot.setSpacing(6)
        tog = QPushButton("DISABLED"); tog.setCheckable(True); tog.setMinimumHeight(28)
        tog.setToolTip("Gate the metering-valve PWM output (MV_ENABLE ON|OFF)")
        tog.toggled.connect(self._on_mv_enable)
        self._coil_toggles.append(tog)
        self.mv_enable_btn = tog
        bot.addWidget(tog, stretch=2)

        self.mv_fault_lbl = QLabel("● FAULT")
        self.mv_fault_lbl.setFixedHeight(28)
        self.mv_fault_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mv_fault_lbl.setToolTip("Latched fault flag from the board (MV_FAULT_CLEAR to clear)")
        self.mv_fault_lbl.mousePressEvent = lambda ev: self.worker.send_command("MV_FAULT_CLEAR")
        self._coil_fires.append(self.mv_fault_lbl)  # keep parallel array happy
        bot.addWidget(self.mv_fault_lbl, stretch=1)
        fv.addLayout(bot)

        # ── row 3: MODE selector (MANUAL / PRESSURE) ───────────────────
        m = QHBoxLayout(); m.setSpacing(6)
        m.addWidget(self._dim("MODE"))
        self.mv_mode_combo = QComboBox()
        self.mv_mode_combo.addItems(["PRESSURE (PID)", "MANUAL (duty %)"])
        self.mv_mode_combo.currentIndexChanged.connect(self._on_mv_mode)
        m.addWidget(self.mv_mode_combo, stretch=1)
        fv.addLayout(m)

        # ── row 4: TARGET (bar in PRESSURE, % in MANUAL) ───────────────
        t = QGridLayout(); t.setSpacing(4)
        t.addWidget(self._dim("TARGET P (bar)"), 0, 0)
        self.mv_target_p = QSpinBox()
        self.mv_target_p.setRange(0, 2000); self.mv_target_p.setValue(0)
        self.mv_target_p.setToolTip("Rail pressure target in REAL bar — closed-loop PID.\n"
                                    "Dashboard scales this by PRESSURE DIVISOR before sending\n"
                                    "TARGET_P so the firmware PID (which sees raw sensor bar)\n"
                                    "converges to the true target.")
        # User types real bar → multiply by divisor so the firmware's raw-bar
        # PID lands on the actual physical pressure the user asked for.
        self.mv_target_p.valueChanged.connect(
            lambda v: self.worker.send_command(
                f"TARGET_P {int(round(v * (self._pressure_divisor or 1.0)))}"))
        t.addWidget(self.mv_target_p, 0, 1)

        t.addWidget(self._dim("DUTY %"), 1, 0)
        self.mv_duty = QSpinBox()
        self.mv_duty.setRange(0, 30); self.mv_duty.setValue(0)
        self.mv_duty.setSuffix(" %")
        self.mv_duty.setToolTip(f"Manual duty override — capped at {30}% for safety (MV_DUTY <pct>)")
        self.mv_duty.valueChanged.connect(
            lambda v: self.worker.send_command(f"MV_DUTY {v}"))
        t.addWidget(self.mv_duty, 1, 1)

        # PWM CARRIER FREQ — the continuous PWM base, not a pulse rate.
        # Live-tunable 100..1000 Hz via MV_FREQ. Duty is preserved.
        t.addWidget(self._dim("PWM FREQ (Hz)"), 2, 0)
        self.mv_freq = QSpinBox()
        self.mv_freq.setRange(100, 1000); self.mv_freq.setValue(200)
        self.mv_freq.setSingleStep(10); self.mv_freq.setSuffix(" Hz")
        self.mv_freq.setToolTip("Metering-valve PWM CARRIER frequency, 100–1000 Hz.\n"
                                "This is the continuous PWM base — not a pulse rate.\n"
                                "Live-tunable; duty is preserved (MV_FREQ <hz>).")
        self.mv_freq.valueChanged.connect(
            lambda v: self.worker.send_command(f"MV_FREQ {v}"))
        t.addWidget(self.mv_freq, 2, 1)
        fv.addLayout(t)

        # ── row 5: live readouts (measured P + current duty + freq) ────
        r = QHBoxLayout(); r.setSpacing(6)
        self.mv_p_lbl    = QLabel("P: — bar")
        self.mv_duty_lbl = QLabel("duty: — %")
        self.mv_freq_lbl = QLabel("f: — Hz")
        r.addWidget(self.mv_p_lbl, stretch=1)
        r.addWidget(self.mv_duty_lbl, stretch=1)
        r.addWidget(self.mv_freq_lbl, stretch=1)
        fv.addLayout(r)

        # ── stub widgets so the parallel per-coil arrays stay valid ────
        # (index 0 must have a freq / pw / dur / run entry; they're hidden)
        stub_f = QSpinBox(); stub_f.setRange(1, 20); stub_f.setValue(10); stub_f.hide()
        stub_pw = QSpinBox(); stub_pw.setRange(50, 100000); stub_pw.setValue(1000); stub_pw.hide()
        stub_dur = QSpinBox(); stub_dur.setRange(0, 3600); stub_dur.setValue(0); stub_dur.hide()
        stub_run = QPushButton(); stub_run.setCheckable(True); stub_run.hide()
        stub_led = QLabel(); stub_led.hide()
        stub_plbl = QLabel(); stub_plbl.hide()
        self._coil_freq_sp.append(stub_f)
        self._coil_pw_sp.append(stub_pw)
        self._coil_dur_sp.append(stub_dur)
        self._coil_run_btns.append(stub_run)
        self._coil_leds.append(stub_led)
        self._coil_pulse_lbl.append(stub_plbl)

        self._coil_frames.append(frame)
        self._style_coil_row(i)
        self._on_mv_mode(0)          # start in PRESSURE mode → hide DUTY row
        return frame

    # ── MV handlers ────────────────────────────────────────────────────
    def _on_mv_enable(self, on: bool):
        self._coil_on[0] = on
        self.mv_enable_btn.setText("ENABLED" if on else "DISABLED")
        self._style_coil_row(0)
        self.worker.send_command(f"MV_ENABLE {'ON' if on else 'OFF'}")
        self._comm_log(f"TX  MV_ENABLE {'ON' if on else 'OFF'}",
                       PH_GREEN if on else PH_AMBER)

    def _on_mv_mode(self, idx: int):
        # 0 = PRESSURE (PID), 1 = MANUAL
        pressure = (idx == 0)
        self.mv_target_p.setEnabled(pressure)
        self.mv_duty.setEnabled(not pressure)
        # visual hint: dim the inactive one
        for w, active in ((self.mv_target_p, pressure),
                          (self.mv_duty,     not pressure)):
            w.setStyleSheet("" if active else "color:#7A7A80;")
        self.worker.send_command(f"MV_MODE {'PRESSURE' if pressure else 'MANUAL'}")

    def _apply_mv_status(self, payload: str):
        """Sync MV widgets from firmware MV:<en>,<mode>,<manual>,<target>,<actual_pct>,<fault>[,<freq_hz>]."""
        try:
            parts = payload.split(',')
            if len(parts) < 6: return
            en = parts[0] == '1'
            mode = parts[1]
            manual = float(parts[2])
            target = float(parts[3])
            actual = float(parts[4])
            fault = parts[5] == '1'
            freq  = int(parts[6]) if len(parts) >= 7 else None
        except (ValueError, IndexError):
            return
        if hasattr(self, 'mv_enable_btn'):
            btn = self.mv_enable_btn
            if btn.isChecked() != en:
                btn.blockSignals(True); btn.setChecked(en); btn.blockSignals(False)
                btn.setText("ENABLED" if en else "DISABLED")
                self._coil_on[0] = en; self._style_coil_row(0)
        if hasattr(self, 'mv_mode_combo'):
            want = 0 if mode.upper().startswith("PRESSURE") else 1
            if self.mv_mode_combo.currentIndex() != want:
                self.mv_mode_combo.blockSignals(True)
                self.mv_mode_combo.setCurrentIndex(want)
                self.mv_mode_combo.blockSignals(False)
        if hasattr(self, 'mv_duty_lbl'):
            self.mv_duty_lbl.setText(f"duty: {actual:.1f} %")
        if freq is not None:
            if hasattr(self, 'mv_freq_lbl'):
                self.mv_freq_lbl.setText(f"f: {freq} Hz")
            if hasattr(self, 'mv_freq') and self.mv_freq.value() != freq:
                self.mv_freq.blockSignals(True)
                self.mv_freq.setValue(freq)
                self.mv_freq.blockSignals(False)
        if hasattr(self, 'mv_fault_lbl'):
            dk = self._dark_mode
            if fault:
                self.mv_fault_lbl.setText("● FAULT")
                self.mv_fault_lbl.setStyleSheet(
                    f"color:#FFFFFF; background:{PH_RED}; border-radius:6px;"
                    f" font-weight:700; letter-spacing:1px; padding:0 8px;")
                self.mv_fault_lbl.setToolTip("Click to clear the fault (MV_FAULT_CLEAR)")
            else:
                self.mv_fault_lbl.setText("● OK")
                self.mv_fault_lbl.setStyleSheet(
                    f"color:{PH_GREEN}; background:{'#0A2218' if dk else '#EAF7EE'};"
                    f" border:1px solid {'#1E5233' if dk else '#BEE3C7'};"
                    f" border-radius:6px; font-weight:700; letter-spacing:1px; padding:0 8px;")

    # ── per-row styling (also the theme-toggle repaint path) ───────────
    def _style_coil_row(self, i: int):
        dk  = self._dark_mode
        on  = self._coil_on[i]

        frame_bg  = PANEL   if dk else '#FFFFFF'
        frame_bdr = BORDER2 if dk else '#E0E0E6'
        # An enabled coil gets a green edge so it reads at a glance.
        if on:
            frame_bdr = PH_GREEN if not dk else '#1E5233'
        self._coil_frames[i].setStyleSheet(
            f"background:{frame_bg}; border:1px solid {frame_bdr}; border-radius:6px;")

        self._coil_edits[i].setStyleSheet(
            f"QLineEdit {{ background:{BORDER if dk else '#F2F2F6'};"
            f" color:{TXT_PRI if dk else '#1A1A1E'};"
            f" border:1px solid {BORDER2 if dk else '#D8D8DE'}; border-radius:5px;"
            f" padding:3px 7px; font-family:monospace; font-size:11px;"
            f" font-weight:600; letter-spacing:1px; }}"
            f"QLineEdit:focus {{ border-color:{PH_BLUE}; }}")

        dot_c = PH_GREEN if on else (TXT_DIM if dk else '#C6C6CC')
        self._coil_dots[i].setStyleSheet(
            f"color:{dot_c}; font-size:13px; border:none; background:transparent;")

        self._coil_pins[i].setStyleSheet(
            f"color:{TXT_DIM if dk else '#9A9AA2'}; font-size:9px; font-weight:bold;"
            f" font-family:monospace; border:none; background:transparent;")

        tog = self._coil_toggles[i]
        if on:
            on_bg    = '#0A2218' if dk else '#DFF5E6'
            on_txt   = PH_GREEN  if dk else '#0E6B2E'
            on_hover = '#163C28' if dk else '#CDEDD8'
            on_press = '#061009' if dk else '#BCE3CA'
            tog.setStyleSheet(f"""
                QPushButton         {{background:{on_bg};color:{on_txt};
                                      border:1px solid {PH_GREEN};border-radius:6px;
                                      font-size:11px;font-weight:700;letter-spacing:1px;}}
                QPushButton:hover   {{background:{on_hover};}}
                QPushButton:pressed {{background:{on_press};}}
            """)
        else:
            off_bg  = '#1A1A1E' if dk else '#EDEDF2'
            off_txt = TXT_SEC   if dk else '#6A6A72'
            off_bdr = BORDER2   if dk else '#D8D8DE'
            tog.setStyleSheet(f"""
                QPushButton         {{background:{off_bg};color:{off_txt};
                                      border:1px solid {off_bdr};border-radius:6px;
                                      font-size:11px;font-weight:700;letter-spacing:1px;}}
                QPushButton:hover   {{border-color:{PH_GREEN};color:{PH_GREEN};}}
                QPushButton:pressed {{background:{off_bdr};}}
            """)

        f_bg    = '#081428' if dk else '#EAF2FF'
        f_bdr   = '#102248' if dk else '#C4DBFF'
        f_hover = '#102248' if dk else '#D3E5FF'
        f_press = '#050C18' if dk else '#BBD6FF'
        f_htxt  = TXT_PRI   if dk else '#0A3F86'
        self._coil_fires[i].setStyleSheet(f"""
            QPushButton         {{background:{f_bg};color:{PH_BLUE};
                                  border:1px solid {f_bdr};
                                  border-radius:6px;font-size:11px;font-weight:600;}}
            QPushButton:hover   {{background:{f_hover};color:{f_htxt};border-color:{PH_BLUE};}}
            QPushButton:pressed {{background:{f_press};color:{f_htxt};}}
        """)

        # ── RUN toggle — cyan when running, neutral when idle ──────────
        run = self._coil_run_btns[i]
        if self._coil_running[i]:
            run.setStyleSheet(f"""
                QPushButton         {{background:{'#08201F' if dk else '#DDF6F4'};
                                      color:{PH_CYAN};
                                      border:1px solid {PH_CYAN};border-radius:6px;
                                      font-size:11px;font-weight:700;letter-spacing:1px;}}
                QPushButton:hover   {{background:{'#0C2E2C' if dk else '#CBEEEB'};}}
            """)
        else:
            run.setStyleSheet(f"""
                QPushButton         {{background:{'#1A1A1E' if dk else '#EDEDF2'};
                                      color:{TXT_SEC if dk else '#6A6A72'};
                                      border:1px solid {BORDER2 if dk else '#D8D8DE'};
                                      border-radius:6px;font-size:11px;font-weight:700;
                                      letter-spacing:1px;}}
                QPushButton:hover   {{border-color:{PH_CYAN};color:{PH_CYAN};}}
            """)

        # ── pulse LED (off state) + count/rate label ──────────────────
        led_off = '#203A38' if dk else '#CFE8E5'
        self._coil_leds[i].setStyleSheet(
            f"color:{led_off}; font-size:13px; border:none; background:transparent;")
        self._coil_pulse_lbl[i].setStyleSheet(
            f"color:{TXT_SEC if dk else '#6A6A72'}; font-size:10px;"
            f" font-family:monospace; border:none; background:transparent;")

        sp_ss = (f"QSpinBox {{ background:{BORDER if dk else '#F2F2F6'};"
                 f" color:{TXT_PRI if dk else '#1A1A1E'};"
                 f" border:1px solid {BORDER2 if dk else '#D8D8DE'}; border-radius:5px;"
                 f" padding:2px 4px; font-family:monospace; font-size:11px; }}")
        self._coil_freq_sp[i].setStyleSheet(sp_ss)
        self._coil_pw_sp[i].setStyleSheet(sp_ss)
        self._coil_dur_sp[i].setStyleSheet(sp_ss)

    # ── coil actions ──────────────────────────────────────────────────
    def _on_coil_toggle(self, i: int, on: bool):
        self._coil_on[i] = on
        self._coil_toggles[i].setText("ON" if on else "OFF")
        self._style_coil_row(i)
        state = "ON" if on else "OFF"
        self.worker.send_command(f"COIL {i+1} {state}")
        self._comm_log(f"TX  COIL {i+1} {state}  ({self._coil_names[i]})",
                       PH_GREEN if on else PH_AMBER)

    def _on_coil_fire(self, i: int):
        # Route through FIRE, not SQFIRE — FIRE honours the SQMODE flag on
        # the firmware side. Boot default is SQMODE=OFF ⇒ proper Peak & Hold
        # (peak + 10 kHz hold chop) so the injector MOSFET is safe. If the
        # tech has flipped `MAXPOWER ON` explicitly for a hard-square test,
        # FIRE will square-drive instead. Same button, respects preference.
        pw = self._coil_pw_sp[i].value()
        self.worker.send_command(f"FIRE {i+1} {pw}")
        self._comm_log(f"TX  FIRE {i+1} {pw}µs  ({self._coil_names[i]})", PH_BLUE)

    def _on_coil_rename(self, i: int):
        txt = self._coil_edits[i].text().strip()[:COIL_NAME_MAXLEN]
        if not txt:                                  # blank reverts to default
            txt = COIL_DEFAULT_NAMES[i]
            self._coil_edits[i].setText(txt)
        if txt == self._coil_names[i]:
            return
        self._coil_names[i] = txt
        save_coil_names(self._coil_names)
        self._coil_toggles[i].setToolTip(
            f"Enable / disable {txt} (COIL {i+1} ON|OFF)")
        self._coil_fires[i].setToolTip(
            f"Single Peak & Hold shot on {txt} (FIRE {i+1})")

    def _apply_coil_mask(self, payload: str):
        """Sync the toggles to the firmware's COILS:<c1>,<c2>,<c3> report."""
        if not hasattr(self, '_coil_toggles'):
            return
        try:
            bits = [int(x) for x in payload.split(',')]
        except ValueError:
            logging.debug(f"bad COILS report: {payload}")
            return
        for i in range(min(COIL_COUNT, len(bits))):
            # Coil 1 is the Metering Valve — its ENABLE state comes from MV:
            # snapshots (see _apply_mv_status), not the COILS: injector mask.
            if i == 0:
                continue
            on  = bool(bits[i])
            tog = self._coil_toggles[i]
            if on == self._coil_on[i] and tog.isChecked() == on:
                continue
            self._coil_on[i] = on
            tog.blockSignals(True)          # board state — do not echo it back
            tog.setChecked(on)
            tog.blockSignals(False)
            tog.setText("ON" if on else "OFF")
            self._style_coil_row(i)

    # ── per-coil frequency / pulse width / run-duration / pulse display ─
    def _on_coil_freq(self, i: int, hz: int):
        self.worker.send_command(f"CFREQ {i+1} {hz}")

    def _on_coil_pw(self, i: int, us: int):
        self.worker.send_command(f"CPW {i+1} {us}")

    def _on_coil_run(self, i: int, on: bool):
        import time as _t
        if on:
            secs = self._coil_dur_sp[i].value()
            ms   = secs * 1000
            self._coil_running[i]  = True
            self._coil_deadline[i] = (_t.perf_counter() + secs) if secs > 0 else None
            self._coil_prev_pc[i]  = 0
            self._coil_prev_pt[i]  = None
            self.worker.send_command(f"CRUN {i+1} {ms}")
            self._comm_log(
                f"TX  CRUN {i+1} @ {self._coil_freq_sp[i].value()}Hz "
                f"for {'∞' if secs==0 else str(secs)+'s'}  ({self._coil_names[i]})",
                PH_CYAN)
        else:
            self._coil_running[i]  = False
            self._coil_deadline[i] = None
            self.worker.send_command(f"CSTOP {i+1}")
            self._comm_log(f"TX  CSTOP {i+1}  ({self._coil_names[i]})", PH_AMBER)
        self._coil_run_btns[i].setText("■  STOP" if on else "▶  RUN")
        self._style_coil_row(i)

    def _apply_coil_info(self, payload: str):
        """Sync freq/pw spinboxes + RUN buttons to
        CINFO:<f1..3>,<pw1..3>,<r1..3> (9 fields)."""
        if not hasattr(self, '_coil_run_btns'):
            return
        try:
            vals = [int(x) for x in payload.split(',')]
        except ValueError:
            logging.debug(f"bad CINFO: {payload}")
            return
        if len(vals) < 3 * COIL_COUNT:
            return
        freqs = vals[0:COIL_COUNT]
        pws   = vals[COIL_COUNT:2*COIL_COUNT]
        runs  = vals[2*COIL_COUNT:3*COIL_COUNT]
        for i in range(COIL_COUNT):
            sp = self._coil_freq_sp[i]
            if sp.value() != freqs[i]:
                sp.blockSignals(True); sp.setValue(freqs[i]); sp.blockSignals(False)
            wsp = self._coil_pw_sp[i]
            if wsp.value() != pws[i]:
                wsp.blockSignals(True); wsp.setValue(pws[i]); wsp.blockSignals(False)
            run_on = bool(runs[i])
            if run_on != self._coil_running[i]:
                self._coil_running[i] = run_on
                btn = self._coil_run_btns[i]
                btn.blockSignals(True); btn.setChecked(run_on); btn.blockSignals(False)
                btn.setText("■  STOP" if run_on else "▶  RUN")
                if not run_on:
                    self._coil_deadline[i] = None
                    self._coil_prate[i]    = 0.0     # rate → 0 once stopped
                    self._coil_prev_pt[i]  = None
                    self._coil_pulse_lbl[i].setText(f"{self._coil_pcount[i]} · 0 Hz")
                self._style_coil_row(i)

    def _apply_coil_pulses(self, payload: str):
        """Live per-coil pulse counts CPULSES:<c1>,<c2>,<c3> — blink + rate."""
        if not hasattr(self, '_coil_leds'):
            return
        import time as _t
        try:
            counts = [int(x) for x in payload.split(',')]
        except ValueError:
            return
        now = _t.perf_counter()
        for i in range(min(COIL_COUNT, len(counts))):
            c = counts[i]
            prev = self._coil_pcount[i]
            if c != prev:                       # new pulses since last report
                self._coil_leds[i].setStyleSheet(
                    f"color:{PH_CYAN}; font-size:13px; border:none; background:transparent;")
                self._coil_led_lit[i] = now
            # measured rate
            if self._coil_prev_pt[i] is not None:
                dt = now - self._coil_prev_pt[i]
                if dt > 0:
                    inst = (c - self._coil_prev_pc[i]) / dt
                    # light smoothing
                    self._coil_prate[i] = 0.6*self._coil_prate[i] + 0.4*inst
            self._coil_prev_pc[i] = c
            self._coil_prev_pt[i] = now
            self._coil_pcount[i]  = c
            self._coil_pulse_lbl[i].setText(f"{c} · {self._coil_prate[i]:.0f} Hz")

    def _coil_ui_tick(self):
        """4 Hz: countdown text on RUN buttons + fade pulse LEDs."""
        if not hasattr(self, '_coil_run_btns'):
            return
        import time as _t
        now = _t.perf_counter()
        led_off = '#203A38' if self._dark_mode else '#CFE8E5'
        for i in range(COIL_COUNT):
            # fade the pulse LED ~150 ms after the last blink
            if self._coil_led_lit[i] and (now - self._coil_led_lit[i]) > 0.15:
                self._coil_led_lit[i] = 0.0
                self._coil_leds[i].setStyleSheet(
                    f"color:{led_off}; font-size:13px; border:none; background:transparent;")
            # run-duration countdown on the button
            if self._coil_running[i] and self._coil_deadline[i] is not None:
                rem = self._coil_deadline[i] - now
                if rem <= 0:
                    self._coil_run_btns[i].setText("■  STOP")
                else:
                    self._coil_run_btns[i].setText(f"■  STOP ({int(rem)+1}s)")

    # ══════════════════════════════════════════════════════════════════
    #  RELAY  —  MANUAL 12 V / 28 V Peak-supply select (GPIO19)
    #
    #  One toggle. OFF → "RELAY OFF" (12 V), ON → "RELAY ON" (28 V). The
    #  operator confirms which physical level is which; the firmware only
    #  holds the commanded state and never switches it per pulse. The board's
    #  RELAY:<0|1> line (boot / change / request) is the source of truth.
    # ══════════════════════════════════════════════════════════════════
    def _panel_relay(self):
        box = QGroupBox("RELAY  ·  PEAK SUPPLY")
        v   = QVBoxLayout(box); v.setSpacing(6)

        self._relay_on = False

        self.relay_btn = QPushButton("OFF  ·  12V")
        self.relay_btn.setCheckable(True)
        self.relay_btn.setMinimumHeight(34)
        self.relay_btn.setToolTip(
            "Manual Peak-supply select (RELAY ON|OFF).\n"
            "OFF = 12 V, ON = 28 V — confirm the mapping on your relay board.")
        self.relay_btn.toggled.connect(self._on_relay_toggle)
        v.addWidget(self.relay_btn)

        hint = self._dim("MANUAL — OPERATOR SELECTS 12V / 28V")
        hint.setWordWrap(True)
        v.addWidget(hint)

        self._style_relay_btn()
        return box

    def _style_relay_btn(self):
        dk = self._dark_mode
        on = self._relay_on
        if on:
            bg    = '#1A1008' if dk else '#FFF3E0'
            txt   = PH_AMBER
            hover = '#2A1A0C' if dk else '#FFE8C4'
            press = '#100800' if dk else '#FFDFA8'
            self.relay_btn.setStyleSheet(f"""
                QPushButton         {{background:{bg};color:{txt};
                                      border:1px solid {PH_AMBER};border-radius:7px;
                                      font-size:12px;font-weight:700;letter-spacing:1px;}}
                QPushButton:hover   {{background:{hover};}}
                QPushButton:pressed {{background:{press};}}
            """)
        else:
            bg    = '#1A1A1E' if dk else '#EDEDF2'
            txt   = TXT_SEC   if dk else '#6A6A72'
            bdr   = BORDER2   if dk else '#D8D8DE'
            self.relay_btn.setStyleSheet(f"""
                QPushButton         {{background:{bg};color:{txt};
                                      border:1px solid {bdr};border-radius:7px;
                                      font-size:12px;font-weight:700;letter-spacing:1px;}}
                QPushButton:hover   {{border-color:{PH_AMBER};color:{PH_AMBER};}}
                QPushButton:pressed {{background:{bdr};}}
            """)

    def _on_relay_toggle(self, on: bool):
        self._relay_on = on
        self.relay_btn.setText("ON  ·  28V" if on else "OFF  ·  12V")
        self._style_relay_btn()
        self.worker.send_command("RELAY ON" if on else "RELAY OFF")
        self._comm_log(f"TX  RELAY {'ON (28V)' if on else 'OFF (12V)'}",
                       PH_AMBER if on else TXT_SEC)

    def _apply_relay_state(self, payload: str):
        """Sync the button to the firmware's RELAY:<0|1> line (no echo back)."""
        if not hasattr(self, 'relay_btn'):
            return
        on = payload.strip() == "1"
        if on == self._relay_on and self.relay_btn.isChecked() == on:
            return
        self._relay_on = on
        self.relay_btn.blockSignals(True)
        self.relay_btn.setChecked(on)
        self.relay_btn.blockSignals(False)
        self.relay_btn.setText("ON  ·  28V" if on else "OFF  ·  12V")
        self._style_relay_btn()

    # ══════════════════════════════════════════════════════════════════
    #  VALVE SINGLE-SHOT  —  one precise plain pulse (SHOT <us>)
    #
    #  The discrete alternative to PUMP mode's continuous PWM: a single
    #  hardware-timed square pulse on the valve (GPIO18), width set in µs.
    #  Rejected by the firmware in PUMP mode (LEDC owns the pin there).
    # ══════════════════════════════════════════════════════════════════
    def _panel_shot(self):
        box = QGroupBox("VALVE SINGLE-SHOT")
        g   = QGridLayout(box); g.setSpacing(8)

        g.addWidget(self._dim("DURATION (µs)"), 0, 0)
        self.shot_sp = QSpinBox()
        self.shot_sp.setRange(500, 5000)
        self.shot_sp.setSingleStep(100)
        self.shot_sp.setValue(1000)
        self.shot_sp.setToolTip(
            "One precise pulse on the valve (GPIO18), 500–5000 µs.\n"
            "Hardware-timed falling edge — not continuous PWM.")
        g.addWidget(self.shot_sp, 0, 1)

        self.shot_btn = QPushButton("▶  FIRE SHOT")
        self.shot_btn.setMinimumHeight(34)
        self.shot_btn.setStyleSheet(f"""
            QPushButton       {{background:#081428;color:{PH_BLUE};
                                border:1px solid #102248;border-radius:7px;
                                font-size:12px;font-weight:600;letter-spacing:1px;}}
            QPushButton:hover {{background:#102248;color:{TXT_PRI};border-color:{PH_BLUE};}}
            QPushButton:pressed {{background:#050C18;color:{TXT_PRI};}}
        """)
        self.shot_btn.clicked.connect(self._on_shot)
        g.addWidget(self.shot_btn, 1, 0, 1, 2)

        hint = self._dim("ONE PULSE PER PRESS — NOT CONTINUOUS PWM")
        hint.setWordWrap(True)
        g.addWidget(hint, 2, 0, 1, 2)
        return box

    def _on_shot(self):
        us = self.shot_sp.value()
        self.worker.send_command(f"SHOT {us}")
        self._comm_log(f"TX  SHOT {us}µs", PH_BLUE)

    # ── actions ───────────────────────────────────────────────────────
    def _panel_actions(self):
        box = QGroupBox("ACTUATORS")
        g   = QGridLayout(box); g.setSpacing(8)

        self.start_btn = QPushButton("  START")
        self.start_btn.setFont(QFont("Arial", 13, QFont.Weight.Bold))
        self.start_btn.setMinimumHeight(52)
        self.start_btn.setStyleSheet(f"""
            QPushButton         {{background:#0A2218;color:{PH_GREEN};
                                  border:1px solid #163C28;border-radius:7px;
                                  font-weight:600;}}
            QPushButton:hover   {{background:#163C28;border-color:{PH_GREEN};}}
            QPushButton:pressed {{background:#061009;}}
        """)
        self.start_btn.clicked.connect(self._on_start)

        self.stop_btn = QPushButton("  STOP")
        self.stop_btn.setFont(QFont("Arial", 13, QFont.Weight.Bold))
        self.stop_btn.setMinimumHeight(52)
        self.stop_btn.setStyleSheet(f"""
            QPushButton         {{background:#2A1010;color:{PH_RED};
                                  border:1px solid #44181A;border-radius:7px;
                                  font-weight:600;}}
            QPushButton:hover   {{background:#44181A;border-color:{PH_RED};}}
            QPushButton:pressed {{background:#100506;}}
        """)
        self.stop_btn.clicked.connect(self._on_stop)

        self.sync_btn = QPushButton("↺  SYNC PARAMS")
        self.sync_btn.setMinimumHeight(30)
        self.sync_btn.setToolTip("Re-send all parameters to ESP32")
        self.sync_btn.setStyleSheet(f"""
            QPushButton       {{background:#081428;color:{PH_BLUE};
                                border:1px solid #102248;border-radius:7px;font-size:11px;font-weight:500;}}
            QPushButton:hover {{background:#102248;color:{TXT_PRI};border-color:{PH_BLUE};}}
            QPushButton:pressed {{background:#050C18;color:{TXT_PRI};}}
        """)
        self.sync_btn.clicked.connect(self._sync)

        # ── Auto-stop after N seconds ─────────────────────────────────
        autostop_row = QWidget()
        ahr = QHBoxLayout(autostop_row); ahr.setContentsMargins(0,0,0,0); ahr.setSpacing(6)
        ahr.addWidget(self._dim("AUTO-STOP (s)"))
        self.autostop_sp = QSpinBox()
        self.autostop_sp.setRange(0, 3600)
        self.autostop_sp.setValue(0)
        self.autostop_sp.setSpecialValueText("OFF")
        self.autostop_sp.setToolTip("0 = disabled. Auto-stops test after N seconds.")
        self.autostop_sp.valueChanged.connect(
            lambda v: setattr(self, '_auto_stop_secs', v))
        ahr.addWidget(self.autostop_sp)

        # ── Save PDF Report ───────────────────────────────────────────
        self.report_btn = QPushButton("  SAVE PDF REPORT")
        self.report_btn.setMinimumHeight(30)
        self.report_btn.setStyleSheet(f"""
            QPushButton       {{background:#081A12;color:{PH_GREEN};
                                border:1px solid #102C1E;border-radius:7px;font-size:11px;font-weight:500;}}
            QPushButton:hover {{background:#102C1E;color:{TXT_PRI};border-color:{PH_GREEN};}}
            QPushButton:pressed {{background:#040D09;color:{TXT_PRI};}}
        """)
        self.report_btn.clicked.connect(self._save_pdf)

        # ── Export CSV ────────────────────────────────────────────────
        self.csv_btn = QPushButton("  EXPORT CSV")
        self.csv_btn.setMinimumHeight(30)
        self.csv_btn.setStyleSheet(f"""
            QPushButton       {{background:#0A1820;color:{PH_CYAN};
                                border:1px solid #122838;border-radius:7px;font-size:11px;font-weight:500;}}
            QPushButton:hover {{background:#122838;color:{TXT_PRI};border-color:{PH_CYAN};}}
            QPushButton:pressed {{background:#050C10;color:{TXT_PRI};}}
        """)
        self.csv_btn.clicked.connect(self._export_csv)

        # ── Zero Calibration button ───────────────────────────────────
        self.zero_btn = QPushButton("◎  SET ZERO PRESSURE")
        self.zero_btn.setMinimumHeight(30)
        self.zero_btn.setToolTip(
            "Press at zero pressure — auto-sets VP_ZERO from current VX4 EMA")
        self.zero_btn.setStyleSheet(f"""
            QPushButton       {{background:#1A1008;color:{PH_AMBER};
                                border:1px solid #3A2810;border-radius:7px;
                                font-size:11px;font-weight:600;}}
            QPushButton:hover {{background:#2A1A0C;color:{TXT_PRI};border-color:{PH_AMBER};}}
            QPushButton:pressed {{background:#100800;}}
        """)
        self.zero_btn.clicked.connect(self._set_pressure_zero)

        g.addWidget(self.start_btn,    0, 0)
        g.addWidget(self.stop_btn,     0, 1)
        g.addWidget(self.sync_btn,     1, 0, 1, 2)
        g.addWidget(autostop_row,      2, 0, 1, 2)
        g.addWidget(self.zero_btn,     3, 0, 1, 2)
        g.addWidget(self.report_btn,   4, 0)
        g.addWidget(self.csv_btn,      4, 1)
        return box


    # ── meters panel (Hartridge-style large displays) ─────────────────
    def _panel_meters(self):
        box = QGroupBox("MEASUREMENTS")
        h   = QVBoxLayout(box); h.setSpacing(4)

        dk = self._dark_mode  # capture once for all meter() calls

        def meter(label, color, digits, unit=""):
            frame = QWidget()
            frame_bg  = PANEL   if dk else '#FFFFFF'
            frame_bdr = BORDER2 if dk else '#E0E0E6'
            frame.setStyleSheet(
                f"background:{frame_bg}; border:1px solid {frame_bdr}; border-radius:6px;")
            v = QVBoxLayout(frame); v.setContentsMargins(10, 8, 10, 8); v.setSpacing(4)

            lbl = QLabel(label.upper())
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            # In dark mode: alpha-dimmed accent. In light mode: full-color accent.
            lbl_color = f"{color}50" if dk else color
            lbl.setStyleSheet(
                f"color:{lbl_color}; font-size:9px; font-weight:bold;"
                f" letter-spacing:2px; font-family:monospace; border:none;")

            lcd = QLCDNumber()
            lcd.setDigitCount(digits)
            lcd.setMinimumSize(10, 55)   # override large default minimumSizeHint
            lcd.setSegmentStyle(QLCDNumber.SegmentStyle.Flat)
            # Dark mode → dark screen with vivid segments. Light mode → white
            # screen with a saturated colored segment so the reading still pops
            # but the whole panel matches the day palette instead of clashing.
            lcd_bg    = G_BG        if dk else '#FBFCFD'
            lcd_bdr   = f"{color}28" if dk else f"{color}45"
            lcd.setStyleSheet(
                f"QLCDNumber{{color:{color}; background:{lcd_bg};"
                f" border:1px solid {lcd_bdr}; border-radius:4px;}}")

            unit_lbl = QLabel(unit)
            unit_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            unit_color = f"{color}60" if dk else f"{color}CC"
            unit_lbl.setStyleSheet(
                f"color:{unit_color}; font-size:10px; font-family:monospace; border:none;")

            v.addWidget(lbl)
            v.addWidget(lcd)
            v.addWidget(unit_lbl)
            return frame, lcd

        # Store frame refs for Feature 4 alarm blinking + theme toggle
        self.frame_r, self.lcd_r = meter("RPM",      PH_PURPLE, 5, "RPM")
        self.frame_p, self.lcd_p = meter("PRESSURE", PH_AMBER,  7, "BAR")
        self.frame_a, self.lcd_a = meter("ANGLE",    PH_BLUE,   3, "deg")
        f3 = self.frame_a

        # Force equal horizontal distribution — ignore per-widget sizeHints
        from PyQt6.QtWidgets import QSizePolicy as _SP
        _eq = _SP(_SP.Policy.Ignored, _SP.Policy.Preferred)
        self.frame_r.setSizePolicy(_eq)
        self.frame_p.setSizePolicy(_eq)
        f3.setSizePolicy(_eq)

        # ── INJ LED panel — flashes green on every injection pulse ────
        dk = self._dark_mode
        f2 = QWidget()
        self.frame_inj = f2
        f2.setStyleSheet(
            f"background:{'#1C1C1E' if dk else '#FFFFFF'};"
            f" border:1px solid {'#2C2C2E' if dk else '#E0E0E6'}; border-radius:6px;")
        v2 = QVBoxLayout(f2); v2.setContentsMargins(10, 8, 10, 8); v2.setSpacing(6)

        inj_title = QLabel("INJ PULSE")
        inj_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inj_title.setStyleSheet(
            f"color:{PH_GREEN}{'50' if dk else 'FF'}; font-size:9px; font-weight:bold;"
            f" letter-spacing:2px; font-family:monospace; border:none;")

        self.inj_led = QLabel()
        self.inj_led.setMinimumHeight(55)
        self.inj_led.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Day-mode off-state is a very light tint so the whole panel reads white,
        # not black. On-state stays vivid green regardless of theme.
        self._led_on_style  = (
            f"background:{PH_GREEN}; border-radius:10px;"
            f" border:2px solid #60FF90;")
        self._led_off_style = (
            f"background:{'#0A1A0D' if dk else '#EAF7EE'}; border-radius:10px;"
            f" border:2px solid {'#1A3A20' if dk else '#BEE3C7'};")
        self.inj_led.setStyleSheet(self._led_off_style)

        self.inj_rate_lbl = QLabel("0 inj/s")
        self.inj_rate_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.inj_rate_lbl.setStyleSheet(
            f"color:{PH_GREEN}{'80' if dk else 'FF'}; font-size:10px; font-family:monospace; border:none;")

        v2.addWidget(inj_title)
        v2.addWidget(self.inj_led, 1)
        v2.addWidget(self.inj_rate_lbl)

        # Timer to turn LED off after flash
        self._led_timer = QTimer(self)
        self._led_timer.setSingleShot(True)
        self._led_timer.setInterval(80)   # LED stays on 80 ms
        self._led_timer.timeout.connect(
            lambda: self.inj_led.setStyleSheet(self._led_off_style))

        self.lcd_i = None   # kept for compatibility, not displayed
        from PyQt6.QtWidgets import QSizePolicy as _SP2
        f2.setSizePolicy(_SP2(_SP2.Policy.Ignored, _SP2.Policy.Preferred))

        # Engine status
        status_box = QWidget()
        self.frame_engine = status_box
        status_box.setStyleSheet(
            f"background:{PANEL if dk else '#FFFFFF'};"
            f" border:1px solid {BORDER2 if dk else '#E0E0E6'}; border-radius:6px;")
        sv = QVBoxLayout(status_box); sv.setContentsMargins(10, 8, 10, 8); sv.setSpacing(6)

        sl = QLabel("ENGINE")
        sl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sl.setStyleSheet(
            f"color:{TXT_DIM if dk else '#7A7A80'}; font-size:9px; font-weight:bold;"
            f" letter-spacing:2px; font-family:monospace; border:none;")

        self.run_lbl = QLabel("STOPPED")
        self.run_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.run_lbl.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        self.run_lbl.setStyleSheet(
            f"color:{PH_RED}; font-family:monospace; border:none;")

        self.mode_lbl = QLabel("COMMON RAIL")
        self.mode_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mode_lbl.setStyleSheet(
            f"color:{PH_BLUE}; font-size:11px; font-family:monospace;"
            f" letter-spacing:1px; border:none;")

        sv.addWidget(sl)
        sv.addStretch()
        sv.addWidget(self.run_lbl)
        sv.addWidget(self.mode_lbl)
        sv.addStretch()

        # ── Row 1: primary readings ───────────────────────────────────────
        top_row = QHBoxLayout(); top_row.setSpacing(6)
        top_row.addWidget(self.frame_r, stretch=1)   # RPM
        top_row.addWidget(self.frame_p, stretch=1)   # PRESSURE
        top_row.addWidget(f2,           stretch=1)   # INJ PULSE

        # ── Row 2: secondary readings + engine state ───────────────────
        bot_row = QHBoxLayout(); bot_row.setSpacing(6)
        bot_row.addWidget(f3,           stretch=1)   # ANGLE
        bot_row.addWidget(status_box,   stretch=2)   # ENGINE STATUS
        bot_row.addStretch(1)
        bot_container = QWidget()
        bot_container.setLayout(bot_row)

        h.addLayout(top_row,       stretch=3)
        h.addWidget(bot_container, stretch=2)

        return box

    # ── helpers ───────────────────────────────────────────────────────
    def _dim(self, txt):
        l = QLabel(txt)
        color = TXT_DIM if self._dark_mode else '#3A3A4A'
        l.setStyleSheet(
            f"color:{color}; font-size:9px; font-weight:bold;"
            f" letter-spacing:1px; font-family:monospace;")
        return l

    def _vsep(self):
        f = QFrame(); f.setFrameShape(QFrame.Shape.VLine)
        f.setStyleSheet(f"color:{BORDER2};")
        f.setFixedHeight(22)
        return f

    def _style_conn_btn(self, connected):
        if self._dark_mode:
            if connected:
                self.conn_btn.setStyleSheet(f"""
                    QPushButton       {{background:#2A1010;color:{PH_RED};
                                        font-weight:600;border-radius:7px;border:1px solid #44181A;}}
                    QPushButton:hover {{background:#44181A;border-color:{PH_RED};}}
                    QPushButton:pressed {{background:#100506;}}""")
            else:
                self.conn_btn.setStyleSheet(f"""
                    QPushButton       {{background:#081428;color:{PH_BLUE};
                                        font-weight:600;border-radius:7px;border:1px solid #102248;}}
                    QPushButton:hover {{background:#102248;color:{TXT_PRI};border-color:{PH_BLUE};}}
                    QPushButton:pressed {{background:#050C18;}}""")
        else:
            if connected:
                self.conn_btn.setStyleSheet("""
                    QPushButton       {background:#FFE5E3;color:#C0281E;
                                        font-weight:600;border-radius:7px;border:1px solid #FFBBBA;}
                    QPushButton:hover {background:#FFBBBA;border-color:#FF453A;}
                    QPushButton:pressed {background:#FFAAAA;}""")
            else:
                self.conn_btn.setStyleSheet("""
                    QPushButton       {background:#E5F0FF;color:#0A5CC7;
                                        font-weight:600;border-radius:7px;border:1px solid #B8D4FF;}
                    QPushButton:hover {background:#B8D4FF;color:#063A8A;border-color:#0A84FF;}
                    QPushButton:pressed {background:#98C0F5;}""")

    def _cam_visible(self, vis):
        for w in [self.fr_lbl, self.fr_sp, self.fr_sl]:
            w.setVisible(not vis)
        for w in [self.an_lbl, self.an_sp, self.an_sl, self.delay_lbl]:
            w.setVisible(vis)

    def _update_delay_label(self):
        if self._mode_id == 1:
            if self._rpm_ema > 10:
                period_ms = 60000.0 / self._rpm_ema
                delay_ms  = (self.an_sp.value() / 360.0) * period_ms
                self.delay_lbl.setText(
                    f"DELAY  {delay_ms:.3f} ms  "
                    f"({self.an_sp.value()}  @ {int(self._rpm_ema)} RPM)")
            else:
                self.delay_lbl.setText("DELAY  —  waiting for RPM signal")

    # ──────────────────────────────────────────────────────────────────
    #  PROFILE SYSTEM — Brand / Model / Mode handlers
    # ──────────────────────────────────────────────────────────────────
    # ── Table right-click — PIN-protected spec editing ────────────────
    _DEV_PIN = "26157048"

    # Column index → JSON field mapping (editable spec columns only)
    _COL_FIELD = {
        1: "rpm",
        2: "pulse_us",
        3: "duration_s",
        4: "vol_target",
        5: "vol_min",
        6: "vol_max",
    }
    _COL_LABEL = {
        1: "RPM",
        2: "PW (µs)",
        3: "Time (s)",
        4: "Target (ml)",
        5: "Min (ml)",
        6: "Max (ml)",
    }

    def _verify_dev_pin(self) -> bool:
        """Ask for PIN every time before any edit."""
        from PyQt6.QtWidgets import QInputDialog
        pin, ok = QInputDialog.getText(
            self, "🔒  Developer Access",
            "Enter developer PIN:",
            QLineEdit.EchoMode.Password)
        if ok and pin == self._DEV_PIN:
            return True
        if ok:
            QMessageBox.warning(self, "Access Denied", "❌  Incorrect PIN.")
        return False

    def _table_context_menu(self, pos):
        from PyQt6.QtWidgets import QMenu
        t   = self._calib_table
        idx = t.indexAt(pos)
        row, col = idx.row(), idx.column()
        if row < 0 or col not in self._COL_FIELD:
            return
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{background:{PANEL};color:{TXT_PRI};border:1px solid {BORDER2};
                    font-size:12px;padding:4px;}}
            QMenu::item {{padding:6px 20px;border-radius:4px;}}
            QMenu::item:selected {{background:{PH_BLUE}33;color:{TXT_PRI};}}
        """)
        mode_name  = t.item(row, 0).text()
        field_name = self._COL_LABEL[col]
        cur_val    = t.item(row, col).text() if t.item(row, col) else "—"
        edit_act = menu.addAction(
            f"✏  Edit  [{mode_name}]  {field_name}  =  {cur_val}")
        action = menu.exec(t.viewport().mapToGlobal(pos))
        if action != edit_act:
            return
        if not self._verify_dev_pin():
            return
        self._table_edit_cell(row, col, mode_name, field_name, cur_val)

    def _table_edit_cell(self, row, col, mode_name, field_name, cur_val):
        from PyQt6.QtWidgets import QInputDialog
        # Map display name back to JSON key
        json_mode = "CamBox" if mode_name == "VE" else mode_name
        json_field = self._COL_FIELD[col]

        new_val, ok = QInputDialog.getText(
            self, f"Edit  {field_name}",
            f"{mode_name}  →  {field_name}\nCurrent: {cur_val}\n\nNew value:",
            QLineEdit.EchoMode.Normal, cur_val)
        if not ok or not new_val.strip():
            return
        try:
            # Numeric conversion
            if json_field in ("rpm", "pulse_us", "duration_s"):
                typed_val = int(float(new_val.strip()))
            else:
                typed_val = float(new_val.strip())
        except ValueError:
            QMessageBox.warning(self, "Invalid Value", "Please enter a number.")
            return

        # Save to active profile in database
        if not self._active_profile:
            QMessageBox.warning(self, "No Profile",
                "Load a profile first before editing.")
            return
        pid = self._active_profile.get("id")
        updated = dict(self._active_profile)
        if json_mode not in updated.get("modes", {}):
            updated.setdefault("modes", {})[json_mode] = {}
        updated["modes"][json_mode][json_field] = typed_val
        self._injector_db.update_profile(pid, updated)
        self._active_profile = self._injector_db.by_id(pid)
        # Refresh table display
        self._populate_calib_table(self._active_profile)
        self._refresh_cylinders(self._active_profile)

    # ── Model right-click context menu ───────────────────────────────
    def _model_context_menu(self, pos):
        from PyQt6.QtWidgets import QMenu
        idx = self.model_combo.currentIndex()
        pid = self.model_combo.itemData(idx)
        if not pid:
            return
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{background:{PANEL};color:{TXT_PRI};border:1px solid {BORDER2};
                    font-size:12px;padding:4px;}}
            QMenu::item {{padding:6px 20px;border-radius:4px;}}
            QMenu::item:selected {{background:{PH_BLUE}33;color:{TXT_PRI};}}
        """)
        edit_act  = menu.addAction("✏  Edit profile values")
        menu.addSeparator()
        del_act   = menu.addAction("🗑  Delete profile")
        action = menu.exec(self.model_combo.mapToGlobal(pos))
        if action == edit_act:
            if not self._verify_dev_pin():
                return
            self._edit_profile_dialog(pid)
        elif action == del_act:
            if not self._verify_dev_pin():
                return
            profile = self._injector_db.by_id(pid)
            if profile:
                r = QMessageBox.question(self, "Delete Profile",
                    f"Delete  {profile['brand']} — {profile['model']} ?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if r == QMessageBox.StandardButton.Yes:
                    self._injector_db.delete_profile(pid)
                    self.brand_combo.blockSignals(True)
                    self.brand_combo.clear()
                    self.brand_combo.addItem("— Select Brand —")
                    self.brand_combo.addItems(self._injector_db.brands())
                    self.brand_combo.blockSignals(False)
                    self.brand_combo.setCurrentIndex(0)

    def _edit_profile_dialog(self, pid: str):
        from PyQt6.QtWidgets import (QDialog, QTabWidget, QFormLayout,
                                      QDialogButtonBox, QScrollArea)
        profile = self._injector_db.by_id(pid)
        if not profile:
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Edit  {profile['brand']} — {profile['model']}")
        dlg.setMinimumSize(480, 520)
        dlg.setStyleSheet(f"background:{PANEL}; color:{TXT_PRI};")

        def fld(val=""):
            e = QLineEdit(str(val))
            e.setStyleSheet(f"background:{BORDER};color:{TXT_PRI};"
                            f"border:1px solid {BORDER2};border-radius:5px;padding:3px 7px;")
            return e

        tabs = QTabWidget()
        tabs.setStyleSheet(f"""
            QTabWidget::pane  {{border:1px solid {BORDER2};border-radius:6px;}}
            QTabBar::tab      {{background:{BORDER};color:{TXT_SEC};padding:5px 12px;
                               border-radius:4px;margin-right:2px;}}
            QTabBar::tab:selected {{background:{PH_BLUE}44;color:{TXT_PRI};}}
        """)

        # ── Info tab ──────────────────────────────────────────────────
        info_w = QWidget(); info_f = QFormLayout(info_w)
        info_f.setSpacing(6); info_f.setContentsMargins(12,12,12,12)
        f_brand  = fld(profile.get("brand",""))
        f_model  = fld(profile.get("model",""))
        f_type   = fld(profile.get("type",""))
        f_engine = fld(profile.get("engine",""))
        s = profile.get("safety", {})
        f_maxpw  = fld(s.get("max_pulse_us",""))
        f_maxhz  = fld(s.get("max_freq_hz",""))
        f_maxrpm = fld(s.get("max_rpm",""))
        info_f.addRow("Brand",        f_brand)
        info_f.addRow("Model",        f_model)
        info_f.addRow("Type",         f_type)
        info_f.addRow("Engine",       f_engine)
        info_f.addRow("Max PW (µs)",  f_maxpw)
        info_f.addRow("Max Hz",       f_maxhz)
        info_f.addRow("Max RPM",      f_maxrpm)
        tabs.addTab(info_w, "INFO")

        # ── Mode tabs ─────────────────────────────────────────────────
        mode_fields = {}
        for mname in ["Idle", "Medium", "Full Load", "CamBox"]:
            mp = profile.get("modes", {}).get(mname, {})
            mw = QWidget(); mf = QFormLayout(mw)
            mf.setSpacing(6); mf.setContentsMargins(12,12,12,12)
            fields = {
                "rpm":        fld(mp.get("rpm",       "")),
                "pulse_us":   fld(mp.get("pulse_us",  "")),
                "freq_hz":    fld(mp.get("freq_hz",   "")),
                "duration_s": fld(mp.get("duration_s","")),
                "rail_bar":   fld(mp.get("rail_bar",  "")),
                "vol_target": fld(mp.get("vol_target","")),
                "vol_min":    fld(mp.get("vol_min",   "")),
                "vol_max":    fld(mp.get("vol_max",   "")),
            }
            mf.addRow("RPM",        fields["rpm"])
            mf.addRow("PW (µs)",    fields["pulse_us"])
            mf.addRow("Hz",         fields["freq_hz"])
            mf.addRow("Time (s)",   fields["duration_s"])
            mf.addRow("Rail BAR",   fields["rail_bar"])
            mf.addRow("Target ml",  fields["vol_target"])
            mf.addRow("Min ml",     fields["vol_min"])
            mf.addRow("Max ml",     fields["vol_max"])
            mode_fields[mname] = fields
            label = "VE" if mname == "CamBox" else mname
            tabs.addTab(mw, label)

        # ── Layout ────────────────────────────────────────────────────
        main_v = QVBoxLayout(dlg)
        main_v.setContentsMargins(12,12,12,12); main_v.setSpacing(8)
        main_v.addWidget(tabs)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel)
        btns.setStyleSheet(f"""
            QPushButton {{background:{BORDER};color:{PH_BLUE};
                          border:1px solid {BORDER2};border-radius:5px;
                          padding:5px 20px;font-weight:600;}}
            QPushButton:hover {{background:{BORDER2};color:{TXT_PRI};}}
        """)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        main_v.addWidget(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        # ── Save changes ──────────────────────────────────────────────
        def num(e, default=0.0):
            try: return float(e.text())
            except: return default

        updated = dict(profile)
        updated["brand"]  = f_brand.text().strip()  or profile["brand"]
        updated["model"]  = f_model.text().strip()  or profile["model"]
        updated["type"]   = f_type.text().strip()
        updated["engine"] = f_engine.text().strip()
        updated["safety"] = {
            "max_pulse_us": int(num(f_maxpw, s.get("max_pulse_us",800))),
            "max_freq_hz":  int(num(f_maxhz,  s.get("max_freq_hz",15))),
            "max_rpm":      int(num(f_maxrpm, s.get("max_rpm",4000))),
        }
        for mname, fields in mode_fields.items():
            if mname not in updated["modes"]:
                updated["modes"][mname] = {}
            mp = updated["modes"][mname]
            mp["rpm"]        = int(num(fields["rpm"],        mp.get("rpm",0)))
            mp["pulse_us"]   = int(num(fields["pulse_us"],   mp.get("pulse_us",200)))
            mp["freq_hz"]    = int(num(fields["freq_hz"],    mp.get("freq_hz",2)))
            mp["duration_s"] = int(num(fields["duration_s"], mp.get("duration_s",60)))
            mp["rail_bar"]   = int(num(fields["rail_bar"],   mp.get("rail_bar",0)))
            mp["vol_target"] = num(fields["vol_target"], mp.get("vol_target",0))
            mp["vol_min"]    = num(fields["vol_min"],    mp.get("vol_min",0))
            mp["vol_max"]    = num(fields["vol_max"],    mp.get("vol_max",5))

        self._injector_db.update_profile(pid, updated)
        # Refresh brand combo if brand changed
        self.brand_combo.blockSignals(True)
        self.brand_combo.clear()
        self.brand_combo.addItem("— Select Brand —")
        self.brand_combo.addItems(self._injector_db.brands())
        self.brand_combo.blockSignals(False)
        self.brand_combo.setCurrentText(updated["brand"])
        QMessageBox.information(self, "Edit Profile", "✓  Changes saved.")

    # ── Search filter ─────────────────────────────────────────────────
    def _on_search_changed(self, text: str):
        """Filter brand/model combos as user types."""
        q = text.strip().lower()
        self.brand_combo.blockSignals(True)
        self.brand_combo.clear()
        self.brand_combo.addItem("— Select Brand —")
        all_brands = self._injector_db.brands()
        if not q:
            self.brand_combo.addItems(all_brands)
        else:
            # Show brands that match or have a matching model
            for b in all_brands:
                if q in b.lower():
                    self.brand_combo.addItem(b)
                else:
                    models = [p["model"] for p in self._injector_db.by_brand(b)]
                    if any(q in m.lower() for m in models):
                        self.brand_combo.addItem(b)
        self.brand_combo.blockSignals(False)
        # Auto-select if only one brand matches
        if self.brand_combo.count() == 2:
            self.brand_combo.setCurrentIndex(1)

    # ── Add new profile dialog ─────────────────────────────────────────
    def _on_add_profile(self):
        if not self._verify_dev_pin():
            return
        from PyQt6.QtWidgets import QDialog, QFormLayout, QDialogButtonBox
        dlg = QDialog(self)
        dlg.setWindowTitle("Add Injector Profile")
        dlg.setMinimumWidth(360)
        dlg.setStyleSheet(f"background:{PANEL}; color:{TXT_PRI};")
        form = QFormLayout(dlg)
        form.setSpacing(8); form.setContentsMargins(16, 16, 16, 16)

        def field(placeholder=""):
            e = QLineEdit(); e.setPlaceholderText(placeholder)
            e.setStyleSheet(f"background:{BORDER};color:{TXT_PRI};"
                            f"border:1px solid {BORDER2};border-radius:5px;padding:4px 8px;")
            return e

        f_brand  = field("e.g. Bosch / EUI Iveco")
        f_model  = field("e.g. CRI 2.0 TDI")
        f_type   = field("e.g. Common Rail Solenoid")
        f_engine = field("e.g. 2.0 TDI")
        f_max_pw = field("e.g. 800")
        f_max_hz = field("e.g. 15")

        form.addRow("Brand",       f_brand)
        form.addRow("Model",       f_model)
        form.addRow("Type",        f_type)
        form.addRow("Engine",      f_engine)
        form.addRow("Max PW (µs)", f_max_pw)
        form.addRow("Max Hz",      f_max_hz)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        btns.setStyleSheet(f"""
            QPushButton {{background:{BORDER};color:{PH_BLUE};
                          border:1px solid {BORDER2};border-radius:5px;
                          padding:4px 16px;font-weight:600;}}
            QPushButton:hover {{background:{BORDER2};color:{TXT_PRI};}}
        """)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        brand  = f_brand.text().strip()
        model  = f_model.text().strip()
        if not brand or not model:
            QMessageBox.warning(self, "Add Profile", "Brand and Model are required.")
            return

        pid = f"{brand.upper().replace(' ','_')}_{model.upper().replace(' ','_')[:20]}"
        try:
            max_pw = int(f_max_pw.text()) if f_max_pw.text().strip() else 800
            max_hz = int(f_max_hz.text()) if f_max_hz.text().strip() else 15
        except ValueError:
            max_pw, max_hz = 800, 15

        new_profile = {
            "id":      pid,
            "brand":   brand,
            "model":   model,
            "type":    f_type.text().strip() or "Common Rail Solenoid",
            "engine":  f_engine.text().strip() or "",
            "notes":   "",
            "safety":  {"max_pulse_us": max_pw, "max_freq_hz": max_hz, "max_rpm": 4000},
            "modes": {
                "Idle":      {"rail_bar":250, "pulse_us":200, "freq_hz":2, "duration_s":60,
                              "delay_deg":0, "rpm":800,
                              "vol_min":0.0, "vol_target":0.0, "vol_max":5.0, "vol_unit":"ml/1000"},
                "Medium":    {"rail_bar":750, "pulse_us":350, "freq_hz":5, "duration_s":60,
                              "delay_deg":0, "rpm":1500,
                              "vol_min":0.0, "vol_target":0.0, "vol_max":15.0, "vol_unit":"ml/1000"},
                "Full Load": {"rail_bar":1350,"pulse_us":500, "freq_hz":10,"duration_s":60,
                              "delay_deg":0, "rpm":3000,
                              "vol_min":0.0, "vol_target":0.0, "vol_max":25.0, "vol_unit":"ml/1000"},
                "CamBox":    {"rail_bar":750, "pulse_us":350, "freq_hz":5, "duration_s":120,
                              "delay_deg":5, "rpm":1500,
                              "vol_min":0.0, "vol_target":0.0, "vol_max":15.0, "vol_unit":"ml/1000"},
            }
        }
        self._injector_db.add_profile(new_profile)
        # Refresh brand combo
        self.brand_combo.blockSignals(True)
        self.brand_combo.clear()
        self.brand_combo.addItem("— Select Brand —")
        self.brand_combo.addItems(self._injector_db.brands())
        self.brand_combo.blockSignals(False)
        self.brand_combo.setCurrentText(brand)
        QMessageBox.information(self, "Add Profile",
            f"✓  {brand}  —  {model}\nProfile added. Edit the spec values in injector_db.json.")

    def _on_brand_change(self, brand: str):
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItem("— Select Model —")
        if brand and not brand.startswith("—"):
            for p in self._injector_db.by_brand(brand):
                self.model_combo.addItem(p["model"], userData=p["id"])
        self.model_combo.blockSignals(False)
        self._active_profile = None
        self._profile_info.setText("Select a model to load profile")
        self._safety_lbl.setText("")
        self._safety.set_profile(None)

    def _on_injector_id_entered(self):
        """Reverse lookup: type an injector ID → auto-select brand + model."""
        pid = self.inj_id_edit.text().strip()
        if not pid:
            return
        profile = self._injector_db.by_id(pid)
        if not profile:
            self.inj_id_edit.setStyleSheet(
                self.inj_id_edit.styleSheet().replace(f"color:{TXT_PRI}", f"color:{PH_RED}"))
            return
        self.inj_id_edit.setStyleSheet(
            self.inj_id_edit.styleSheet().replace(f"color:{PH_RED}", f"color:{TXT_PRI}"))
        self._select_profile_by_id(pid)

    def _select_profile_by_id(self, pid: str):
        """Select brand + model combos for the given profile ID, then load it."""
        profile = self._injector_db.by_id(pid)
        if not profile:
            return
        brand = profile.get("brand", "")
        self.brand_combo.blockSignals(True)
        self.brand_combo.setCurrentText(brand)
        self.brand_combo.blockSignals(False)
        # Repopulate model combo for this brand
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItem("— Select Model —")
        for p in self._injector_db.by_brand(brand):
            self.model_combo.addItem(p["model"], userData=p["id"])
        self.model_combo.blockSignals(False)
        # Select the matching model
        for i in range(self.model_combo.count()):
            if self.model_combo.itemData(i) == pid:
                self.model_combo.setCurrentIndex(i)
                break

    def _on_model_change(self, model: str):
        if model.startswith("—"):
            return
        idx = self.model_combo.currentIndex()
        pid = self.model_combo.itemData(idx)
        if not pid:
            return
        profile = self._injector_db.by_id(pid)
        if not profile:
            return
        self._active_profile = profile
        self._safety.set_profile(profile)
        # Auto-populate the INJECTOR ID field from the selected profile
        self.inj_id_edit.setText(profile.get("id", ""))
        # Update info card
        s = profile.get("safety", {})
        info = (f"{profile.get('type','')}  |  {profile.get('engine','')}\n"
                f"Max: {s.get('max_pulse_us','—')} µs  "
                f"{s.get('max_freq_hz','—')} Hz  "
                f"{s.get('max_rpm','—')} RPM")
        self._profile_info.setText(info)
        self._safety_lbl.setText(
            f"⚠  Limits: PW≤{s.get('max_pulse_us')} µs  "
            f"Freq≤{s.get('max_freq_hz')} Hz")
        # Refresh calibration table + cylinder gauges
        if hasattr(self, '_calib_table'):
            self._populate_calib_table(profile)
        self._refresh_cylinders(profile)
        # Auto-load current mode params
        mode = self.mode_combo.currentText()
        if mode == "VE":
            self._on_cambox_profile_change(self.cambox_combo.currentText())
        else:
            self._load_mode_params(mode)

    def _on_mode_combo_change(self, mode: str):
        self._active_mode = mode
        # Show/hide CamBox sub-selector
        is_cb = (mode == "VE")
        self.cambox_combo.setVisible(is_cb)
        self._cambox_row_lbl.setVisible(is_cb)
        if is_cb:
            self._on_cambox_profile_change(self.cambox_combo.currentText())
        elif self._active_profile:
            self._load_mode_params(mode)

    def _on_cambox_profile_change(self, name: str):
        """Load a CamBox profile (Cranking / Idle / Diagnostic / Performance Test)."""
        params = self._injector_db.cambox_profiles().get(name)
        if not params:
            return
        self._apply_params(params, f"CamBox — {name}")

    def _load_mode_params(self, mode: str):
        """Load parameters from the active injector profile's selected mode."""
        if not self._active_profile:
            return
        modes    = self._active_profile.get("modes", {})
        json_key = "CamBox" if mode == "VE" else mode
        params   = modes.get(json_key)
        if not params:
            return
        p = self._active_profile
        self._apply_params(params, f"{p.get('model','')}  —  {mode}")

    def _apply_params(self, params: dict, label: str):
        """Validate + apply a parameter dict to spinboxes."""
        pw    = params.get("pulse_us",   200)
        freq  = params.get("freq_hz",    2)
        angle = params.get("delay_deg",  0)
        dur   = params.get("duration_s", 0)
        rpm   = params.get("rpm",        0)
        # Validate through safety layer
        _, pw,    msg1 = self._safety.validate_pulse(pw)
        _, freq,  msg2 = self._safety.validate_freq(freq)
        _, angle, msg3 = self._safety.validate_delay(angle)
        # Block signals — fill all at once
        for sp in [self.pw_sp, self.fr_sp, self.an_sp]:
            sp.blockSignals(True)
        self.pw_sp.setValue(pw);    self.pw_sl.setValue(pw)
        self.fr_sp.setValue(freq);  self.fr_sl.setValue(freq)
        self.an_sp.setValue(angle); self.an_sl.setValue(angle)
        if hasattr(self, 'autostop_sp') and dur > 0:
            self.autostop_sp.setValue(dur)
            self._auto_stop_secs = dur
        for sp in [self.pw_sp, self.fr_sp, self.an_sp]:
            sp.blockSignals(False)
        # Update target RPM label
        if rpm > 0:
            self._rpm_target_lbl.setText(f"Target RPM: {rpm}")
            self._rpm_target_lbl.setStyleSheet(
                f"color:{PH_PURPLE}; font-size:10px; font-family:monospace; padding:1px 0;")
        else:
            self._rpm_target_lbl.setText("Target RPM: LEAK TEST (no injection)")
            self._rpm_target_lbl.setStyleSheet(
                f"color:{PH_AMBER}; font-size:10px; font-family:monospace; padding:1px 0;")
        # Log any clamping warnings
        for msg in [msg1, msg2, msg3]:
            if msg:
                self._comm_log(f"⚠  {msg}", PH_AMBER)
        self._profile_info.setText(
            f"{label}\n"
            f"PW {pw} µs  |  {freq} Hz  |  {angle}°  |  {dur} s")

    # Backward-compat stub (kept so PDF report and other callers don't break)
    def _apply_preset(self, name: str):
        pass

    # ──────────────────────────────────────────────────────────────────
    #  FEATURE 2 — Save PDF Report
    # ──────────────────────────────────────────────────────────────────
    def _save_pdf(self):
        try:
            from PyQt6.QtPrintSupport import QPrinter
        except ImportError:
            QMessageBox.warning(self, "PDF Error",
                                "PyQt6.QtPrintSupport not available.\n"
                                "Run:  pip install PyQt6-Qt6-PrintSupport")
            return

        ts       = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        default  = f"Injector_Report_{ts}.pdf"
        path, _  = QFileDialog.getSaveFileName(
            self, "Save PDF Report", default, "PDF Files (*.pdf)")
        if not path:
            return

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(path)

        try:
            from PyQt6.QtGui import QPageSize
            printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        except Exception:
            pass

        painter = QPainter()
        if not painter.begin(printer):
            QMessageBox.critical(self, "PDF Error", f"Cannot write to:\n{path}")
            return

        page   = printer.pageRect(QPrinter.Unit.DevicePixel)
        W      = page.width()
        H      = page.height()
        margin = W * 0.06

        # Font sizes must be in POINTS (physical, DPI-independent) — never a
        # fraction of the pixel width (that yields ~190pt at 1200 DPI).
        _dpi   = printer.resolution() or 1200
        _pw_pt = W / _dpi * 72.0          # page width in points (~575 for A4)
        def _pt(frac):
            return max(5, round(_pw_pt * frac * 1.5))

        # ── header bar ────────────────────────────────────────────────
        painter.fillRect(0, 0, int(W), int(H * 0.07), QColor(HEADER))
        painter.setPen(QColor(PH_GREEN))
        painter.setFont(QFont("Arial", _pt(0.018), QFont.Weight.Bold))
        painter.drawText(int(margin), int(H * 0.044),
                         "INJECTOR PRO  —  Diesel Injection Test Report")
        # Date — right-aligned just under the title so it never overlaps.
        # Use painter.fontMetrics() (device DPI) not QFontMetrics (screen DPI).
        painter.setPen(QColor(TXT_SEC))
        painter.setFont(QFont("Arial", _pt(0.0095)))
        now_str = datetime.datetime.now().strftime("%A, %d %B %Y  %H:%M")
        dw = painter.fontMetrics().horizontalAdvance(now_str)
        painter.drawText(int(W - margin - dw), int(H * 0.062), now_str)

        # ── helpers ───────────────────────────────────────────────────
        def hline(y):
            painter.setPen(QColor(BORDER2))
            painter.drawLine(int(margin), int(y), int(W - margin), int(y))

        def section(x, y, title, color=PH_BLUE):
            painter.setFont(QFont("Arial", _pt(0.011), QFont.Weight.Bold))
            painter.setPen(QColor(color))
            painter.drawText(int(x), int(y), title)

        def draw_kv(x, y, key, val, key_color=TXT_DIM, val_color=TXT_PRI):
            painter.setFont(QFont("Courier New", _pt(0.0095), QFont.Weight.Bold))
            painter.setPen(QColor(key_color))
            painter.drawText(int(x), int(y), key)
            painter.setFont(QFont("Courier New", _pt(0.012)))
            painter.setPen(QColor(val_color))
            painter.drawText(int(x + W * 0.135), int(y), val)

        hline(H * 0.08)

        # ── identification + session summary (two columns) ────────────
        col1_x = margin
        col2_x = W * 0.52
        row_h  = H * 0.030
        y0     = H * 0.105

        prof   = self._active_profile or {}
        inj_id = self.inj_id_edit.text().strip() or "—"
        brand  = prof.get("brand", "—")
        model  = prof.get("model", "—")
        engine = prof.get("engine", "") or "—"
        itype  = prof.get("type", "") or "—"

        section(col1_x, y0, "INJECTOR IDENTIFICATION")
        draw_kv(col1_x, y0 + row_h * 1, "INJECTOR ID", inj_id, val_color=PH_CYAN)
        draw_kv(col1_x, y0 + row_h * 2, "BRAND",       brand)
        draw_kv(col1_x, y0 + row_h * 3, "MODEL",       model)
        draw_kv(col1_x, y0 + row_h * 4, "TYPE",        itype)
        draw_kv(col1_x, y0 + row_h * 5, "ENGINE",      engine)

        # Session summary (real time-series stats)
        h_el = self._session_elapsed // 3600
        m_el = (self._session_elapsed % 3600) // 60
        s_el = self._session_elapsed % 60
        dur_txt = f"{h_el:02d}:{m_el:02d}:{s_el:02d}"
        min_p   = self._min_pressure if self._min_pressure is not None else 0.0

        section(col2_x, y0, "SESSION SUMMARY", PH_AMBER)
        draw_kv(col2_x, y0 + row_h * 1, "DURATION",   dur_txt)
        draw_kv(col2_x, y0 + row_h * 2, "TEST MODE",  self._active_mode, val_color=PH_BLUE)
        draw_kv(col2_x, y0 + row_h * 3, "TOTAL PULSES", f"{self.total_pulses:,}")
        draw_kv(col2_x, y0 + row_h * 4, "PRESSURE",
                f"peak {self._max_pressure:.0f}  avg {self._avg_pressure():.0f} BAR",
                val_color=PH_AMBER)
        draw_kv(col2_x, y0 + row_h * 5, "RPM",
                f"peak {self._max_rpm}  avg {self._avg_rpm()}",
                val_color=PH_PURPLE)

        y_after_info = y0 + row_h * 6 + H * 0.005
        hline(y_after_info)

        # ── CALIBRATION RESULTS table ─────────────────────────────────
        ytab = y_after_info + H * 0.030
        section(margin, ytab, "CALIBRATION RESULTS  —  DELIVERY SPEC", PH_GREEN)

        # column layout (fractions of usable width)
        usable = W - margin * 2
        cols   = ["TEST MODE", "TARGET", "MIN", "MAX", "ACTUAL", "RESULT"]
        cfrac  = [0.30, 0.14, 0.12, 0.12, 0.14, 0.18]
        cx     = []
        acc    = margin
        for fr in cfrac:
            cx.append(acc)
            acc += usable * fr

        # header row
        hdr_y = ytab + H * 0.028
        painter.fillRect(int(margin), int(hdr_y - H * 0.018),
                         int(usable), int(H * 0.024), QColor(HEADER))
        painter.setFont(QFont("Arial", _pt(0.0085), QFont.Weight.Bold))
        painter.setPen(QColor(TXT_DIM))
        for i, c in enumerate(cols):
            painter.drawText(int(cx[i] + W * 0.005), int(hdr_y), c)

        # data rows pulled from the calibration table widget
        t        = self._calib_table
        rh       = H * 0.030
        ry       = hdr_y + H * 0.006
        n_pass   = 0
        n_fail   = 0
        n_tested = 0

        def cell_txt(row, col):
            it = t.item(row, col)
            return it.text().strip() if it and it.text() else "—"

        for r in range(t.rowCount()):
            ry += rh
            mode   = cell_txt(r, 0)
            target = cell_txt(r, 4)
            cmin   = cell_txt(r, 5)
            cmax   = cell_txt(r, 6)
            actual = cell_txt(r, 8)
            status = cell_txt(r, 9)

            # zebra background
            if r % 2 == 0:
                painter.fillRect(int(margin), int(ry - H * 0.020),
                                 int(usable), int(rh), QColor(PANEL))

            painter.setFont(QFont("Courier New", _pt(0.0105), QFont.Weight.Bold))
            painter.setPen(QColor(PH_CYAN))
            painter.drawText(int(cx[0] + W * 0.005), int(ry), mode)

            painter.setFont(QFont("Courier New", _pt(0.0105)))
            painter.setPen(QColor(TXT_PRI))
            painter.drawText(int(cx[1] + W * 0.005), int(ry), target)
            painter.drawText(int(cx[2] + W * 0.005), int(ry), cmin)
            painter.drawText(int(cx[3] + W * 0.005), int(ry), cmax)

            # actual + result
            has_actual = actual not in ("—", "")
            painter.setPen(QColor(PH_BLUE if has_actual else TXT_DIM))
            painter.drawText(int(cx[4] + W * 0.005), int(ry),
                             actual if has_actual else "—")

            if "PASS" in status:
                res_c, res_t = PH_GREEN, "PASS"; n_pass += 1; n_tested += 1
            elif "FAIL" in status:
                res_c, res_t = PH_RED, "FAIL"; n_fail += 1; n_tested += 1
            else:
                res_c, res_t = TXT_DIM, "— not tested"
            painter.setFont(QFont("Courier New", _pt(0.0105), QFont.Weight.Bold))
            painter.setPen(QColor(res_c))
            painter.drawText(int(cx[5] + W * 0.005), int(ry), res_t)

        # overall verdict
        ry += rh * 1.2
        if n_tested == 0:
            verdict_c, verdict = TXT_DIM, "NO MEASUREMENTS ENTERED"
        elif n_fail == 0:
            verdict_c, verdict = PH_GREEN, f"OVERALL: PASS   ({n_pass}/{n_tested} modes)"
        else:
            verdict_c, verdict = PH_RED, f"OVERALL: FAIL   ({n_fail} of {n_tested} modes out of spec)"
        painter.setFont(QFont("Arial", _pt(0.012), QFont.Weight.Bold))
        painter.setPen(QColor(verdict_c))
        painter.drawText(int(margin), int(ry), verdict)

        # ── waveform snapshots (all 3) ────────────────────────────────
        ywav = ry + H * 0.025
        hline(ywav)
        section(margin, ywav + H * 0.028, "WAVEFORM SNAPSHOT", TXT_DIM)

        graphs   = [(self.glw_p, "PRESSURE", G_AMBER),
                    (self.glw_i, "INJECTION", G_GREEN),
                    (self.glw_c, "CAM", G_BLUE)]
        gw       = (usable - W * 0.02) / 3.0
        gy       = ywav + H * 0.040
        gh       = H * 0.075
        painter.setFont(QFont("Arial", _pt(0.008), QFont.Weight.Bold))
        for i, (glw, lbl, clr) in enumerate(graphs):
            gx  = margin + i * (gw + W * 0.01)
            # Fill the box exactly (scope strips are wide & short) + border
            pm  = glw.grab().scaled(
                int(gw), int(gh),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap(int(gx), int(gy), pm)
            painter.setPen(QColor(BORDER2))
            painter.drawRect(int(gx), int(gy), int(gw), int(gh))
            painter.setPen(QColor(clr))
            painter.drawText(int(gx), int(gy + gh + H * 0.020), lbl)

        # ── signature line ────────────────────────────────────────────
        ysig = gy + gh + H * 0.05
        painter.setPen(QColor(BORDER2))
        painter.drawLine(int(margin), int(ysig), int(margin + W * 0.30), int(ysig))
        painter.drawLine(int(W - margin - W * 0.30), int(ysig),
                         int(W - margin), int(ysig))
        painter.setFont(QFont("Arial", _pt(0.0085)))
        painter.setPen(QColor(TXT_DIM))
        painter.drawText(int(margin), int(ysig + H * 0.018), "Technician signature")
        painter.drawText(int(W - margin - W * 0.30), int(ysig + H * 0.018),
                         "Date / Stamp")

        # ── footer ────────────────────────────────────────────────────
        painter.setPen(QColor(TXT_DIM))
        painter.setFont(QFont("Arial", _pt(0.009)))
        painter.drawText(int(margin), int(H * 0.97),
                         "INJECTOR PRO  ·  Diesel Injection Test System")
        painter.drawText(int(W - margin - W * 0.1), int(H * 0.97), "Page 1 / 1")

        painter.end()
        QMessageBox.information(self, "Report Saved",
                                f"PDF report saved to:\n{path}")

    # ──────────────────────────────────────────────────────────────────
    #  FEATURE 3 — Freeze / Unfreeze Graph Display
    # ──────────────────────────────────────────────────────────────────
    def _toggle_freeze(self, checked: bool):
        self._display_frozen = checked
        if checked:
            self._freeze_status.setText(self._display_text("  FROZEN"))
            self._freeze_status.setStyleSheet(
                f"color:{PH_AMBER}; font-size:10px; font-family:monospace;")
        else:
            self._freeze_status.setText(self._display_text("  LIVE"))
            self._freeze_status.setStyleSheet(
                f"color:{PH_GREEN}; font-size:10px; font-family:monospace;")
            # Force immediate redraw on unfreeze
            self._graph_dirty = True

    # ──────────────────────────────────────────────────────────────────
    #  FEATURE 4 — Visual Safety Alarms (blink timer)
    # ──────────────────────────────────────────────────────────────────
    def _check_alarms(self):
        self._p_alarm = (self._snap_p >= PRESSURE_WARN)
        self._r_alarm = (self._snap_r >= RPM_WARN)

    def _blink_tick(self):
        self._blink_state = not self._blink_state
        bg  = PANEL    if self._dark_mode else "#FFFFFF"
        bdr = BORDER2  if self._dark_mode else "#D1D1D6"

        if self._p_alarm:
            color  = PH_RED if self._snap_p >= PRESSURE_ALARM else PH_AMBER
            border = color if self._blink_state else bdr
            bw     = "2px" if self._blink_state else "1px"
            self.frame_p.setStyleSheet(
                f"background:{bg}; border:{bw} solid {border}; border-radius:6px;")
        else:
            self.frame_p.setStyleSheet(
                f"background:{bg}; border:1px solid {bdr}; border-radius:6px;")

        if self._r_alarm:
            color  = PH_RED if self._snap_r >= RPM_ALARM else PH_AMBER
            border = color if self._blink_state else bdr
            bw     = "2px" if self._blink_state else "1px"
            self.frame_r.setStyleSheet(
                f"background:{bg}; border:{bw} solid {border}; border-radius:6px;")
        else:
            self.frame_r.setStyleSheet(
                f"background:{bg}; border:1px solid {bdr}; border-radius:6px;")

    # ──────────────────────────────────────────────────────────────────
    #  FEATURE 5 — Light / Dark Theme Toggle
    # ──────────────────────────────────────────────────────────────────
    def _toggle_theme(self):
        self._dark_mode = not self._dark_mode
        dk = self._dark_mode
        self.setStyleSheet(STYLE_DARK if dk else STYLE_LIGHT)
        self.theme_btn.setText(self._display_text("LIGHT MODE" if dk else "DARK MODE"))

        # Swap the application palette so Fusion matches the active theme
        app = QApplication.instance()
        if dk:
            p = QPalette()
            p.setColor(QPalette.ColorRole.Window,         QColor(BG))
            p.setColor(QPalette.ColorRole.WindowText,      QColor(TXT_PRI))
            p.setColor(QPalette.ColorRole.Base,            QColor(PANEL))
            p.setColor(QPalette.ColorRole.AlternateBase,   QColor(BORDER))
            p.setColor(QPalette.ColorRole.Text,            QColor(TXT_PRI))
            p.setColor(QPalette.ColorRole.Button,          QColor(BORDER))
            p.setColor(QPalette.ColorRole.ButtonText,      QColor(TXT_PRI))
            p.setColor(QPalette.ColorRole.Highlight,       QColor(PH_BLUE))
            p.setColor(QPalette.ColorRole.HighlightedText, QColor('#FFFFFF'))
            p.setColor(QPalette.ColorGroup.Disabled,
                       QPalette.ColorRole.WindowText,      QColor(TXT_DIM))
            p.setColor(QPalette.ColorGroup.Disabled,
                       QPalette.ColorRole.Text,            QColor(TXT_DIM))
            app.setPalette(p)
        else:
            p = QPalette()
            p.setColor(QPalette.ColorRole.Window,         QColor('#F2F2F7'))
            p.setColor(QPalette.ColorRole.WindowText,      QColor('#1C1C1E'))
            p.setColor(QPalette.ColorRole.Base,            QColor('#FFFFFF'))
            p.setColor(QPalette.ColorRole.AlternateBase,   QColor('#E5E5EA'))
            p.setColor(QPalette.ColorRole.Text,            QColor('#1C1C1E'))
            p.setColor(QPalette.ColorRole.Button,          QColor('#E5E5EA'))
            p.setColor(QPalette.ColorRole.ButtonText,      QColor('#1C1C1E'))
            p.setColor(QPalette.ColorRole.Highlight,       QColor('#0A84FF'))
            p.setColor(QPalette.ColorRole.HighlightedText, QColor('#FFFFFF'))
            app.setPalette(p)

        self._apply_theme_widgets()

    def _apply_theme_widgets(self):
        dk = self._dark_mode

        # ── button text reflects current mode ─────────────────────────
        self.theme_btn.setText(self._display_text("LIGHT MODE" if dk else "DARK MODE"))

        # ── restyle the measurement meters + INJ / ENGINE frames ─────
        # These are built once with the boot-time `dk` and never touched
        # after that, so a theme toggle would leave the LCD screens dark
        # against a white page. Redo their stylesheets from the current dk.
        if hasattr(self, 'lcd_r'):
            for lcd, color in ((self.lcd_r, PH_PURPLE),
                               (self.lcd_p, PH_AMBER),
                               (self.lcd_a, PH_BLUE)):
                lcd_bg  = G_BG        if dk else '#FBFCFD'
                lcd_bdr = f"{color}28" if dk else f"{color}45"
                lcd.setStyleSheet(
                    f"QLCDNumber{{color:{color}; background:{lcd_bg};"
                    f" border:1px solid {lcd_bdr}; border-radius:4px;}}")
            frame_bg  = PANEL   if dk else '#FFFFFF'
            frame_bdr = BORDER2 if dk else '#E0E0E6'
            for f in (self.frame_r, self.frame_p, self.frame_a):
                f.setStyleSheet(
                    f"background:{frame_bg}; border:1px solid {frame_bdr}; border-radius:6px;")
        if hasattr(self, 'frame_inj'):
            self.frame_inj.setStyleSheet(
                f"background:{'#1C1C1E' if dk else '#FFFFFF'};"
                f" border:1px solid {'#2C2C2E' if dk else '#E0E0E6'}; border-radius:6px;")
            self._led_off_style = (
                f"background:{'#0A1A0D' if dk else '#EAF7EE'}; border-radius:10px;"
                f" border:2px solid {'#1A3A20' if dk else '#BEE3C7'};")
            self.inj_led.setStyleSheet(self._led_off_style)
        if hasattr(self, 'frame_engine'):
            self.frame_engine.setStyleSheet(
                f"background:{PANEL if dk else '#FFFFFF'};"
                f" border:1px solid {BORDER2 if dk else '#E0E0E6'}; border-radius:6px;")

        # ── coils panel — each row rebuilt from the current theme ────
        if hasattr(self, '_coil_frames'):
            for i in range(len(self._coil_frames)):
                self._style_coil_row(i)

        # ── relay + calibration table need a repaint too ─────────────
        if hasattr(self, 'relay_btn'):
            self._style_relay_btn()
        if hasattr(self, '_calib_table'):
            self._calib_table.setStyleSheet(self._calib_table_style(dk))

        # ── Q INJECT cylinder gauges (custom-painted) ─────────────────
        if hasattr(self, '_cylinders'):
            for cg in self._cylinders.values():
                cg.set_dark(dk)

        # ── header bar ────────────────────────────────────────────────
        if dk:
            self._header_bar.setStyleSheet(
                f"background:{HEADER}; border-bottom:1px solid {BORDER2};")
        else:
            self._header_bar.setStyleSheet(
                "background:#FFFFFF; border-bottom:1px solid #E0E0E6;")

        # ── theme toggle button ───────────────────────────────────────
        if dk:
            self.theme_btn.setStyleSheet(f"""
                QPushButton       {{background:{BORDER};color:{TXT_SEC};
                                    border:1px solid {BORDER2};border-radius:6px;
                                    font-size:10px;padding:0 10px;font-weight:500;}}
                QPushButton:hover {{background:{BORDER2};color:{TXT_PRI};border-color:{PH_BLUE};}}
                QPushButton:pressed {{background:{BG};color:{TXT_PRI};}}
            """)
        else:
            self.theme_btn.setStyleSheet("""
                QPushButton       {background:#E5E5EA;color:#3C3C43;
                                    border:1px solid #C7C7CC;border-radius:6px;
                                    font-size:10px;padding:0 10px;font-weight:500;}
                QPushButton:hover {background:#D1D1D6;color:#1C1C1E;border-color:#0A84FF;}
                QPushButton:pressed {background:#AEAEB2;color:#1C1C1E;}
            """)

        # ── START button ──────────────────────────────────────────────
        if dk:
            self.start_btn.setStyleSheet(f"""
                QPushButton         {{background:#0A2218;color:{PH_GREEN};
                                      border:1px solid #163C28;border-radius:7px;font-weight:600;}}
                QPushButton:hover   {{background:#163C28;border-color:{PH_GREEN};}}
                QPushButton:pressed {{background:#061009;}}
            """)
        else:
            self.start_btn.setStyleSheet("""
                QPushButton         {background:#D4F5E2;color:#1A6B3A;
                                      border:1px solid #A8DFC0;border-radius:7px;font-weight:600;}
                QPushButton:hover   {background:#A8DFC0;border-color:#30D158;}
                QPushButton:pressed {background:#7DC49A;}
            """)

        # ── STOP button ───────────────────────────────────────────────
        if dk:
            self.stop_btn.setStyleSheet(f"""
                QPushButton         {{background:#2A1010;color:{PH_RED};
                                      border:1px solid #44181A;border-radius:7px;font-weight:600;}}
                QPushButton:hover   {{background:#44181A;border-color:{PH_RED};}}
                QPushButton:pressed {{background:#100506;}}
            """)
        else:
            self.stop_btn.setStyleSheet("""
                QPushButton         {background:#FFE5E3;color:#C0281E;
                                      border:1px solid #FFBBBA;border-radius:7px;font-weight:600;}
                QPushButton:hover   {background:#FFBBBA;border-color:#FF453A;}
                QPushButton:pressed {background:#FFAAAA;}
            """)

        # ── SYNC button ───────────────────────────────────────────────
        if dk:
            self.sync_btn.setStyleSheet(f"""
                QPushButton       {{background:#081428;color:{PH_BLUE};
                                    border:1px solid #102248;border-radius:7px;font-size:11px;font-weight:500;}}
                QPushButton:hover {{background:#102248;color:{TXT_PRI};border-color:{PH_BLUE};}}
                QPushButton:pressed {{background:#050C18;color:{TXT_PRI};}}
            """)
        else:
            self.sync_btn.setStyleSheet("""
                QPushButton       {background:#E5F0FF;color:#0A5CC7;
                                    border:1px solid #B8D4FF;border-radius:7px;font-size:11px;font-weight:500;}
                QPushButton:hover {background:#B8D4FF;color:#063A8A;border-color:#0A84FF;}
                QPushButton:pressed {background:#98C0F5;}
            """)

        # ── SAVE REPORT button ────────────────────────────────────────
        if dk:
            self.report_btn.setStyleSheet(f"""
                QPushButton       {{background:#081A12;color:{PH_GREEN};
                                    border:1px solid #102C1E;border-radius:7px;font-size:11px;font-weight:500;}}
                QPushButton:hover {{background:#102C1E;color:{TXT_PRI};border-color:{PH_GREEN};}}
                QPushButton:pressed {{background:#040D09;color:{TXT_PRI};}}
            """)
        else:
            self.report_btn.setStyleSheet("""
                QPushButton       {background:#D4F5E2;color:#1A6B3A;
                                    border:1px solid #A8DFC0;border-radius:7px;font-size:11px;font-weight:500;}
                QPushButton:hover {background:#A8DFC0;color:#0F4A28;border-color:#30D158;}
                QPushButton:pressed {background:#7DC49A;}
            """)

        # ── CSV button ───────────────────────────────────────────────
        if dk:
            self.csv_btn.setStyleSheet(f"""
                QPushButton       {{background:#0A1820;color:{PH_CYAN};
                                    border:1px solid #122838;border-radius:7px;font-size:11px;font-weight:500;}}
                QPushButton:hover {{background:#122838;color:{TXT_PRI};border-color:{PH_CYAN};}}
                QPushButton:pressed {{background:#050C10;color:{TXT_PRI};}}
            """)
        else:
            self.csv_btn.setStyleSheet("""
                QPushButton       {background:#D4F0F5;color:#0A6B7A;
                                    border:1px solid #A0D8E0;border-radius:7px;font-size:11px;font-weight:500;}
                QPushButton:hover {background:#A0D8E0;color:#064A56;border-color:#30B0C7;}
                QPushButton:pressed {background:#70C0CC;}
            """)

        # ── ZERO button ───────────────────────────────────────────────
        if dk:
            self.zero_btn.setStyleSheet(f"""
                QPushButton       {{background:#1A1008;color:{PH_AMBER};
                                    border:1px solid #3A2810;border-radius:7px;
                                    font-size:11px;font-weight:600;}}
                QPushButton:hover {{background:#2A1A0C;color:{TXT_PRI};border-color:{PH_AMBER};}}
                QPushButton:pressed {{background:#100800;}}
            """)
        else:
            self.zero_btn.setStyleSheet("""
                QPushButton       {background:#FFF3D4;color:#7A4800;
                                    border:1px solid #FFD980;border-radius:7px;
                                    font-size:11px;font-weight:600;}
                QPushButton:hover {background:#FFE9A8;color:#4A2A00;border-color:#FF9F0A;}
                QPushButton:pressed {background:#FFDB8A;}
            """)

        # ── FREEZE button ─────────────────────────────────────────────
        # Only present if the waveform panel is built.
        if not hasattr(self, 'freeze_btn'):
            return
        if dk:
            self.freeze_btn.setStyleSheet(f"""
                QPushButton         {{background:{BORDER};color:{PH_BLUE};
                                      border:1px solid {BORDER2};border-radius:6px;
                                      font-size:10px;padding:0 12px;font-weight:500;}}
                QPushButton:hover   {{background:{BORDER2};color:{TXT_PRI};border-color:{PH_BLUE};}}
                QPushButton:checked {{background:#241E08;color:{PH_AMBER};border-color:{PH_AMBER};}}
                QPushButton:checked:hover {{background:#352C0C;border-color:{PH_AMBER};}}
            """)
        else:
            self.freeze_btn.setStyleSheet("""
                QPushButton         {background:#E5F0FF;color:#0A84FF;
                                      border:1px solid #B8D4FF;border-radius:6px;
                                      font-size:10px;padding:0 12px;font-weight:500;}
                QPushButton:hover   {background:#B8D4FF;color:#063A8A;border-color:#0A84FF;}
                QPushButton:checked {background:#FFF3D4;color:#9A5E00;border-color:#FFDB8A;}
                QPushButton:checked:hover {background:#FFE9A8;border-color:#FF9F0A;}
            """)

        # ── meter frames (alarm-border targets) ───────────────────────
        frame_ss = (f"background:{PANEL}; border:1px solid {BORDER2}; border-radius:6px;"
                    if dk else
                    "background:#FFFFFF; border:1px solid #D1D1D6; border-radius:6px;")
        self.frame_p.setStyleSheet(frame_ss)
        self.frame_r.setStyleSheet(frame_ss)

        # ── re-apply connection button for current state ───────────────
        self._style_conn_btn(self.worker.is_running)

        # ── PyQtGraph oscilloscope ─────────────────────────────────────
        if dk:
            graph_bg   = BG
            axis_clr   = BORDER
            grid_alpha = 0.18
            axis_txt   = TXT_DIM
        else:
            graph_bg   = '#FFFFFF'
            axis_clr   = '#D1D1D6'
            grid_alpha = 0.30
            axis_txt   = '#AEAEB2'
        for _glw in [self.glw_p, self.glw_i, self.glw_c]:
            _glw.setBackground(graph_bg)

        # ── _dim() labels and meter frame labels — re-style on toggle ──
        dim_color   = TXT_DIM  if dk else '#3A3A4A'
        dim_ss      = (f"color:{dim_color}; font-size:9px; font-weight:bold;"
                       f" letter-spacing:1px; font-family:monospace;")
        frame_bg    = PANEL    if dk else '#FFFFFF'
        frame_bdr   = BORDER2  if dk else '#E0E0E6'
        frame_ss    = f"background:{frame_bg}; border:1px solid {frame_bdr}; border-radius:6px;"

        for w in self.findChildren(QLabel):
            ss = w.styleSheet()
            # update _dim() labels
            if 'letter-spacing:1px' in ss and 'font-size:9px' in ss:
                w.setStyleSheet(dim_ss)
            # update meter title labels (letter-spacing:2px, no border-color logic)
            elif 'letter-spacing:2px' in ss and 'font-family:monospace' in ss and 'border:none' in ss:
                # extract the color from existing style and rebuild with correct alpha
                for acc in [PH_PURPLE, PH_AMBER, PH_GREEN, PH_BLUE]:
                    if acc[:7].lower() in ss.lower():
                        new_c = acc if not dk else f"{acc}50"
                        w.setStyleSheet(
                            f"color:{new_c}; font-size:9px; font-weight:bold;"
                            f" letter-spacing:2px; font-family:monospace; border:none;")
                        break
            # update unit labels (no letter-spacing, has border:none)
            elif 'font-size:10px' in ss and 'font-family:monospace' in ss and 'border:none' in ss:
                for acc in [PH_PURPLE, PH_AMBER, PH_GREEN, PH_BLUE]:
                    if acc[:7].lower() in ss.lower():
                        new_c = f"{acc}CC" if not dk else f"{acc}60"
                        w.setStyleSheet(
                            f"color:{new_c}; font-size:10px; font-family:monospace; border:none;")
                        break

        # re-apply meter frame backgrounds (ALL boxes, not just R & P)
        for frame in [self.frame_r, self.frame_p, self.frame_a,
                      self.frame_inj, self.frame_engine]:
            frame.setStyleSheet(frame_ss)

        # ── LCD digit displays — dark glass in dark mode, white in light ─
        lcd_bg     = G_BG      if dk else '#FFFFFF'
        lcd_border = '28'      if dk else '55'   # alpha on accent border
        for lcd, accent in [(self.lcd_r, PH_PURPLE), (self.lcd_p, PH_AMBER),
                            (self.lcd_a, PH_BLUE)]:
            lcd.setStyleSheet(
                f"QLCDNumber{{color:{accent}; background:{lcd_bg};"
                f" border:1px solid {accent}{lcd_border}; border-radius:4px;}}")

        # ── INJ PULSE LED off-state — light tint in light mode ──────────
        if dk:
            self._led_off_style = ("background:#0A1A0D; border-radius:10px;"
                                   " border:2px solid #1A3A20;")
        else:
            self._led_off_style = ("background:#E8F5EC; border-radius:10px;"
                                   " border:2px solid #BFE5CC;")
        if not self._led_timer.isActive():       # don't override an active flash
            self.inj_led.setStyleSheet(self._led_off_style)

        # ── Auto-Reconnect checkbox — keep label readable in both modes ──
        cb_color = TXT_SEC if dk else '#3A3A4A'
        self.autoreconn_cb.setStyleSheet(
            f"color:{cb_color}; font-size:10px;")

        # ── Cylinder gauges — repaint with theme colors ────────────────
        if hasattr(self, '_cylinders'):
            for cg in self._cylinders.values():
                cg.set_dark(dk)

        # ── Coil boxes — re-tint frames, name fields and buttons ───────
        if hasattr(self, '_coil_frames'):
            for i in range(COIL_COUNT):
                self._style_coil_row(i)

        # ── Relay button — re-tint for the current theme ───────────────
        if hasattr(self, 'relay_btn'):
            self._style_relay_btn()

        # ── Calibration table — swap dark/light palette ────────────────
        if hasattr(self, '_calib_table'):
            self._calib_table.setStyleSheet(self._calib_table_style(dk))
            # re-tint row backgrounds for current theme
            self._populate_calib_table(self._active_profile)

    # ── actions ───────────────────────────────────────────────────────
    def _send_validated(self, cmd: str):
        """Send a command through the safety validator, then to ESP32."""
        ok   = True
        warn = ""
        if cmd.startswith("w"):
            ok, val, warn = self._safety.validate_pulse(int(cmd[1:]))
            cmd = f"w{val}"
        elif cmd.startswith("f"):
            ok, val, warn = self._safety.validate_freq(int(cmd[1:]))
            cmd = f"f{val}"
        elif cmd.startswith("a"):
            ok, val, warn = self._safety.validate_delay(int(cmd[1:]))
            cmd = f"a{val}"
        if warn:
            self._comm_log(f"⚠  {warn}", PH_AMBER)
        self._comm_log(f"TX  {cmd}", PH_BLUE)
        self.worker.send_command(cmd)

    def _on_start(self):
        # Re-sync params through validator before start
        self._send_validated(f"w{self.pw_sp.value()}")
        self._send_validated(f"f{self.fr_sp.value()}")
        self._send_validated(f"a{self.an_sp.value()}")
        self.worker.send_command("start")
        self._comm_log("▶  START", PH_GREEN)
        self.graph_paused     = False
        self._session_start   = datetime.datetime.now()
        self._session_elapsed = 0
        # ── reset session statistics ──────────────────────────────────
        self._max_pressure    = 0.0
        self._min_pressure    = None
        self._sum_pressure    = 0.0
        self._cnt_pressure    = 0
        self._sum_rpm         = 0.0
        self._cnt_rpm         = 0
        self._max_rpm         = 0
        self.total_pulses     = 0
        self.run_lbl.setText(self._display_text("RUNNING"))
        self.run_lbl.setStyleSheet(
            f"color:{PH_GREEN}; font-family:monospace; border:none;")
        self.hdr_timer.setStyleSheet(
            f"color:{PH_GREEN}; font-size:11px; font-family:monospace;")

    def _on_stop(self):
        self.worker.send_command("stop")
        self._comm_log("■  STOP", PH_RED)
        self.graph_paused   = True
        # Auto-log session
        self._log_session()
        self._session_start = None
        self.run_lbl.setText(self._display_text("STOPPED"))
        self.run_lbl.setStyleSheet(
            f"color:{PH_RED}; font-family:monospace; border:none;")
        self.hdr_timer.setStyleSheet(
            f"color:{TXT_DIM}; font-size:11px; font-family:monospace;")

    def _avg_pressure(self) -> float:
        return self._sum_pressure / self._cnt_pressure if self._cnt_pressure else 0.0

    def _avg_rpm(self) -> int:
        return round(self._sum_rpm / self._cnt_rpm) if self._cnt_rpm else 0

    def _log_session(self):
        """Auto-save session to CSV log."""
        p = self._active_profile or {}
        row = {
            "timestamp":       datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "injector_id":     self.inj_id_edit.text().strip() or "—",
            "brand":           p.get("brand", "—"),
            "model":           p.get("model", "—"),
            "mode":            self._active_mode,
            "pulse_us":        self.pw_sp.value(),
            "freq_hz":         self.fr_sp.value(),
            "delay_deg":       self.an_sp.value(),
            "duration_s":      self._session_elapsed,
            "total_pulses":    self.total_pulses,
            "max_pressure_bar":f"{self._max_pressure:.1f}",
            "avg_pkt_s":       self._pkt_rate,
        }
        self._session_logger.log(row)

    # ── Session 1Hz tick ──────────────────────────────────────────────
    def _session_tick(self):
        if self._session_start is not None:
            self._session_elapsed = int(
                (datetime.datetime.now() - self._session_start).total_seconds())
            h = self._session_elapsed // 3600
            m = (self._session_elapsed % 3600) // 60
            s = self._session_elapsed % 60
            self.hdr_timer.setText(f"⏱  {h:02d}:{m:02d}:{s:02d}")
            # Auto-stop
            if self._auto_stop_secs > 0 and self._session_elapsed >= self._auto_stop_secs:
                self._on_stop()
        else:
            self.hdr_timer.setText("⏱  00:00:00")

    # ── Watchdog — stale data detection ──────────────────────────────
    def _watchdog_tick(self):
        if not self.worker.is_running:
            return
        age = time.time() - self._last_data_time
        if self._last_data_time > 0 and age > 3.0:
            if not self._watchdog_stale:
                self._watchdog_stale = True
                self.hdr_conn.setText(self._display_text("⚠  NO DATA"))
                self.hdr_conn.setStyleSheet(
                    f"color:{PH_AMBER}; font-size:11px; font-family:monospace;")
        else:
            if self._watchdog_stale:
                self._watchdog_stale = False
                port = self.port_combo.currentText()
                self.hdr_conn.setText(self._display_text(f"●  {port}  CONNECTED"))
                self.hdr_conn.setStyleSheet(
                    f"color:{PH_GREEN}; font-size:11px; font-family:monospace;")

    # ── Auto-reconnect ────────────────────────────────────────────────
    def _try_reconnect(self):
        if self._auto_reconnect and not self.worker.is_running:
            self.worker.reconnect()

    # ── Packet rate from worker ───────────────────────────────────────
    def _on_pkt_tick(self, pps):
        self._pkt_rate = pps
        color = PH_GREEN if pps >= 80 else PH_AMBER if pps >= 30 else PH_RED
        self.hdr_pkt.setText(self._display_text(f"PKT: {pps}/s"))
        self.hdr_pkt.setStyleSheet(
            f"color:{color}; font-size:11px; font-family:monospace;")

    # ── Export CSV ────────────────────────────────────────────────────
    def _export_csv(self):
        import csv, os
        ts  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        inj = self.inj_id_edit.text().strip() or "unknown"
        default = os.path.expanduser(f"~/Desktop/INJ_{inj}_{ts}.csv")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", default, "CSV Files (*.csv)")
        if not path:
            return
        preset = self.preset_combo.currentText()
        mode   = "CamBox" if self._mode_id == 1 else "Custom"
        try:
            with open(path, 'w', newline='', encoding='utf-8') as f:
                w = csv.writer(f)
                w.writerow(["INJECTOR PRO — Test Session Export"])
                w.writerow(["Timestamp",      ts])
                w.writerow(["Injector ID",    inj])
                w.writerow(["Preset",         preset])
                w.writerow(["Mode",           mode])
                w.writerow(["Pulse Width µs", self.pw_sp.value()])
                w.writerow(["Frequency Hz",   self.fr_sp.value()])
                w.writerow(["Delay Angle °",  self.an_sp.value()])
                w.writerow(["Total Pulses",   self.total_pulses])
                w.writerow(["Session s",      self._session_elapsed])
                w.writerow(["Avg PKT/s",      self._pkt_rate])
                w.writerow([])
                w.writerow(["Session Statistics", "Min", "Avg", "Max", "Unit"])
                _minp = self._min_pressure if self._min_pressure is not None else 0.0
                w.writerow(["Pressure", f"{_minp:.1f}",
                            f"{self._avg_pressure():.1f}",
                            f"{self._max_pressure:.1f}", "BAR"])
                w.writerow(["RPM", "—", self._avg_rpm(), self._max_rpm, "RPM"])
                w.writerow([])
                w.writerow(["Live Reading (at export)", "Value", "Unit"])
                w.writerow(["Pressure",  f"{self._snap_p:.1f}", "BAR"])
                w.writerow(["RPM",       self._snap_r,          "RPM"])
                w.writerow(["Inj Rate",  f"{self._snap_i:.1f}", "inj/s"])
            QMessageBox.information(self, "Export CSV",
                f"Saved:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    def _on_mode(self, mid):
        # Use the explicit MODE CAM / MODE PUMP setters (not the `mode` toggle)
        # so we always land in the intended firmware mode, regardless of what
        # it was in before. mid==0 = Common Rail (MODE_PUMP), mid==1 = CamBox
        # (MODE_CAM = proximity-synced pulse).
        if mid == 1:
            self.worker.send_command("MODE CAM")
        else:
            self.worker.send_command("MODE PUMP")
        self._mode_id = mid
        self._cam_visible(mid == 1)

        # Coil channels get set based on mode:
        #   CamBox (mid==1)      → EUI (Coil 2) fires with the cam sensor.
        #                          Coil 1 (Metering Valve) stays disabled.
        #   Common Rail (mid==0) → MV (Coil 1) closed-loop pressure control.
        #                          Coil 2 & 3 injector pulse channels disabled.
        # Coil 1 is the Metering Valve — it has its own MV_ENABLE gate, not
        # the injector COIL 1 ON/OFF enable mask, so we don't touch it here.
        # Coil 2 and Coil 3 use the injector enable mask.
        if mid == 1:            # CamBox
            self.worker.send_command("COIL 2 ON")
            self.worker.send_command("COIL 3 OFF")
            for idx, on in ((1, True), (2, False)):
                tog = self._coil_toggles[idx]
                tog.blockSignals(True); tog.setChecked(on); tog.blockSignals(False)
                tog.setText("ON" if on else "OFF")
                self._coil_on[idx] = on; self._style_coil_row(idx)
            self._comm_log("TX  CamBox → COIL 2 ON · COIL 3 OFF · MV disabled",
                           PH_PURPLE)
        else:                   # Common Rail
            self.worker.send_command("COIL 2 OFF")
            self.worker.send_command("COIL 3 OFF")
            for idx in (1, 2):
                tog = self._coil_toggles[idx]
                tog.blockSignals(True); tog.setChecked(False); tog.blockSignals(False)
                tog.setText("OFF")
                self._coil_on[idx] = False; self._style_coil_row(idx)
            # Auto-prime the Metering Valve for hands-on use:
            #   MANUAL mode + duty 0 + ENABLE ON  →  moving the DUTY knob (or
            #   switching to PRESSURE + setting TARGET_P) drives the valve
            #   immediately. No hidden ENABLE step to trip over.
            if hasattr(self, 'mv_mode_combo'):
                self.mv_mode_combo.blockSignals(True)
                self.mv_mode_combo.setCurrentIndex(1)   # MANUAL
                self.mv_mode_combo.blockSignals(False)
                self.worker.send_command("MV_MODE MANUAL")
            if hasattr(self, 'mv_duty'):
                self.mv_duty.blockSignals(True); self.mv_duty.setValue(0); self.mv_duty.blockSignals(False)
                self.worker.send_command("MV_DUTY 0")
            if hasattr(self, 'mv_enable_btn'):
                btn = self.mv_enable_btn
                btn.blockSignals(True); btn.setChecked(True); btn.blockSignals(False)
                btn.setText("ENABLED")
                self._coil_on[0] = True; self._style_coil_row(0)
                self.worker.send_command("MV_ENABLE ON")
            # visual affordance for the mode/duty controls
            if hasattr(self, '_on_mv_mode'):
                self._on_mv_mode(1)
            self._comm_log("TX  Common Rail → MODE PUMP · MV auto-primed "
                           "(MANUAL · duty=0 · ENABLED)  turn DUTY to drive",
                           PH_BLUE)
        if mid == 0:
            # Custom mode: lock RPM to zero + clear all buffers
            self._rpm_ema = 0.0
            self._snap_r  = 0
            self._rpm_win.clear()
            self._inj_win.clear()
            self.cam_buf  = deque([0.0] * N_SAMPLES, maxlen=N_SAMPLES)
            self.mode_lbl.setText("COMMON RAIL")
            self.mode_lbl.setStyleSheet(
                f"color:{PH_BLUE}; font-size:11px; font-family:monospace;"
                f" letter-spacing:1px; border:none;")
            self.hdr_mode.setText("  COMMON RAIL")
            self.hdr_mode.setStyleSheet(
                f"color:{PH_BLUE}; font-size:11px; font-family:monospace;")
        else:
            self.mode_lbl.setText("CAMBOX")
            self.mode_lbl.setStyleSheet(
                f"color:{PH_PURPLE}; font-size:11px; font-family:monospace;"
                f" letter-spacing:1px; border:none;")
            self.hdr_mode.setText("  CAMBOX MODE")
            self.hdr_mode.setStyleSheet(
                f"color:{PH_PURPLE}; font-size:11px; font-family:monospace;")

        # Update mode switch button to show what you'll switch TO
        if hasattr(self, 'mode_switch_btn'):
            if mid == 0:   # currently Common Rail → button offers CamBox
                self.mode_switch_btn.setText("⇄  CAM BOX")
                self.mode_switch_btn.setStyleSheet(f"""
                    QPushButton       {{background:#18102A;border:1px solid {PH_PURPLE};
                                        color:{PH_PURPLE};padding:0 12px;border-radius:6px;
                                        font-size:10px;font-weight:bold;letter-spacing:1px;
                                        font-family:monospace;}}
                    QPushButton:hover {{background:{PH_PURPLE};color:#FFFFFF;}}
                    QPushButton:pressed {{background:#9040C8;color:#FFFFFF;}}
                """)
            else:          # currently CamBox → button offers Common Rail
                self.mode_switch_btn.setText("⇄  COMMON RAIL")
                self.mode_switch_btn.setStyleSheet(f"""
                    QPushButton       {{background:#0A1828;border:1px solid {PH_BLUE};
                                        color:{PH_BLUE};padding:0 12px;border-radius:6px;
                                        font-size:10px;font-weight:bold;letter-spacing:1px;
                                        font-family:monospace;}}
                    QPushButton:hover {{background:{PH_BLUE};color:#FFFFFF;}}
                    QPushButton:pressed {{background:#0060CC;color:#FFFFFF;}}
                """)

    def _toggle_mode(self):
        """Switch between Common Rail (0) and CamBox (1)."""
        new_mid = 0 if self._mode_id == 1 else 1
        self.rb_custom.setChecked(new_mid == 0)
        self.rb_cam.setChecked(new_mid == 1)
        self._on_mode(new_mid)

    def _on_rpm_divisor(self, val):
        self._rpm_divisor = val
        self._settings.setValue("rpm_divisor", val)   # persist across restarts

    def _on_pressure_divisor(self, val):
        # Displayed bar and TARGET_P scaling both pick this up immediately.
        # No need to re-send TARGET_P — next time the user changes it, or the
        # next PID cycle if PRESSURE mode is active on the MV, it uses the
        # new divisor. The live display switches to the new value on the very
        # next telemetry packet (10 ms).
        self._pressure_divisor = val
        self._settings.setValue("pressure_divisor", val)
        self._comm_log(f"PRESSURE DIVISOR = {val:.2f}", PH_AMBER)

    def _refresh_ports(self):
        if not self.worker.is_running:
            ports = [p.device for p in serial.tools.list_ports.comports()]
            cur   = self.port_combo.currentText()
            self.port_combo.blockSignals(True)
            self.port_combo.clear()
            self.port_combo.addItems(ports)
            if cur in ports:
                self.port_combo.setCurrentText(cur)
            self.port_combo.blockSignals(False)

    def _auto_connect_esp32(self):
        if self.worker.is_running:
            return
        port = _find_esp32_port()
        if not port:
            return
        self.port_combo.setCurrentText(port)
        self.worker.connect_device(port, int(self.baud_combo.currentText()))

    def _toggle_conn(self):
        if not self.worker.is_running:
            port = self.port_combo.currentText()
            baud = int(self.baud_combo.currentText())
            if port:
                self.worker.connect_device(port, baud)
            else:
                QMessageBox.warning(self, "No Port", "No COM ports found.")
        else:
            self.worker.disconnect_device()

    def _set_pressure_zero(self):
        """Auto-calibrate zero: snap P_VX4_ZERO_MV to current EMA reading."""
        if self._p_vx4_ema < 10:
            QMessageBox.warning(self, "SET ZERO",
                "No sensor data yet — connect ESP32 first.")
            return
        global P_VX4_ZERO_MV
        P_VX4_ZERO_MV   = round(self._p_vx4_ema, 1)
        self._p_vx4_ema = 0.0
        self._snap_p    = 0.0
        QMessageBox.information(self, "SET ZERO",
            f"Zero calibrated.\nP_VX4_ZERO_MV = {P_VX4_ZERO_MV:.1f} mV")

    def _sync(self):
        self._send_validated(f"w{self.pw_sp.value()}")
        self._send_validated(f"f{self.fr_sp.value()}")
        self._send_validated(f"a{self.an_sp.value()}")
        self.worker.send_command("COILS")     # re-read the board's coil mask
        self.worker.send_command("RELAY")     # re-read the board's relay state
        self.worker.send_command("CINFO")     # re-read per-coil freq + run state
        self._comm_log("↺  SYNC", PH_CYAN)

    def _on_conn(self, ok):
        self._style_conn_btn(ok)
        if ok:
            self.conn_btn.setText(self._display_text("DISCONNECT"))
            self.conn_lbl.setText(self._display_text("●  CONNECTED"))
            self.conn_lbl.setStyleSheet(
                f"color:{PH_GREEN}; font-weight:bold; font-size:11px; font-family:monospace;")
            port = self.port_combo.currentText()
            self.hdr_conn.setText(self._display_text(f"●  {port}  CONNECTED"))
            self.hdr_conn.setStyleSheet(
                f"color:{PH_GREEN}; font-size:11px; font-family:monospace;")
            # Sync coil mask + relay + per-coil config in case it's already running.
            self.worker.send_command("COILS")
            self.worker.send_command("RELAY")
            self.worker.send_command("CINFO")
            # Always fire SQUARE pulses from this UI — every SHOT button uses
            # SQFIRE directly, and this puts the RUN (CRUN) path in square mode
            # too so both single-shot AND repeating use plain 100 % HIGH pulses.
            # SQMODE was previously forced ON here so every SHOT/RUN fired a
            # solid 100% square pulse. That was safe for the metering valve
            # (its own duty clamp handles it) but COOKED the injector MOSFETs
            # on Coil 2 / Coil 3 — real injectors need Peak & Hold. We now
            # let the firmware boot default win (SQMODE=OFF → P&H). If the
            # tech wants a hard square pulse for a diagnostic, they can type
            # `MAXPOWER ON` (or `SQMODE ON`) explicitly.
            # (deliberately do NOT send SQMODE here.)
            # ── Pressure-sensor calibration — two-point live cal ────────
            # Sensor: Denso HP3 rail-pressure, through ~0.298 voltage divider
            # on GPIO14. Bench cal with the tech's calibrated pressure gauge:
            #    52 bar → 343 mV
            #   580 bar → 539 mV     (both from live PADC readings)
            # ⇒ slope = 0.371 mV/bar
            # ⇒ v0    = 0.324 V (0 bar), vmax = 0.917 V (1600 bar)
            # With firmware oversampling×32 + EMA α=0.05 (400ms tau), the
            # LCD reads ±5 bar peak-to-peak — steady enough for real work.
            # If you swap the sensor OR the divider board, redo with `PADC`
            # at two known pressures.
            self.worker.send_command("PSCALE 0.324 0.917 1600")
            # ── Replay the mode-picker choice now that the port is open ──
            # The startup popup fires _on_mode BEFORE we connect, so those
            # MODE/COIL/MV commands are lost. Re-run _on_mode using the
            # currently-checked radio so the board actually lands in the
            # right mode and (for Common Rail) the MV gets auto-primed.
            mid = 1 if self.rb_cam.isChecked() else 0
            logging.info(f"connect: replaying mode picker choice mid={mid}")
            self._on_mode(mid)
            self.worker.send_command("MV")           # request MV snapshot to sync UI
        else:
            self.conn_btn.setText(self._display_text("CONNECT"))
            self.conn_lbl.setText(self._display_text("●  DISCONNECTED"))
            self.conn_lbl.setStyleSheet(
                f"color:{PH_RED}; font-weight:bold; font-size:11px; font-family:monospace;")
            self.hdr_conn.setText(self._display_text("●  DISCONNECTED"))
            self.hdr_conn.setStyleSheet(
                f"color:{PH_RED}; font-size:11px; font-family:monospace;")
            self._p_vx4_ema    = 0.0
            self._p_graph      = 0.0
            self._p_ema_raw    = 0.0
            self._pressure_ema = 0.0
            self._rpm_ema      = 0.0
            self._rpm_win      = deque(maxlen=25)
            self._inj_ema      = 0.0

            self._inj_win      = deque(maxlen=20)
            self._inj_hold     = self._cam_hold = 0

    # ── data parser ───────────────────────────────────────────────────
    def _on_data(self, raw):
        if raw.startswith("COILS:"):          # firmware coil enable mask
            self._apply_coil_mask(raw[6:].strip())
            return
        if raw.startswith("RELAY:"):          # firmware Peak-supply relay state
            self._apply_relay_state(raw[6:])
            return
        if raw.startswith("CINFO:"):          # per-coil freq + run state
            self._apply_coil_info(raw[6:].strip())
            return
        if raw.startswith("CPULSES:"):        # live per-coil pulse counts
            self._apply_coil_pulses(raw[8:].strip())
            return
        if raw.startswith("MV:"):             # metering-valve status snapshot
            self._apply_mv_status(raw[3:].strip())
            return
        if raw.startswith("OK:") or raw.startswith("ERR:") or "P:" not in raw:
            logging.debug(raw)
            return
        self._last_data_time = time.time()   # watchdog timestamp
        if self.graph_paused:
            return
        try:
            p = a = r = i = c = d = 0
            for part in raw.split(','):
                k, _, v = part.partition(':')
                if   k == 'P': p = float(v)
                elif k == 'A': a = int(v)
                elif k == 'R': r = int(v)
                elif k == 'D': d = int(v)
                elif k == 'I': i = int(v)
                elif k == 'C': c = int(v)

            # (PRESSURE DIVISOR is applied at the END of the filter chain —
            #  see just before `self._snap_p = …` below. That way the whole
            #  legacy mV→bar + EMA + slew-limit + offset pipeline stays
            #  untouched; the divisor purely rescales the final display.)

            # ══════════════════════════════════════════════════════════
            #  PRESSURE FILTER  (3-stage, EMI-resistant)
            #
            #  Stage 1 — Buffer:  keep last 20 raw BAR readings
            #  Stage 2 — Trim:    drop 2 highest + 2 lowest (outlier removal)
            #  Stage 3 — EMA:     alpha=0.15 on trimmed mean → smooth & fast
            #  Stage 4 — Offset + dead-band clamp → final display value
            # ══════════════════════════════════════════════════════════

            # Custom mode: ESP32 interrupt detached → force R & C to zero
            if self._mode_id == 0:
                r = 0
                c = 0

            # ── Pressure filter (3 steps, EMI-resistant) ──────────────
            # p = raw VX4 mV from ESP32 (averaged over 256 ADC samples)

            # Step 1a: slow EMA for LCD — warm-start on first reading
            self._p_ema_raw = p
            if self._p_vx4_ema == 0.0:                              # warm-start
                self._p_vx4_ema = p
            else:
                self._p_vx4_ema = P_EMA_ALPHA * p + (1.0 - P_EMA_ALPHA) * self._p_vx4_ema

            # Step 1b: fast EMA for graph (shows dynamics)
            if self._p_graph == 0.0:
                self._p_graph = p
            else:
                self._p_graph = 0.15 * p + 0.85 * self._p_graph

            # Step 2: filtered mV → BAR  (direct slope, 3-point best-fit)
            #   slope = 2.355 BAR/mV  (regression: 0→112, 260→227, 540→339 mV)
            #   zero  = 112 mV
            delta = self._p_vx4_ema - P_VX4_ZERO_MV
            bar   = max(0.0, delta * P_SLOPE_BAR_MV)
            bar   = min(bar, P_BAR_MAX_VAL)

            # Step 3: Slew-Rate Limiter → HEAVY EMA (α=0.05, tau ≈ 200ms)
            # Combined with the α=0.05 EMA at Step 1a and the firmware's own
            # α=0.05 filter, the effective system time constant is ≈ 1 s.
            # LCD looks locked-solid; real changes still show up in ~1 s.
            _prev_bar = getattr(self, '_pressure_ema', None)
            if _prev_bar is None or _prev_bar == 0.0:               # warm-start: snap immediately
                self._pressure_ema = bar
            else:
                _slew_limit        = 40.0                            # BAR per cycle (was 80)
                bar                = max(_prev_bar - _slew_limit,
                                     min(_prev_bar + _slew_limit, bar))
                self._pressure_ema = 0.05 * bar + 0.95 * _prev_bar  # heavy EMA (was 0.20)
            calibrated             = self._pressure_ema + P_CAL_OFFSET
            # ── PRESSURE DIVISOR — rescale filtered bar to real-world bar ──
            # Applied here (after all EMA/slew/offset processing) so the
            # legacy filter chain works exactly as before; we only rescale
            # the number that hits the LCD / MV panel / CSV / PDF.
            if self._pressure_divisor and self._pressure_divisor > 0:
                calibrated = calibrated / self._pressure_divisor
            if self._mode_id == 1:                        # CamBox: sensor not connected
                self._snap_p = 0.0
            else:
                self._snap_p = 0.0 if calibrated < P_DEAD_BAND else calibrated

            # ── RPM median window + spike rejection ──────────────────────
            if self._mode_id == 0:
                self._rpm_win.clear()
                self._rpm_ema = 0.0
            else:
                if r > 0:
                    # Spike reject: ignore jumps > 500 RPM from current value
                    if self._rpm_ema == 0.0 or abs(r - self._rpm_ema) <= 500:
                        self._rpm_win.append(r)
                if self._rpm_win:
                    nz = sorted(self._rpm_win)
                    self._rpm_ema = float(nz[len(nz) // 2])

            self._inj_win.append(i)
            win_sec  = len(self._inj_win) * TELEMETRY_MS / 1000
            self._inj_ema = (sum(self._inj_win) / win_sec) / 2   # ÷2: 2× correction

            _new_r = round(self._rpm_ema / self._rpm_divisor)       # gear correction
            if abs(_new_r - self._snap_r) > 5:                    # dead-band ±5 RPM
                self._snap_r = _new_r
            self._snap_a = a
            self._snap_i = self._inj_ema
            self._snap_d = d

            self.total_pulses += i

            # ── INJ LED flash on every pulse ──────────────────────────
            if i > 0:
                self.inj_led.setStyleSheet(self._led_on_style)
                self._led_timer.start()          # auto-off after 80 ms
                self.inj_rate_lbl.setText(f"{round(self._inj_ema)} inj/s")

            if i > 0: self._inj_hold = 2
            elif self._inj_hold > 0: self._inj_hold -= 1
            if c > 0: self._cam_hold = 2
            elif self._cam_hold > 0: self._cam_hold -= 1

            # Graph uses faster EMA to show dynamics; LCD uses slow EMA
            # Apply same CAL_OFFSET as LCD so graph and display match
            graph_bar = max(0.0, (self._p_graph - P_VX4_ZERO_MV) * P_SLOPE_BAR_MV + P_CAL_OFFSET)
            self.pressure_buf.append(graph_bar)
            self.inj_buf.append(1.0 if (i > 0 or self._inj_hold > 0) else 0.0)
            self.cam_buf.append(1.0 if (c > 0 or self._cam_hold > 0) else 0.0)
            self._graph_dirty = True

            # Track session statistics AFTER computing the new value
            # (only while a session is actually running)
            if self._session_start is not None:
                if self._snap_p > self._max_pressure:
                    self._max_pressure = self._snap_p
                if self._snap_p > 0:
                    if self._min_pressure is None or self._snap_p < self._min_pressure:
                        self._min_pressure = self._snap_p
                    self._sum_pressure += self._snap_p
                    self._cnt_pressure += 1
                if self._snap_r > 0:
                    if self._snap_r > self._max_rpm:
                        self._max_rpm = self._snap_r
                    self._sum_rpm += self._snap_r
                    self._cnt_rpm += 1

        except Exception as e:
            logging.warning(f"Parse [{raw}]: {e}")

    # ── 30fps tick ────────────────────────────────────────────────────
    def _tick(self):
        # LCDs
        self.lcd_p.display(f"{self._snap_p:.0f}")
        self.lcd_r.display(self._snap_r)
        self.lcd_a.display(self._snap_a)
        # lcd_i replaced by LED — rate label updated in _on_data on pulse
        # mirror the pressure into the metering-valve live readout
        if hasattr(self, 'mv_p_lbl'):
            self.mv_p_lbl.setText(f"P: {self._snap_p:.0f} bar")

        # Header pulse counter
        self.hdr_pulses.setText(self._display_text(f"PULSES: {self.total_pulses:,}"))


        # CamBox delay label
        self._update_delay_label()

        # Feature 4 — check alarms every tick
        self._check_alarms()

        # Graph — skip entirely when the WAVEFORM panel is removed (no curves).
        if (self._graph_dirty and not self.graph_paused
                and not self._display_frozen and hasattr(self, 'curve_p')):
            self._graph_dirty = False
            self.curve_p.setData(X_DATA, list(self.pressure_buf))
            self.curve_i.setData(X_STEP, make_step(self.inj_buf))
            self.curve_c.setData(X_STEP, make_step(self.cam_buf))

    # ── close ─────────────────────────────────────────────────────────
    def closeEvent(self, event):
        self._port_timer.stop()
        self._graph_timer.stop()
        self._alarm_timer.stop()
        self._watchdog_timer.stop()
        self._reconnect_timer.stop()
        self.worker._keep_running = False
        self.worker.disconnect_device()
        self.thread.quit()
        self.thread.wait(3000)
        event.accept()


# ══════════════════════════════════════════════════════════════════════
#  SINGLE INSTANCE LOCK
# ══════════════════════════════════════════════════════════════════════
_lock_sock = None

def _acquire_lock():
    global _lock_sock
    try:
        _lock_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _lock_sock.bind(('127.0.0.1', 47832))
        _lock_sock.listen(1)
        return True
    except OSError:
        return False


# ══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = QApplication(sys.argv)
    if not _acquire_lock():
        QMessageBox.warning(None, "Already Running",
                            "INJECTOR PRO is already running!")
        sys.exit(0)

    pg.setConfigOptions(antialias=True, foreground=TXT_SEC)
    app.setStyle("Fusion")

    # ── Dark system palette — Fusion never falls back to light colors ──
    _dp = QPalette()
    _dp.setColor(QPalette.ColorRole.Window,          QColor(BG))
    _dp.setColor(QPalette.ColorRole.WindowText,       QColor(TXT_PRI))
    _dp.setColor(QPalette.ColorRole.Base,             QColor(PANEL))
    _dp.setColor(QPalette.ColorRole.AlternateBase,    QColor(BORDER))
    _dp.setColor(QPalette.ColorRole.ToolTipBase,      QColor(PANEL))
    _dp.setColor(QPalette.ColorRole.ToolTipText,      QColor(TXT_PRI))
    _dp.setColor(QPalette.ColorRole.Text,             QColor(TXT_PRI))
    _dp.setColor(QPalette.ColorRole.Button,           QColor(BORDER))
    _dp.setColor(QPalette.ColorRole.ButtonText,       QColor(TXT_PRI))
    _dp.setColor(QPalette.ColorRole.BrightText,       QColor(PH_RED))
    _dp.setColor(QPalette.ColorRole.Link,             QColor(PH_BLUE))
    _dp.setColor(QPalette.ColorRole.Highlight,        QColor(PH_BLUE))
    _dp.setColor(QPalette.ColorRole.HighlightedText,  QColor('#FFFFFF'))
    _dp.setColor(QPalette.ColorGroup.Disabled,
                 QPalette.ColorRole.WindowText,        QColor(TXT_DIM))
    _dp.setColor(QPalette.ColorGroup.Disabled,
                 QPalette.ColorRole.Text,              QColor(TXT_DIM))
    _dp.setColor(QPalette.ColorGroup.Disabled,
                 QPalette.ColorRole.ButtonText,        QColor(TXT_DIM))
    app.setPalette(_dp)

    # ── STARTUP MODE PICKER ────────────────────────────────────────────
    #   Ask which system the user is running before the main window shows.
    #   Result is stored in the dashboard and used to pre-select the mode.
    from PyQt6.QtWidgets import (QDialog, QLabel, QVBoxLayout, QHBoxLayout,
                                  QPushButton, QWidget)
    from PyQt6.QtCore import Qt as _Qt

    class _ModePicker(QDialog):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("INJECTOR PRO")
            self.setModal(True)
            screen = QApplication.primaryScreen()
            available = screen.availableGeometry() if screen else None
            screen_width = available.width() if available else 620
            screen_height = available.height() if available else 360
            self.setFixedSize(
                min(620, max(480, screen_width - 40)),
                min(360, max(300, screen_height - 40)))
            self.setWindowFlag(_Qt.WindowType.FramelessWindowHint)
            self.choice = None

            outer = QVBoxLayout(self)
            outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)

            # ── header strip ───────────────────────────────────────────
            header = QWidget(); header.setFixedHeight(76)
            header.setStyleSheet(
                f"background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                f"stop:0 #071427, stop:1 #0E1F3E);"
                f"border-bottom:1px solid {PH_BLUE}55;")
            hv = QVBoxLayout(header); hv.setContentsMargins(28, 14, 28, 12); hv.setSpacing(2)
            brand = QLabel("INJECTOR  PRO")
            brand.setStyleSheet(f"color:{PH_GREEN};font-size:20px;font-weight:800;"
                                "letter-spacing:6px;border:none;background:transparent;")
            sub = QLabel("SELECT OPERATING SYSTEM")
            sub.setStyleSheet(f"color:{TXT_DIM};font-size:10px;font-weight:600;"
                              "letter-spacing:3px;border:none;background:transparent;")
            hv.addWidget(brand); hv.addWidget(sub)
            outer.addWidget(header)

            # ── body: two big option cards ─────────────────────────────
            body = QWidget()
            body.setStyleSheet(f"background:{BG};")
            v = QVBoxLayout(body); v.setContentsMargins(24, 22, 24, 20); v.setSpacing(14)

            row = QHBoxLayout(); row.setSpacing(16); v.addLayout(row, stretch=1)

            def option(title, subtitle, meta, colour, on_click):
                b = QPushButton()
                b.setCursor(_Qt.CursorShape.PointingHandCursor)
                b.setMinimumHeight(130)
                # title / subtitle / meta stacked inside the button
                inner = QVBoxLayout(b)
                inner.setContentsMargins(18, 18, 18, 18); inner.setSpacing(6)
                inner.setAlignment(_Qt.AlignmentFlag.AlignCenter)

                t = QLabel(title)
                t.setAlignment(_Qt.AlignmentFlag.AlignCenter)
                t.setStyleSheet(f"color:{colour};font-size:22px;font-weight:800;"
                                "letter-spacing:3px;border:none;background:transparent;")
                s = QLabel(subtitle)
                s.setAlignment(_Qt.AlignmentFlag.AlignCenter)
                s.setStyleSheet(f"color:{TXT_PRI};font-size:11px;font-weight:600;"
                                "letter-spacing:1px;border:none;background:transparent;")
                m = QLabel(meta)
                m.setAlignment(_Qt.AlignmentFlag.AlignCenter)
                m.setStyleSheet(f"color:{TXT_DIM};font-size:9px;font-family:monospace;"
                                "letter-spacing:2px;border:none;background:transparent;")
                inner.addStretch()
                inner.addWidget(t); inner.addSpacing(4)
                inner.addWidget(s); inner.addWidget(m)
                inner.addStretch()

                b.setStyleSheet(f"""
                    QPushButton {{background:#0A1424;
                                  border:1px solid {colour}55;border-radius:12px;}}
                    QPushButton:hover {{background:#132244;border:1px solid {colour};}}
                    QPushButton:pressed {{background:#050C18;}}
                """)
                b.clicked.connect(on_click)
                return b

            row.addWidget(option("CAMBOX",  "Cam-Synchronised Injection",
                                 "EUI  ·  GPIO 23", PH_PURPLE,
                                 lambda: self._pick("cambox")))
            row.addWidget(option("COMMON RAIL", "PID Pressure Control",
                                 "SCV  ·  GPIO 18", PH_BLUE,
                                 lambda: self._pick("common_rail")))

            # ── footer: exit button ────────────────────────────────────
            foot = QHBoxLayout(); foot.setSpacing(0)
            foot.addStretch()
            exit_btn = QPushButton("EXIT")
            exit_btn.setCursor(_Qt.CursorShape.PointingHandCursor)
            exit_btn.setFixedHeight(28)
            exit_btn.setStyleSheet(f"""
                QPushButton {{background:transparent;color:{TXT_DIM};
                              border:1px solid {BORDER2};border-radius:6px;
                              padding:2px 22px;font-size:10px;letter-spacing:3px;
                              font-weight:600;}}
                QPushButton:hover {{color:{PH_RED};border-color:{PH_RED};}}
            """)
            exit_btn.clicked.connect(self.reject)
            foot.addWidget(exit_btn)
            v.addLayout(foot)

            outer.addWidget(body, stretch=1)
            self.setStyleSheet(f"QDialog {{background:{BG};border:1px solid {BORDER2};}}")

        def _pick(self, choice):
            self.choice = choice
            self.accept()

    _picker = _ModePicker()
    if _picker.exec() != QDialog.DialogCode.Accepted or _picker.choice is None:
        sys.exit(0)

    win = DieselDashboard()
    # Apply the picked mode as soon as the window is up — flip the radio group
    # to the picked side and let _on_mode do the rest (mode send + coil setup).
    if _picker.choice == "cambox":
        win.rb_cam.setChecked(True)
    else:
        win.rb_custom.setChecked(True)

    win.showMaximized()
    sys.exit(app.exec())