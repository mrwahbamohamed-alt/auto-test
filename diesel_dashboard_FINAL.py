import sys
import time
import logging
import socket
from collections import deque

from PyQt6.QtCore import QObject, pyqtSignal, QThread, Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QGroupBox, QLabel, QComboBox, QPushButton, QSlider,
    QSpinBox, QRadioButton, QButtonGroup, QLCDNumber, QMessageBox, QFrame
)
from PyQt6.QtGui import QFont, QPalette, QColor

import serial
import serial.tools.list_ports
import pyqtgraph as pg

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

# ── constants ─────────────────────────────────────────────────────────
N_SAMPLES    = 300
TELEMETRY_MS = 10
GRAPH_FPS    = 30

# ── Hartridge-inspired color palette ──────────────────────────────────
BG        = '#0B0D11'
PANEL     = '#111318'
HEADER    = '#0D1420'
BORDER    = '#1C2130'
BORDER2   = '#2A3347'

PH_GREEN  = '#00E676'   # phosphor green  → INJ
PH_AMBER  = '#FFB300'   # amber           → Pressure
PH_BLUE   = '#29B6F6'   # ice blue        → CAM / Custom mode
PH_PURPLE = '#CE93D8'   # purple          → RPM
PH_RED    = '#EF5350'   # red             → stop / error
PH_CYAN   = '#00BCD4'   # cyan            → slider / accent

TXT_PRI   = '#E8EAF0'
TXT_SEC   = '#8892A4'
TXT_DIM   = '#3D4558'

# ── graph colors ──────────────────────────────────────────────────────
G_BG      = '#060912'   # scope background (CRT-like)
G_GRID    = '#111926'   # grid lines
G_AMBER   = '#FFB300'
G_GREEN   = '#00E676'
G_BLUE    = '#29B6F6'

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

