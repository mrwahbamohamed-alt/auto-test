import sys
import time
import logging
import socket
import datetime
from collections import deque

from PyQt6.QtCore import QObject, pyqtSignal, QThread, Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QGroupBox, QLabel, QComboBox, QPushButton, QSlider,
    QSpinBox, QRadioButton, QButtonGroup, QLCDNumber, QMessageBox, QFrame,
    QFileDialog, QScrollArea
)
from PyQt6.QtGui import QFont, QColor, QPainter, QPixmap, QPalette

import serial
import serial.tools.list_ports
import pyqtgraph as pg

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

# ── constants ─────────────────────────────────────────────────────────
N_SAMPLES    = 300
TELEMETRY_MS = 10
GRAPH_FPS    = 30

# ══════════════════════════════════════════════════════════════════════
#  PRESSURE SENSOR CALIBRATION  ←  عدّل القيم دي بس
#  الحساس: VP=1.0V عند 0 BAR  |  VP=4.5V عند 1600 BAR
#  Voltage divider ×0.3: VX4 = VP × 0.3
#
# ── CASE A: RAW P ≈ 0.30  → ESP32 بيبعت Voltage (VX4) ◄ شغّال دلوقتي
P_CAL_RAW_ZERO = 0.300   # VX4 عند 0 BAR
P_CAL_RAW_MAX  = 1.340   # VX4 عند 1600 BAR
#
# ── CASE B: RAW P ≈ 370   → ESP32 بيبعت Raw ADC (3.3V ref) ─────────
# P_CAL_RAW_ZERO = 373
# P_CAL_RAW_MAX  = 1664
#
# ── CASE C: RAW P ≈ 245   → ESP32 بيبعت Raw ADC (5V ref) ──────────
# P_CAL_RAW_ZERO = 246
# P_CAL_RAW_MAX  = 1098
#
# ── CASE D: RAW P ≈ 1.0   → ESP32 بيبعت VP مباشرة ─────────────────
# P_CAL_RAW_ZERO = 1.000
# P_CAL_RAW_MAX  = 4.500
#
P_CAL_P_MAX    = 1600.0
P_CAL_OFFSET   = 0.0
# ══════════════════════════════════════════════════════════════════════

# ── Safety alarm thresholds ───────────────────────────────────────────
PRESSURE_WARN  = 1400.0   # BAR  — amber warning
PRESSURE_ALARM = 1600.0   # BAR  — red alarm
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


# ══════════════════════════════════════════════════════════════════════
#  SERIAL WORKER
# ══════════════════════════════════════════════════════════════════════
class SerialWorker(QObject):
    data_received     = pyqtSignal(str)
    error_occurred    = pyqtSignal(str)
    connection_status = pyqtSignal(bool)
    _cmd              = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.port          = None
        self.is_running    = False
        self._keep_running = True
        self._cmd.connect(self._write)

    def connect_device(self, port, baud):
        try:
            self.port       = serial.Serial(port, baud, timeout=0.1)
            self.is_running = True
            self.connection_status.emit(True)
        except Exception as e:
            self.error_occurred.emit(str(e))
            self.connection_status.emit(False)

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
                        else:
                            self.data_received.emit(raw)
                    if latest:
                        self.data_received.emit(latest)
                except Exception as e:
                    self.error_occurred.emit(f"Lost: {e}")
                    self.disconnect_device()
            time.sleep(0.010)

    def send_command(self, cmd):
        self._cmd.emit(cmd)

    def _write(self, cmd):
        if self.port and self.port.is_open:
            try:
                self.port.write(f"{cmd}\n".encode())
                logging.info(f"TX: {cmd}")
            except Exception as e:
                self.error_occurred.emit(f"Write: {e}")