# ── stylesheet ────────────────────────────────────────────────────────
STYLE = f"""
QMainWindow, QWidget {{ background:{BG}; color:{TXT_PRI}; }}

QGroupBox {{
    background:{PANEL}; border:1px solid {BORDER};
    border-radius:6px; margin-top:20px;
    font-size:9px; font-weight:bold;
    color:{TXT_DIM}; letter-spacing:2px;
}}
QGroupBox::title {{
    subcontrol-origin:margin; subcontrol-position:top left;
    left:10px; padding:0 8px;
    background:{PANEL};
}}

QLabel {{ color:{TXT_SEC}; font-size:12px; }}

QComboBox, QSpinBox {{
    background:{BORDER}; border:1px solid {BORDER2};
    border-radius:4px; padding:5px 10px;
    color:{TXT_PRI}; font-size:12px; font-family:monospace;
}}
QComboBox:focus, QSpinBox:focus {{ border:1px solid {PH_BLUE}; }}
QComboBox::drop-down {{ border:none; width:0; }}
QComboBox::down-arrow {{ image:none; }}

QSlider::groove:horizontal {{
    border:none; height:3px;
    background:{BORDER}; border-radius:2px;
}}
QSlider::handle:horizontal {{
    background:{PH_CYAN}; width:13px; height:13px;
    margin:-5px 0; border-radius:7px;
    border:2px solid {BG};
}}
QSlider::sub-page:horizontal {{ background:{PH_CYAN}; border-radius:2px; }}

QPushButton {{
    background:{BORDER}; border:1px solid {BORDER2};
    color:{TXT_SEC}; padding:7px 14px;
    border-radius:5px; font-size:12px;
}}
QPushButton:hover  {{ background:{BORDER2}; color:{TXT_PRI}; border-color:{PH_BLUE}; }}
QPushButton:pressed {{ background:{BG}; }}

QLCDNumber {{ background:{BG}; border:none; border-radius:4px; }}

QRadioButton {{ color:{TXT_SEC}; font-size:12px; spacing:8px; }}
QRadioButton::indicator {{
    width:13px; height:13px;
    border:2px solid {BORDER2}; border-radius:7px; background:{BORDER};
}}
QRadioButton::indicator:checked {{ background:{PH_CYAN}; border-color:{PH_CYAN}; }}

QFrame[frameShape="4"] {{ color:{BORDER2}; }}
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
        self.setWindowTitle("INJECTOR PRO  ·  Diesel Injection Test System")
        self.resize(1400, 820)
        self.setStyleSheet(STYLE)

        # buffers
        self.pressure_buf = deque([0.0] * N_SAMPLES, maxlen=N_SAMPLES)
        self.inj_buf      = deque([0.0] * N_SAMPLES, maxlen=N_SAMPLES)
        self.cam_buf      = deque([0.0] * N_SAMPLES, maxlen=N_SAMPLES)

        # state
        self.total_pulses = 0
        self.graph_paused = False
        self._graph_dirty = False
        self._mode_id     = 0

        # EMA
        self._p_ema   = 0.0
        self._rpm_ema = 0.0
        self._inj_ema = 0.0

        # pulse hold
        self._inj_hold = 0
        self._cam_hold = 0

        # LCD snapshot (updated at 30fps)
        self._snap_p = 0.0
        self._snap_r = 0
        self._snap_a = 0
        self._snap_i = 0.0

        # serial
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

        h = QHBoxLayout(bar)
        h.setContentsMargins(16, 0, 16, 0)

        # Logo / title
        logo = QLabel("⬡  INJECTOR PRO")
        logo.setStyleSheet(
            f"color:{PH_GREEN}; font-size:15px; font-weight:bold;"
            f" font-family:monospace; letter-spacing:2px;")

        # Mode pill
        self.hdr_mode = QLabel("● CUSTOM MODE")
        self.hdr_mode.setStyleSheet(
            f"color:{PH_BLUE}; font-size:11px; font-family:monospace; letter-spacing:1px;")

        # Connection status
        self.hdr_conn = QLabel("○  DISCONNECTED")
        self.hdr_conn.setStyleSheet(
            f"color:{PH_RED}; font-size:11px; font-family:monospace; letter-spacing:1px;")

        # Total pulses
        self.hdr_pulses = QLabel("PULSES: 0")
        self.hdr_pulses.setStyleSheet(
            f"color:{TXT_DIM}; font-size:11px; font-family:monospace;")

        h.addWidget(logo)
        h.addSpacing(30)
        h.addWidget(self.hdr_mode)
        h.addStretch()
        h.addWidget(self.hdr_pulses)
        h.addSpacing(20)
        h.addWidget(self._vsep())
        h.addSpacing(20)
        h.addWidget(self.hdr_conn)
        return bar

    # ──────────────────────────────────────────────────────────────────
    #  LEFT CONTROL PANEL
    # ──────────────────────────────────────────────────────────────────
    def _make_left(self):
        w = QWidget(); w.setFixedWidth(270)
        v = QVBoxLayout(w); v.setSpacing(10); v.setContentsMargins(0,0,0,0)
        v.addWidget(self._panel_conn())
        v.addWidget(self._panel_mode())
        v.addWidget(self._panel_params())
        v.addWidget(self._panel_actions())
        v.addStretch()
        return w

    # ──────────────────────────────────────────────────────────────────
    #  RIGHT DISPLAY PANEL
    # ──────────────────────────────────────────────────────────────────
    def _make_right(self):
        w = QWidget()
        v = QVBoxLayout(w); v.setSpacing(10); v.setContentsMargins(0,0,0,0)
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

        self.conn_lbl = QLabel("● DISCONNECTED")
        self.conn_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.conn_lbl.setStyleSheet(
            f"color:{PH_RED}; font-weight:bold; font-size:11px; font-family:monospace;")
        g.addWidget(self.conn_lbl, 3, 0, 1, 2)
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
            g.addWidget(lbl, i*2,   0, 1, 2)
            g.addWidget(sp,  i*2,   2)
            g.addWidget(sl,  i*2+1, 0, 1, 3)

        # CamBox delay info
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

        self.start_btn = QPushButton("▶   START")
        self.start_btn.setFont(QFont("Arial", 13, QFont.Weight.Bold))
        self.start_btn.setMinimumHeight(52)
        self.start_btn.setStyleSheet(f"""
            QPushButton         {{background:#052E16;color:{PH_GREEN};
                                  border:1px solid #064E3B;border-radius:6px;}}
            QPushButton:hover   {{background:#064E3B;border-color:{PH_GREEN};}}
            QPushButton:pressed {{background:#021208;}}
        """)
        self.start_btn.clicked.connect(self._on_start)

        self.stop_btn = QPushButton("■   STOP")
        self.stop_btn.setFont(QFont("Arial", 13, QFont.Weight.Bold))
        self.stop_btn.setMinimumHeight(52)
        self.stop_btn.setStyleSheet(f"""
            QPushButton         {{background:#450A0A;color:{PH_RED};
                                  border:1px solid #7F1D1D;border-radius:6px;}}
            QPushButton:hover   {{background:#7F1D1D;border-color:{PH_RED};}}
            QPushButton:pressed {{background:#1A0303;}}
        """)
        self.stop_btn.clicked.connect(self._on_stop)

        self.sync_btn = QPushButton("↺   SYNC TO ESP32")
        self.sync_btn.setMinimumHeight(30)
        self.sync_btn.setStyleSheet(f"""
            QPushButton       {{background:#0C1A2E;color:{PH_BLUE};
                                border:1px solid #1D3A6E;border-radius:5px;font-size:11px;}}
            QPushButton:hover {{background:#1D3A6E;color:{TXT_PRI};}}
        """)
        self.sync_btn.clicked.connect(self._sync)

        g.addWidget(self.start_btn, 0, 0)
        g.addWidget(self.stop_btn,  0, 1)
        g.addWidget(self.sync_btn,  1, 0, 1, 2)
        return box

    # ── meters panel (Hartridge-style large displays) ─────────────────
    def _panel_meters(self):
        box = QGroupBox("MEASUREMENTS")
        h   = QHBoxLayout(box); h.setSpacing(2)

        def meter(label, color, digits, unit=""):
            # Outer frame
            frame = QWidget()
            frame.setStyleSheet(
                f"background:{PANEL}; border:1px solid {BORDER2}; border-radius:6px;")
            v = QVBoxLayout(frame); v.setContentsMargins(10, 8, 10, 8); v.setSpacing(4)

            # Top label
            lbl = QLabel(label.upper())
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(
                f"color:{color}50; font-size:9px; font-weight:bold;"
                f" letter-spacing:2px; font-family:monospace; border:none;")

            # LCD
            lcd = QLCDNumber()
            lcd.setDigitCount(digits)
            lcd.setMinimumHeight(70)
            lcd.setSegmentStyle(QLCDNumber.SegmentStyle.Flat)
            lcd.setStyleSheet(
                f"QLCDNumber{{color:{color}; background:#000610;"
                f" border:1px solid {color}20; border-radius:4px;}}")

            # Bottom unit label
            unit_lbl = QLabel(unit)
            unit_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            unit_lbl.setStyleSheet(
                f"color:{color}60; font-size:10px; font-family:monospace; border:none;")

            v.addWidget(lbl)
            v.addWidget(lcd)
            v.addWidget(unit_lbl)
            return frame, lcd

        f0, self.lcd_r = meter("RPM",      PH_PURPLE, 5, "rev/min")
        f1, self.lcd_p = meter("PRESSURE", PH_AMBER,  7, "BAR")
        f2, self.lcd_i = meter("INJ RATE", PH_GREEN,  4, "inj/s")
        f3, self.lcd_a = meter("ANGLE",    PH_BLUE,   3, "deg")

        # Engine status indicator
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

        for f in [f0, f1, f2, f3, status_box]:
            h.addWidget(f, stretch=1)

        return box

    # ── oscilloscope / waveform ───────────────────────────────────────
    def _panel_scope(self):
        box = QGroupBox("WAVEFORM  OSCILLOSCOPE")
        lay = QVBoxLayout(box); lay.setContentsMargins(4, 20, 4, 4)

        self.glw = pg.GraphicsLayoutWidget()
        self.glw.setBackground(G_BG)

        def scope_plot(row, color, label, is_digital=False):
            p = self.glw.addPlot(row=row, col=0)
            p.setLabel('left', label, color=color, **{'font-size': '9pt'})
            p.getAxis('left').setTextPen(color)
            p.getAxis('left').setWidth(52)
            p.getAxis('left').setPen(pg.mkPen(BORDER2))
            p.getAxis('bottom').setPen(pg.mkPen(BORDER2))
            if is_digital:
                p.getAxis('left').setTicks([[(0, '0'), (1, '1')]])
                p.setYRange(-0.07, 1.3)
            p.showGrid(x=True, y=True, alpha=0.15)
            p.setMouseEnabled(x=True, y=(not is_digital))
            return p

        # Plot 1 — Pressure (analog)
        self.plt_p = scope_plot(0, G_AMBER, 'BAR')
        self.plt_p.hideAxis('bottom')
        self.curve_p = self.plt_p.plot(
            X_DATA, list(self.pressure_buf),
            pen=pg.mkPen(G_AMBER, width=2))

        # Plot 2 — Injector (digital)
        self.plt_i = scope_plot(1, G_GREEN, 'INJ', is_digital=True)
        self.plt_i.hideAxis('bottom')
        self.plt_i.setXLink(self.plt_p)
        self.curve_i = pg.PlotCurveItem(
            X_STEP, [0.0] * (N_SAMPLES * 2),
            pen=pg.mkPen(G_GREEN, width=2),
            fillLevel=0.0,
            brush=pg.mkBrush(0, 230, 118, 35))
        self.plt_i.addItem(self.curve_i)

        # Plot 3 — CamBox (digital)
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
            brush=pg.mkBrush(41, 182, 246, 35))
        self.plt_c.addItem(self.curve_c)

        # Height ratios
        self.glw.ci.layout.setRowStretchFactor(0, 3)
        self.glw.ci.layout.setRowStretchFactor(1, 2)
        self.glw.ci.layout.setRowStretchFactor(2, 2)
        self.glw.ci.layout.setSpacing(1)

        lay.addWidget(self.glw)
        return box

    # ── helpers ───────────────────────────────────────────────────────
    def _dim(self, txt):
        l = QLabel(txt)
        l.setStyleSheet(
            f"color:{TXT_DIM}; font-size:9px; font-weight:bold;"
            f" letter-spacing:1px; font-family:monospace;")
        return l

    def _vsep(self):
        f = QFrame(); f.setFrameShape(QFrame.Shape.VLine)
        f.setStyleSheet(f"color:{BORDER2};")
        f.setFixedHeight(22)
        return f

    def _style_conn_btn(self, connected):
        if connected:
            self.conn_btn.setStyleSheet(f"""
                QPushButton       {{background:#450A0A;color:{PH_RED};
                                    font-weight:bold;border-radius:5px;border:1px solid #7F1D1D;}}
                QPushButton:hover {{background:#7F1D1D;}}""")
        else:
            self.conn_btn.setStyleSheet(f"""
                QPushButton       {{background:#0C1A2E;color:{PH_BLUE};
                                    font-weight:bold;border-radius:5px;border:1px solid #1D3A6E;}}
                QPushButton:hover {{background:#1D3A6E;color:{TXT_PRI};}}""")

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
                    f"({self.an_sp.value()}° @ {int(self._rpm_ema)} RPM)")
            else:
                self.delay_lbl.setText("DELAY  —  waiting for RPM signal")

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
            self.hdr_mode.setText("●  CUSTOM MODE")
            self.hdr_mode.setStyleSheet(
                f"color:{PH_BLUE}; font-size:11px; font-family:monospace;")
        else:
            self.mode_lbl.setText("CAMBOX")
            self.mode_lbl.setStyleSheet(
                f"color:{PH_PURPLE}; font-size:11px; font-family:monospace;"
                f" letter-spacing:1px; border:none;")
            self.hdr_mode.setText("●  CAMBOX MODE")
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
            self.conn_lbl.setText("● CONNECTED")
            self.conn_lbl.setStyleSheet(
                f"color:{PH_GREEN}; font-weight:bold; font-size:11px; font-family:monospace;")
            port = self.port_combo.currentText()
            self.hdr_conn.setText(f"●  {port}  CONNECTED")
            self.hdr_conn.setStyleSheet(
                f"color:{PH_GREEN}; font-size:11px; font-family:monospace;")
        else:
            self.conn_btn.setText("CONNECT")
            self.conn_lbl.setText("○  DISCONNECTED")
            self.conn_lbl.setStyleSheet(
                f"color:{PH_RED}; font-weight:bold; font-size:11px; font-family:monospace;")
            self.hdr_conn.setText("○  DISCONNECTED")
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

            self._p_ema   = 0.15 * p + 0.85 * self._p_ema
            self._rpm_ema = 0.05 * r + 0.95 * self._rpm_ema
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

        # Header
        self.hdr_pulses.setText(f"PULSES: {self.total_pulses:,}")

        # CamBox delay
        self._update_delay_label()

        # Graph
        if self._graph_dirty and not self.graph_paused:
            self._graph_dirty = False
            self.curve_p.setData(X_DATA, list(self.pressure_buf))
            self.curve_i.setData(X_STEP, make_step(self.inj_buf))
            self.curve_c.setData(X_STEP, make_step(self.cam_buf))

    # ── close ─────────────────────────────────────────────────────────
    def closeEvent(self, event):
        self._port_timer.stop()
        self._graph_timer.stop()
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

    pg.setConfigOptions(antialias=True, foreground=TXT_DIM)
    app.setStyle("Fusion")
    win = DieselDashboard()
    win.show()
    sys.exit(app.exec())