# ══════════════════════════════════════════════════════════════════════
#  MAIN WINDOW
# ══════════════════════════════════════════════════════════════════════
class DieselDashboard(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("AUTO PRO TEST  ·  Diesel Injection Test System")
        self.resize(1400, 860)
        self.setStyleSheet(STYLE_DARK)

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

        # ── EMA ───────────────────────────────────────────────────────
        self._p_ema     = 0.0
        self._p_ema_raw = 0.0
        self._rpm_ema = 0.0
        self._inj_ema = 0.0

        # ── pulse hold ────────────────────────────────────────────────
        self._inj_hold = 0
        self._cam_hold = 0

        # ── LCD snapshot (updated at 30fps) ───────────────────────────
        self._snap_p = 0.0
        self._snap_r = 0
        self._snap_a = 0
        self._snap_i = 0.0

        # ── Feature 4: alarm state ────────────────────────────────────
        self._blink_state  = False
        self._p_alarm      = False
        self._r_alarm      = False
        self._alarm_timer  = QTimer()
        self._alarm_timer.timeout.connect(self._blink_tick)
        self._alarm_timer.start(420)

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
        self.thread.start()

        self._build_ui()
        self._apply_theme_widgets()          # sync all inline styles with startup mode
        QApplication.processEvents()         # force Qt to repaint with new styles

        self._port_timer = QTimer()
        self._port_timer.timeout.connect(self._refresh_ports)
        self._port_timer.start(2000)
        self._refresh_ports()

        self._graph_timer = QTimer()
        self._graph_timer.timeout.connect(self._tick)
        self._graph_timer.start(1000 // GRAPH_FPS)

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

        body.addWidget(self._make_left(),  stretch=0)
        body.addWidget(self._make_right(), stretch=1)

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

        logo = QLabel("  AUTO PRO TEST")
        logo.setStyleSheet(
            f"color:{PH_GREEN}; font-size:15px; font-weight:bold;"
            f" font-family:monospace; letter-spacing:2px;")

        self.hdr_mode = QLabel("  CUSTOM MODE")
        self.hdr_mode.setStyleSheet(
            f"color:{PH_BLUE}; font-size:11px; font-family:monospace; letter-spacing:1px;")

        self.hdr_conn = QLabel("o  DISCONNECTED")
        self.hdr_conn.setStyleSheet(
            f"color:{PH_RED}; font-size:11px; font-family:monospace; letter-spacing:1px;")

        self.hdr_pulses = QLabel("PULSES: 0")
        self.hdr_pulses.setStyleSheet(
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

        h.addWidget(logo)
        h.addSpacing(30)
        h.addWidget(self.hdr_mode)
        h.addStretch()
        h.addWidget(self.hdr_pulses)
        h.addSpacing(20)
        h.addWidget(self._vsep())
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
        v.addWidget(self._panel_mode())
        v.addWidget(self._panel_params())
        v.addWidget(self._panel_actions())
        v.addStretch()

        # wrap in a scroll area so nothing ever hides under the taskbar
        scroll = QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(286)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        return scroll

    # ──────────────────────────────────────────────────────────────────
    #  RIGHT DISPLAY PANEL
    # ──────────────────────────────────────────────────────────────────
    def _make_right(self):
        w = QWidget()
        v = QVBoxLayout(w); v.setSpacing(10); v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self._panel_meters())
        v.addWidget(self._panel_scope(), stretch=1)
        return w

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

        self.conn_lbl = QLabel("  DISCONNECTED")
        self.conn_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.conn_lbl.setStyleSheet(
            f"color:{PH_RED}; font-weight:bold; font-size:11px; font-family:monospace;")
        g.addWidget(self.conn_lbl, 3, 0, 1, 2)
        return box

    # ── Feature 1: Test Plan Presets ──────────────────────────────────
    def _panel_presets(self):
        box = QGroupBox("TEST PLANS  —  COMMON RAIL  SOLENOID")
        g   = QGridLayout(box); g.setSpacing(6)

        g.addWidget(self._dim("PRESET"), 0, 0)

        self.preset_combo = QComboBox()
        self.preset_combo.addItems(PRESETS.keys())
        self.preset_combo.setToolTip(
            "Auto-fills Pulse Width and Delay Angle.\n"
            "You can still manually edit values after selection.")
        self.preset_combo.currentTextChanged.connect(self._apply_preset)
        g.addWidget(self.preset_combo, 0, 1)

        self._preset_info = QLabel("—")
        self._preset_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preset_info.setStyleSheet(
            f"color:{PH_AMBER}; font-size:10px; font-family:monospace; padding:1px 0;")
        g.addWidget(self._preset_info, 1, 0, 1, 2)
        return box

    # ── mode ──────────────────────────────────────────────────────────
    def _panel_mode(self):
        box = QGroupBox("INJECTION MODE")
        h   = QHBoxLayout(box); h.setSpacing(0)

        self.mode_grp  = QButtonGroup(self)
        self.rb_custom = QRadioButton("Custom  (Hz)")
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

        self.pw_lbl, self.pw_sp, self.pw_sl = row("PULSE WIDTH (µs)", 200, 3000, 1000, 50)
        self.fr_lbl, self.fr_sp, self.fr_sl = row("FREQUENCY (Hz)",     1,  100,   25)
        self.an_lbl, self.an_sp, self.an_sl = row("DELAY ANGLE (°)",    0,   45,    0)

        self.pw_sp.valueChanged.connect(lambda v: self.worker.send_command(f"w{v}"))
        self.fr_sp.valueChanged.connect(lambda v: self.worker.send_command(f"f{v}"))
        self.an_sp.valueChanged.connect(lambda v: self.worker.send_command(f"a{v}"))

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

        self._cam_visible(False)
        return box

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

        self.sync_btn = QPushButton("~   dync auto test")
        self.sync_btn.setMinimumHeight(30)
        self.sync_btn.setStyleSheet(f"""
            QPushButton       {{background:#081428;color:{PH_BLUE};
                                border:1px solid #102248;border-radius:7px;font-size:11px;font-weight:500;}}
            QPushButton:hover {{background:#102248;color:{TXT_PRI};border-color:{PH_BLUE};}}
            QPushButton:pressed {{background:#050C18;color:{TXT_PRI};}}
        """)
        self.sync_btn.clicked.connect(self._sync)

        # Feature 2 — Save PDF Report
        self.report_btn = QPushButton("  SAVE REPORT")
        self.report_btn.setMinimumHeight(30)
        self.report_btn.setStyleSheet(f"""
            QPushButton       {{background:#081A12;color:{PH_GREEN};
                                border:1px solid #102C1E;border-radius:7px;font-size:11px;font-weight:500;}}
            QPushButton:hover {{background:#102C1E;color:{TXT_PRI};border-color:{PH_GREEN};}}
            QPushButton:pressed {{background:#040D09;color:{TXT_PRI};}}
        """)
        self.report_btn.clicked.connect(self._save_pdf)

        g.addWidget(self.start_btn,  0, 0)
        g.addWidget(self.stop_btn,   0, 1)
        g.addWidget(self.sync_btn,   1, 0, 1, 2)
        g.addWidget(self.report_btn, 2, 0, 1, 2)
        return box

    # ── meters panel (Hartridge-style large displays) ─────────────────
    def _panel_meters(self):
        box = QGroupBox("MEASUREMENTS")
        h   = QHBoxLayout(box); h.setSpacing(2)

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
            lcd.setMinimumHeight(70)
            lcd.setSegmentStyle(QLCDNumber.SegmentStyle.Flat)
            lcd.setStyleSheet(
                f"QLCDNumber{{color:{color}; background:{G_BG};"
                f" border:1px solid {color}28; border-radius:4px;}}")

            unit_lbl = QLabel(unit)
            unit_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            unit_color = f"{color}60" if dk else f"{color}CC"
            unit_lbl.setStyleSheet(
                f"color:{unit_color}; font-size:10px; font-family:monospace; border:none;")

            v.addWidget(lbl)
            v.addWidget(lcd)
            v.addWidget(unit_lbl)
            return frame, lcd

        # Store frame refs for Feature 4 alarm blinking
        self.frame_r, self.lcd_r = meter("RPM",      PH_PURPLE, 5, "rev/min")
        self.frame_p, self.lcd_p = meter("PRESSURE", PH_AMBER,  7, "BAR")
        f2,           self.lcd_i = meter("INJ RATE", PH_GREEN,  4, "inj/s")
        f3,           self.lcd_a = meter("ANGLE",    PH_BLUE,   3, "deg")

        # Engine status
        status_box = QWidget()
        status_box.setStyleSheet(
            f"background:{PANEL}; border:1px solid {BORDER2}; border-radius:6px;")
        sv = QVBoxLayout(status_box); sv.setContentsMargins(10, 8, 10, 8); sv.setSpacing(6)

        sl = QLabel("ENGINE")
        sl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sl.setStyleSheet(
            f"color:{TXT_DIM}; font-size:9px; font-weight:bold;"
            f" letter-spacing:2px; font-family:monospace; border:none;")

        self.run_lbl = QLabel("STOPPED")
        self.run_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.run_lbl.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        self.run_lbl.setStyleSheet(
            f"color:{PH_RED}; font-family:monospace; border:none;")

        self.mode_lbl = QLabel("CUSTOM")
        self.mode_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mode_lbl.setStyleSheet(
            f"color:{PH_BLUE}; font-size:11px; font-family:monospace;"
            f" letter-spacing:1px; border:none;")

        sv.addWidget(sl)
        sv.addStretch()
        sv.addWidget(self.run_lbl)
        sv.addWidget(self.mode_lbl)
        sv.addStretch()

        for f in [self.frame_r, self.frame_p, f2, f3, status_box]:
            h.addWidget(f, stretch=1)

        return box

    # ── oscilloscope / waveform ───────────────────────────────────────
    def _panel_scope(self):
        box = QGroupBox("WAVEFORM  OSCILLOSCOPE")
        lay = QVBoxLayout(box); lay.setContentsMargins(4, 20, 4, 4)

        # Feature 3 — Freeze/Pause row above the graph
        ctrl_row = QHBoxLayout()
        ctrl_row.setContentsMargins(4, 0, 4, 4)

        self.freeze_btn = QPushButton("  FREEZE")
        self.freeze_btn.setFixedHeight(26)
        self.freeze_btn.setCheckable(True)
        self.freeze_btn.setStyleSheet(f"""
            QPushButton         {{background:{BORDER};color:{PH_BLUE};
                                  border:1px solid {BORDER2};border-radius:6px;
                                  font-size:10px;padding:0 12px;font-weight:500;}}
            QPushButton:hover   {{background:{BORDER2};color:{TXT_PRI};border-color:{PH_BLUE};}}
            QPushButton:checked {{background:#241E08;color:{PH_AMBER};
                                  border-color:{PH_AMBER};}}
            QPushButton:checked:hover {{background:#352C0C;border-color:{PH_AMBER};}}
        """)
        self.freeze_btn.toggled.connect(self._toggle_freeze)

        self._freeze_status = QLabel("  LIVE")
        self._freeze_status.setStyleSheet(
            f"color:{PH_GREEN}; font-size:10px; font-family:monospace;")

        ctrl_row.addWidget(self.freeze_btn)
        ctrl_row.addSpacing(8)
        ctrl_row.addWidget(self._freeze_status)
        ctrl_row.addStretch()
        lay.addLayout(ctrl_row)

        self.glw = pg.GraphicsLayoutWidget()
        self.glw.setBackground(G_BG)
        self.glw.setStyleSheet(
            f"border:1px solid {BORDER}; border-radius:6px; background:{G_BG};")

        def scope_plot(row, color, label, is_digital=False):
            p = self.glw.addPlot(row=row, col=0)
            p.setLabel('left', label, color=color, **{'font-size': '9pt'})
            p.getAxis('left').setTextPen(pg.mkPen(color=TXT_DIM))
            p.getAxis('left').setWidth(54)
            # Axis lines match BORDER — very subtle, not black
            p.getAxis('left').setPen(pg.mkPen(color=BORDER, width=1))
            p.getAxis('bottom').setPen(pg.mkPen(color=BORDER, width=1))
            p.getAxis('bottom').setTextPen(pg.mkPen(color=TXT_DIM))
            if is_digital:
                p.getAxis('left').setTicks([[(0, '0'), (1, '1')]])
                p.setYRange(-0.07, 1.3)
            # Grid: color matches BORDER for faint, clean grid lines
            p.showGrid(x=True, y=True, alpha=0.18)
            p.setMouseEnabled(x=True, y=(not is_digital))
            p.getViewBox().setBackgroundColor(G_BG)
            return p

        self.plt_p = scope_plot(0, G_AMBER, 'BAR')
        self.plt_p.hideAxis('bottom')
        self.curve_p = self.plt_p.plot(
            X_DATA, list(self.pressure_buf),
            pen=pg.mkPen(G_AMBER, width=2))

        self.plt_i = scope_plot(1, G_GREEN, 'INJ', is_digital=True)
        self.plt_i.hideAxis('bottom')
        self.plt_i.setXLink(self.plt_p)
        self.curve_i = pg.PlotCurveItem(
            X_STEP, [0.0] * (N_SAMPLES * 2),
            pen=pg.mkPen(G_GREEN, width=2),
            fillLevel=0.0,
            brush=pg.mkBrush(48, 209, 88, 28))
        self.plt_i.addItem(self.curve_i)

        self.plt_c = scope_plot(2, G_BLUE, 'CAM', is_digital=True)
        self.plt_c.getAxis('bottom').setTextPen(TXT_DIM)
        self.plt_c.setLabel(
            'bottom',
            f'{TELEMETRY_MS} ms / sample  ·  {N_SAMPLES * TELEMETRY_MS // 1000} s window',
            color=TXT_DIM, **{'font-size': '8pt'})
        self.plt_c.setXLink(self.plt_p)
        self.curve_c = pg.PlotCurveItem(
            X_STEP, [0.0] * (N_SAMPLES * 2),
            pen=pg.mkPen(G_BLUE, width=2),
            fillLevel=0.0,
            brush=pg.mkBrush(48, 176, 199, 26))
        self.plt_c.addItem(self.curve_c)

        self.glw.ci.layout.setRowStretchFactor(0, 3)
        self.glw.ci.layout.setRowStretchFactor(1, 2)
        self.glw.ci.layout.setRowStretchFactor(2, 2)
        self.glw.ci.layout.setSpacing(1)

        lay.addWidget(self.glw)
        return box

    # ── helpers ───────────────────────────────────────────────────────
    @staticmethod
    def _volt_to_bar(raw, zero, maxv, pmax):
        span = maxv - zero
        if span == 0: return 0.0
        return max(0.0, (raw - zero) / span * pmax)

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
    #  FEATURE 1 — Apply Preset
    # ──────────────────────────────────────────────────────────────────
    def _apply_preset(self, name: str):
        params = PRESETS.get(name)
        if params is None:
            self._preset_info.setText("—")
            return
        pw, freq, angle = params
        # Block signals so auto-send to ESP32 doesn't fire during fill
        self.pw_sp.blockSignals(True)
        self.fr_sp.blockSignals(True)
        self.an_sp.blockSignals(True)
        self.pw_sp.setValue(pw)
        self.fr_sp.setValue(freq)
        self.an_sp.setValue(angle)
        self.pw_sp.blockSignals(False)
        self.fr_sp.blockSignals(False)
        self.an_sp.blockSignals(False)
        # Update sliders (they have their own connection)
        self.pw_sl.setValue(pw)
        self.fr_sl.setValue(freq)
        self.an_sl.setValue(angle)
        self._preset_info.setText(f"PW {pw} µs  |  Freq {freq} Hz  |  Angle {angle}°")

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

        page  = printer.pageRect(QPrinter.Unit.DevicePixel)
        W     = page.width()
        H     = page.height()
        margin = W * 0.06

        # ── header bar ────────────────────────────────────────────────
        painter.fillRect(int(0), int(0), int(W), int(H * 0.07),
                         QColor(HEADER))
        painter.setPen(QColor(PH_GREEN))
        f = QFont("Arial", int(W * 0.022), QFont.Weight.Bold)
        painter.setFont(f)
        painter.drawText(int(margin), int(H * 0.048),
                         "AUTO PRO TEST  —  Diesel Injection Test Report")

        painter.setPen(QColor(TXT_SEC))
        painter.setFont(QFont("Arial", int(W * 0.011)))
        now_str = datetime.datetime.now().strftime("%A, %d %B %Y  %H:%M:%S")
        painter.drawText(int(W - margin - W * 0.25), int(H * 0.048), now_str)

        # ── divider ───────────────────────────────────────────────────
        painter.setPen(QColor(BORDER2))
        y_div = int(H * 0.08)
        painter.drawLine(int(margin), y_div, int(W - margin), y_div)

        # ── two-column info ───────────────────────────────────────────
        col1_x = int(margin)
        col2_x = int(W * 0.52)
        row_h  = int(H * 0.033)
        y0     = int(H * 0.095)

        def draw_kv(x, y, key, val, key_color=TXT_DIM, val_color=TXT_PRI):
            painter.setFont(QFont("Courier New", int(W * 0.010), QFont.Weight.Bold))
            painter.setPen(QColor(key_color))
            painter.drawText(x, y, key)
            painter.setFont(QFont("Courier New", int(W * 0.013)))
            painter.setPen(QColor(val_color))
            painter.drawText(x + int(W * 0.14), y, val)

        preset_name = self.preset_combo.currentText()
        mode_name   = "CamBox (Sync)" if self._mode_id == 1 else "Custom (Hz)"
        status_name = "RUNNING" if not self.graph_paused else "STOPPED"

        # Left column — parameters
        painter.setFont(QFont("Arial", int(W * 0.012), QFont.Weight.Bold))
        painter.setPen(QColor(PH_BLUE))
        painter.drawText(col1_x, y0, "INJECTION PARAMETERS")
        draw_kv(col1_x, y0 + row_h * 1, "PRESET",     preset_name)
        draw_kv(col1_x, y0 + row_h * 2, "MODE",       mode_name)
        draw_kv(col1_x, y0 + row_h * 3, "PULSE WIDTH", f"{self.pw_sp.value()} µs")
        draw_kv(col1_x, y0 + row_h * 4, "FREQUENCY",  f"{self.fr_sp.value()} Hz")
        draw_kv(col1_x, y0 + row_h * 5, "DELAY ANGLE", f"{self.an_sp.value()} °")
        draw_kv(col1_x, y0 + row_h * 6, "STATUS",     status_name,
                val_color=PH_GREEN if status_name == "RUNNING" else PH_RED)

        # Right column — live readings
        painter.setFont(QFont("Arial", int(W * 0.012), QFont.Weight.Bold))
        painter.setPen(QColor(PH_AMBER))
        painter.drawText(col2_x, y0, "LIVE READINGS")
        draw_kv(col2_x, y0 + row_h * 1, "PRESSURE",   f"{self._snap_p:.1f} BAR",   val_color=PH_AMBER)
        draw_kv(col2_x, y0 + row_h * 2, "RPM",        f"{self._snap_r}",            val_color=PH_PURPLE)
        draw_kv(col2_x, y0 + row_h * 3, "INJ RATE",   f"{round(self._snap_i)} inj/s", val_color=PH_GREEN)
        draw_kv(col2_x, y0 + row_h * 4, "ANGLE",      f"{self._snap_a} °",          val_color=PH_BLUE)
        draw_kv(col2_x, y0 + row_h * 5, "TOTAL PULSES", f"{self.total_pulses:,}")
        port_txt = self.port_combo.currentText() or "—"
        draw_kv(col2_x, y0 + row_h * 6, "COM PORT",   port_txt)

        # ── divider ───────────────────────────────────────────────────
        y_div2 = y0 + row_h * 7 + int(H * 0.01)
        painter.setPen(QColor(BORDER2))
        painter.drawLine(int(margin), y_div2, int(W - margin), y_div2)

        # ── oscilloscope snapshot ─────────────────────────────────────
        painter.setFont(QFont("Arial", int(W * 0.011), QFont.Weight.Bold))
        painter.setPen(QColor(TXT_DIM))
        painter.drawText(int(margin), y_div2 + int(H * 0.025), "WAVEFORM OSCILLOSCOPE SNAPSHOT")

        scope_pixmap = self.glw.grab()
        scope_y  = y_div2 + int(H * 0.035)
        scope_h  = int(H * 0.38)
        scope_w  = int(W - margin * 2)
        scaled   = scope_pixmap.scaled(
            scope_w, scope_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        painter.drawPixmap(int(margin), scope_y, scaled)

        # ── footer ────────────────────────────────────────────────────
        painter.setPen(QColor(TXT_DIM))
        painter.setFont(QFont("Arial", int(W * 0.009)))
        painter.drawText(int(margin), int(H * 0.97),
                         "AUTO PRO TEST  ·  Diesel Injection Test System")
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
            self._freeze_status.setText("  FROZEN")
            self._freeze_status.setStyleSheet(
                f"color:{PH_AMBER}; font-size:10px; font-family:monospace;")
        else:
            self._freeze_status.setText("  LIVE")
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
        self.theme_btn.setText("LIGHT MODE" if dk else "DARK MODE")

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
        self.theme_btn.setText("LIGHT MODE" if dk else "DARK MODE")

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

        # ── FREEZE button ─────────────────────────────────────────────
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
        self.glw.setBackground(graph_bg)
        for _plt in [self.plt_p, self.plt_i, self.plt_c]:
            _plt.getViewBox().setBackgroundColor(graph_bg)
            _plt.getAxis('left').setPen(pg.mkPen(color=axis_clr, width=1))
            _plt.getAxis('bottom').setPen(pg.mkPen(color=axis_clr, width=1))
            _plt.getAxis('left').setTextPen(pg.mkPen(color=axis_txt))
            _plt.getAxis('bottom').setTextPen(pg.mkPen(color=axis_txt))
            _plt.showGrid(x=True, y=True, alpha=grid_alpha)

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

        # re-apply meter frame backgrounds
        for frame in [self.frame_r, self.frame_p]:
            frame.setStyleSheet(frame_ss)

    # ── actions ───────────────────────────────────────────────────────
    def _on_start(self):
        self.worker.send_command("start")
        self.graph_paused = False
        self.run_lbl.setText("RUNNING")
        self.run_lbl.setStyleSheet(
            f"color:{PH_GREEN}; font-family:monospace; border:none;")

    def _on_stop(self):
        self.worker.send_command("stop")
        self.graph_paused = True
        self.run_lbl.setText("STOPPED")
        self.run_lbl.setStyleSheet(
            f"color:{PH_RED}; font-family:monospace; border:none;")

    def _on_mode(self, mid):
        self.worker.send_command("mode")
        self._mode_id = mid
        self._cam_visible(mid == 1)
        if mid == 0:
            self.mode_lbl.setText("CUSTOM")
            self.mode_lbl.setStyleSheet(
                f"color:{PH_BLUE}; font-size:11px; font-family:monospace;"
                f" letter-spacing:1px; border:none;")
            self.hdr_mode.setText("  CUSTOM MODE")
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

    def _sync(self):
        self.worker.send_command(f"w{self.pw_sp.value()}")
        self.worker.send_command(f"f{self.fr_sp.value()}")
        self.worker.send_command(f"a{self.an_sp.value()}")

    def _on_conn(self, ok):
        self._style_conn_btn(ok)
        if ok:
            self.conn_btn.setText("DISCONNECT")
            self.conn_lbl.setText("  CONNECTED")
            self.conn_lbl.setStyleSheet(
                f"color:{PH_GREEN}; font-weight:bold; font-size:11px; font-family:monospace;")
            port = self.port_combo.currentText()
            self.hdr_conn.setText(f"  {port}  CONNECTED")
            self.hdr_conn.setStyleSheet(
                f"color:{PH_GREEN}; font-size:11px; font-family:monospace;")
        else:
            self.conn_btn.setText("CONNECT")
            self.conn_lbl.setText("o  DISCONNECTED")
            self.conn_lbl.setStyleSheet(
                f"color:{PH_RED}; font-weight:bold; font-size:11px; font-family:monospace;")
            self.hdr_conn.setText("o  DISCONNECTED")
            self.hdr_conn.setStyleSheet(
                f"color:{PH_RED}; font-size:11px; font-family:monospace;")
            self._p_ema = self._rpm_ema = self._inj_ema = 0.0
            self._inj_hold = self._cam_hold = 0

    # ── data parser ───────────────────────────────────────────────────
    def _on_data(self, raw):
        if raw.startswith("OK:") or raw.startswith("ERR:") or "P:" not in raw:
            logging.debug(raw)
            return
        if self.graph_paused:
            return
        try:
            p = a = r = i = c = 0
            for part in raw.split(','):
                k, _, v = part.partition(':')
                if   k == 'P': p = float(v)
                elif k == 'A': a = int(v)
                elif k == 'R': r = int(v)
                elif k == 'I': i = int(v)
                elif k == 'C': c = int(v)

            self._p_ema_raw = 0.15 * p + 0.85 * self._p_ema_raw
            self._p_ema = (
                self._volt_to_bar(self._p_ema_raw,
                                  P_CAL_RAW_ZERO, P_CAL_RAW_MAX, P_CAL_P_MAX)
                + P_CAL_OFFSET
            )

            # ── RPM EMA — stable, non-zero–dragged ────────────────────
            if r > 0:
                self._rpm_ema = 0.15 * r + 0.85 * self._rpm_ema
            else:
                self._rpm_ema *= 0.994

            if self._rpm_ema < 5:
                self._rpm_ema = 0.0

            raw_rate      = i * (1000 / TELEMETRY_MS)
            self._inj_ema = 0.10 * raw_rate + 0.90 * self._inj_ema

            self._snap_p = self._p_ema
            self._snap_r = int(self._rpm_ema)
            self._snap_a = a
            self._snap_i = self._inj_ema

            self.total_pulses += i

            if i > 0: self._inj_hold = 2
            elif self._inj_hold > 0: self._inj_hold -= 1
            if c > 0: self._cam_hold = 2
            elif self._cam_hold > 0: self._cam_hold -= 1

            self.pressure_buf.append(self._p_ema)
            self.inj_buf.append(1.0 if (i > 0 or self._inj_hold > 0) else 0.0)
            self.cam_buf.append(1.0 if (c > 0 or self._cam_hold > 0) else 0.0)
            self._graph_dirty = True

        except Exception as e:
            logging.warning(f"Parse [{raw}]: {e}")

    # ── 30fps tick ────────────────────────────────────────────────────
    def _tick(self):
        # LCDs
        self.lcd_p.display(f"{self._snap_p:.1f}")
        self.lcd_r.display(self._snap_r)
        self.lcd_a.display(self._snap_a)
        self.lcd_i.display(round(self._snap_i))

        # Header pulse counter
        self.hdr_pulses.setText(f"PULSES: {self.total_pulses:,}")

        # CamBox delay label
        self._update_delay_label()

        # Feature 4 — check alarms every tick
        self._check_alarms()

        # Graph — skip if frozen (Feature 3) or paused (STOP)
        if self._graph_dirty and not self.graph_paused and not self._display_frozen:
            self._graph_dirty = False
            self.curve_p.setData(X_DATA, list(self.pressure_buf))
            self.curve_i.setData(X_STEP, make_step(self.inj_buf))
            self.curve_c.setData(X_STEP, make_step(self.cam_buf))

    # ── close ─────────────────────────────────────────────────────────
    def closeEvent(self, event):
        self._port_timer.stop()
        self._graph_timer.stop()
        self._alarm_timer.stop()
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
        _lock_sock.bind(('127.0.0.1', 47833))
        _lock_sock.listen(1)
        return True
    except OSError:
        return False


# ══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = QApplication(sys.argv)
    if not _acquire_lock():
        QMessageBox.warning(None, "Already Running",
                            "AUTO PRO TEST is already running!")
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

    win = DieselDashboard()
    win.showMaximized()
    sys.exit(app.exec())
