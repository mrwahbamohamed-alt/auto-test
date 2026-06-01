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
from PyQt6.QtGui import QFont

import serial
import serial.tools.list_ports
import pyqtgraph as pg

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ── constants ──────────────────────────────────────────────────────────
N_SAMPLES    = 400      # عدد العينات في الجراف (2 ثانية عند 5ms)
TELEMETRY_MS = 5        # لازم يتطابق مع ESP32
GRAPH_FPS    = 30       # معدل تحديث الجراف — مفصول عن استقبال البيانات

X_DATA = list(range(N_SAMPLES))

# X للـ step display — كل عينة بتتكرر مرتين
X_STEP = []
for _i in range(N_SAMPLES):
    X_STEP.extend([_i, _i + 0.999])

def make_step(buf):
    out = []
    for v in buf:
        out.extend([v, v])
    return out

# ── stylesheet ─────────────────────────────────────────────────────────
STYLE = """
QMainWindow, QWidget { background-color: #0F0F0F; }
QGroupBox {
    background-color: #161616; border: 1px solid #252525;
    border-radius: 6px; margin-top: 14px;
    font-size: 11px; font-weight: bold; color: #555;
}
QGroupBox::title { subcontrol-origin:margin; subcontrol-position:top left; left:10px; padding:0 5px; }
QLabel { color:#999; font-size:12px; }
QComboBox, QSpinBox {
    background-color:#1E1E1E; border:1px solid #2E2E2E;
    border-radius:4px; padding:4px 8px; color:#DDD; font-size:12px;
}
QComboBox::drop-down { border:none; }
QSlider::groove:horizontal { border:none; height:4px; background:#252525; border-radius:2px; }
QSlider::handle:horizontal { background:#00ADB5; width:14px; height:14px; margin:-5px 0; border-radius:7px; }
QSlider::sub-page:horizontal { background:#00ADB5; border-radius:2px; }
QPushButton {
    background-color:#1E1E1E; border:1px solid #2E2E2E;
    color:#CCC; padding:6px 12px; border-radius:4px; font-size:12px;
}
QPushButton:hover   { background-color:#262626; border-color:#404040; }
QPushButton:pressed { background-color:#141414; }
QLCDNumber { background-color:#060606; border:1px solid #1E1E1E; border-radius:4px; }
QRadioButton { color:#AAA; font-size:12px; }
"""


# ══════════════════════════════════════════════════════════════════════
#  SERIAL WORKER
# ══════════════════════════════════════════════════════════════════════
class SerialWorker(QObject):
    data_received     = pyqtSignal(str)
    error_occurred    = pyqtSignal(str)
    connection_status = pyqtSignal(bool)
    _cmd_signal       = pyqtSignal(str)   # thread-safe write

    def __init__(self):
        super().__init__()
        self.port          = None
        self.is_running    = False
        self._keep_running = True
        self._cmd_signal.connect(self._write)

    def connect_device(self, port, baud):
        try:
            self.port       = serial.Serial(port, baud, timeout=0.1)
            self.is_running = True
            self.connection_status.emit(True)
            logging.info(f"Connected {port} @ {baud}")
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
                    # استنزف كل البيانات المتاحة دفعة واحدة
                    while self.port.in_waiting > 0:
                        raw = self.port.readline().decode('utf-8', errors='ignore').strip()
                        if raw:
                            self.data_received.emit(raw)
                except Exception as e:
                    self.error_occurred.emit(f"Lost: {e}")
                    self.disconnect_device()
            time.sleep(0.005)  # 5ms — يتماشى مع معدل الـ telemetry

    def send_command(self, cmd):
        self._cmd_signal.emit(cmd)

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
        self.setWindowTitle("INJECTOR PRO  —  ESP32 Diesel Control")
        self.resize(1300, 780)
        self.setStyleSheet(STYLE)

        # data
        self.pressure_buf = deque([0.0] * N_SAMPLES, maxlen=N_SAMPLES)
        self.inj_buf      = deque([0.0] * N_SAMPLES, maxlen=N_SAMPLES)
        self.cam_buf      = deque([0.0] * N_SAMPLES, maxlen=N_SAMPLES)
        self.total_pulses = 0
        self.graph_paused = False
        self._graph_dirty = False

        # ── فلاتر EMA ─────────────────────────────────
        self._rpm_ema  = 0.0   # alpha=0.2  → ناعم ومستقر
        self._p_ema    = 0.0   # alpha=0.15 → ناعم جداً للضغط

        # ── Pulse hold — يضمن عرض ثابت للنبضة ────────
        # كل frame = 5ms → 2 frames = 10ms minimum visible width
        self._inj_hold = 0     # عداد تنازلي للـ INJ
        self._cam_hold = 0     # عداد تنازلي للـ CAM
        self._inj_rate_ema = 0.0  # فلتر EMA لـ INJ/s — يمنع الرقص

        # serial
        self.thread = QThread()
        self.worker = SerialWorker()
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.read_loop)
        self.worker.data_received.connect(self._on_data)
        self.worker.error_occurred.connect(lambda m: logging.error(m))
        self.worker.connection_status.connect(self._on_conn)
        self.worker.connection_status.connect(
            lambda ok: QTimer.singleShot(700, self._sync) if ok else None
        )
        self.thread.start()

        self._build_ui()

        self._port_timer = QTimer()
        self._port_timer.timeout.connect(self._refresh_ports)
        self._port_timer.start(2000)
        self._refresh_ports()

        # جراف بيتحدث بـ 30fps مستقل عن معدل الـ telemetry
        self._graph_timer = QTimer()
        self._graph_timer.timeout.connect(self._redraw_graph)
        self._graph_timer.start(1000 // GRAPH_FPS)

    # ── layout ────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QWidget(); self.setCentralWidget(root)
        lay  = QHBoxLayout(root)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(10)

        left = QVBoxLayout(); left.setSpacing(8)
        left.addWidget(self._panel_conn())
        left.addWidget(self._panel_mode())
        left.addWidget(self._panel_params())
        left.addWidget(self._panel_actions())
        left.addStretch()

        right = QVBoxLayout(); right.setSpacing(8)
        right.addWidget(self._panel_status())
        right.addWidget(self._panel_telem())
        right.addWidget(self._panel_graph(), stretch=1)

        lay.addLayout(left,  stretch=0)
        lay.addLayout(right, stretch=1)

    # ── connection panel ──────────────────────────────────────────────
    def _panel_conn(self):
        box = QGroupBox("CONNECTION")
        g   = QGridLayout(box); g.setSpacing(6)

        g.addWidget(QLabel("Port:"), 0, 0)
        self.port_combo = QComboBox(); self.port_combo.setMinimumWidth(110)
        g.addWidget(self.port_combo, 0, 1)

        g.addWidget(QLabel("Baud:"), 1, 0)
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["115200", "57600", "9600"])
        g.addWidget(self.baud_combo, 1, 1)

        self.conn_btn = QPushButton("CONNECT")
        self._btn_style(self.conn_btn, '#0277BD', '#0288D1')
        self.conn_btn.clicked.connect(self._toggle_conn)
        g.addWidget(self.conn_btn, 2, 0, 1, 2)

        self.conn_lbl = QLabel("DISCONNECTED")
        self.conn_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.conn_lbl.setStyleSheet("color:#EF5350; font-weight:bold; font-size:11px;")
        g.addWidget(self.conn_lbl, 3, 0, 1, 2)
        return box

    # ── status bar ────────────────────────────────────────────────────
    def _panel_status(self):
        box = QGroupBox("STATUS")
        h   = QHBoxLayout(box); h.setSpacing(0)

        def cell(title, val, color):
            v = QVBoxLayout()
            t = QLabel(title); t.setAlignment(Qt.AlignmentFlag.AlignCenter)
            t.setStyleSheet("color:#444; font-size:10px; font-weight:bold;")
            l = QLabel(val);   l.setAlignment(Qt.AlignmentFlag.AlignCenter)
            l.setStyleSheet(f"color:{color}; font-weight:bold; font-size:15px;")
            v.addWidget(t); v.addWidget(l)
            return v, l

        l0, self.mode_lbl   = cell("MODE",        "CUSTOM",  "#00ADB5")
        l1, self.run_lbl    = cell("ENGINE",       "STOPPED", "#EF5350")
        l2, self.port_lbl   = cell("PORT",         "—",       "#555")
        l3, self.pulse_lbl  = cell("TOTAL PULSES", "0",       "#00FF88")

        for i, lyt in enumerate([l0, l1, l2, l3]):
            h.addLayout(lyt, stretch=1)
            if i < 3:
                sep = QFrame(); sep.setFrameShape(QFrame.Shape.VLine)
                sep.setStyleSheet("color:#222;"); h.addWidget(sep)
        return box

    # ── mode ──────────────────────────────────────────────────────────
    def _panel_mode(self):
        box = QGroupBox("MODE")
        h   = QHBoxLayout(box); h.setSpacing(12)
        self.mode_grp  = QButtonGroup(self)
        self.rb_custom = QRadioButton("Custom (Freq)")
        self.rb_cam    = QRadioButton("CamBox (Sync)")
        self.rb_custom.setChecked(True)
        self.mode_grp.addButton(self.rb_custom, 0)
        self.mode_grp.addButton(self.rb_cam,    1)
        self.mode_grp.idToggled.connect(
            lambda id, chk: self._on_mode(id) if chk else None)
        h.addWidget(self.rb_custom); h.addWidget(self.rb_cam)
        return box

    # ── parameters ────────────────────────────────────────────────────
    def _panel_params(self):
        box = QGroupBox("PARAMETERS")
        g   = QGridLayout(box); g.setSpacing(6)

        def row(label, lo, hi, val, step=1):
            lbl = QLabel(label)
            sp  = QSpinBox();  sp.setRange(lo, hi); sp.setValue(val); sp.setSingleStep(step)
            sl  = QSlider(Qt.Orientation.Horizontal); sl.setRange(lo, hi); sl.setValue(val)
            sp.valueChanged.connect(sl.setValue)
            sl.valueChanged.connect(sp.setValue)
            return lbl, sp, sl

        self.pw_lbl,  self.pw_sp,  self.pw_sl  = row("Pulse Width (µs)", 200, 3000, 1000, 50)
        self.fr_lbl,  self.fr_sp,  self.fr_sl  = row("Frequency (Hz)",     1,  100,   25)
        self.an_lbl,  self.an_sp,  self.an_sl  = row("Delay Angle (°)",    0,   45,    0)

        self.pw_sp.valueChanged.connect(lambda v: self.worker.send_command(f"w{v}"))
        self.fr_sp.valueChanged.connect(lambda v: self.worker.send_command(f"f{v}"))
        self.an_sp.valueChanged.connect(lambda v: self.worker.send_command(f"a{v}"))

        for i, (lbl, sp, sl) in enumerate([
            (self.pw_lbl, self.pw_sp, self.pw_sl),
            (self.fr_lbl, self.fr_sp, self.fr_sl),
            (self.an_lbl, self.an_sp, self.an_sl),
        ]):
            g.addWidget(lbl, i*2,   0)
            g.addWidget(sp,  i*2,   1)
            g.addWidget(sl,  i*2+1, 0, 1, 2)

        self._cam_visible(False)
        return box

    # ── actions ───────────────────────────────────────────────────────
    def _panel_actions(self):
        box = QGroupBox("ACTUATORS")
        g   = QGridLayout(box); g.setSpacing(8)

        self.start_btn = QPushButton("▶  START")
        self.start_btn.setFont(QFont("Arial", 13, QFont.Weight.Bold))
        self.start_btn.setMinimumHeight(48)
        self.start_btn.setStyleSheet("""
            QPushButton         { background:#1B5E20; color:#69F0AE; border-radius:5px; border:1px solid #2E7D32; }
            QPushButton:hover   { background:#2E7D32; }
            QPushButton:pressed { background:#0A3D12; }
        """)
        self.start_btn.clicked.connect(self._on_start)

        self.stop_btn = QPushButton("■  STOP")
        self.stop_btn.setFont(QFont("Arial", 13, QFont.Weight.Bold))
        self.stop_btn.setMinimumHeight(48)
        self.stop_btn.setStyleSheet("""
            QPushButton         { background:#7F0000; color:#FF8A80; border-radius:5px; border:1px solid #B71C1C; }
            QPushButton:hover   { background:#B71C1C; }
            QPushButton:pressed { background:#4A0000; }
        """)
        self.stop_btn.clicked.connect(self._on_stop)

        self.sync_btn = QPushButton("↺  SYNC TO ESP32")
        self.sync_btn.setMinimumHeight(30)
        self.sync_btn.setStyleSheet("""
            QPushButton       { background:#1A237E; color:#82B1FF; border-radius:4px; border:1px solid #283593; font-size:11px; }
            QPushButton:hover { background:#283593; }
        """)
        self.sync_btn.clicked.connect(self._sync)

        g.addWidget(self.start_btn, 0, 0)
        g.addWidget(self.stop_btn,  0, 1)
        g.addWidget(self.sync_btn,  1, 0, 1, 2)
        return box

    # ── telemetry LCDs ────────────────────────────────────────────────
    def _panel_telem(self):
        box = QGroupBox("TELEMETRY")
        h   = QHBoxLayout(box); h.setSpacing(10)

        def lcd(title, color, digits):
            w = QLCDNumber(); w.setDigitCount(digits); w.setMinimumHeight(60)
            w.setStyleSheet(f"QLCDNumber{{border:1px solid {color}33; color:{color}; background:#040404;}}")
            lbl = QLabel(title); lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("color:#444; font-size:10px; font-weight:bold;")
            v = QVBoxLayout(); v.addWidget(lbl); v.addWidget(w)
            return v, w

        l0, self.lcd_p = lcd("PRESSURE (BAR)", "#FFA726", 7)
        l1, self.lcd_r = lcd("RPM",            "#00ADB5", 5)
        l2, self.lcd_a = lcd("DELAY (°)",      "#AB47BC", 3)
        l3, self.lcd_i = lcd("INJ / s",        "#00FF88", 4)

        for l in [l0, l1, l2, l3]:
            h.addLayout(l)
        return box

    # ── graph (3 stacked plots) ───────────────────────────────────────
    def _panel_graph(self):
        box = QGroupBox("LIVE GRAPH")
        lay = QVBoxLayout(box); lay.setContentsMargins(4, 18, 4, 4)

        self.glw = pg.GraphicsLayoutWidget()
        self.glw.setBackground('#D0D0D0')

        # Pressure
        self.plt_p = self.glw.addPlot(row=0, col=0)
        self.plt_p.setLabel('left', 'BAR', color='#B33000', **{'font-size':'9pt'})
        self.plt_p.getAxis('left').setTextPen('#B33000')
        self.plt_p.getAxis('left').setWidth(55)
        self.plt_p.showGrid(x=True, y=True, alpha=0.3)
        self.plt_p.setMouseEnabled(x=True, y=True)
        self.plt_p.hideAxis('bottom')
        self.curve_p = self.plt_p.plot(X_DATA, list(self.pressure_buf),
                                        pen=pg.mkPen('#B33000', width=2))

        # Injector
        self.plt_i = self.glw.addPlot(row=1, col=0)
        self.plt_i.setLabel('left', 'INJ', color='#006030', **{'font-size':'9pt'})
        self.plt_i.getAxis('left').setTextPen('#006030')
        self.plt_i.getAxis('left').setWidth(55)
        self.plt_i.setYRange(-0.1, 1.4)
        self.plt_i.getAxis('left').setTicks([[(0, '0'), (1, '1')]])
        self.plt_i.showGrid(x=True, y=False, alpha=0.3)
        self.plt_i.setMouseEnabled(x=True, y=False)
        self.plt_i.setXLink(self.plt_p)
        self.plt_i.hideAxis('bottom')
        self.curve_i = pg.PlotCurveItem(X_STEP, [0.0]*(N_SAMPLES*2),
                                         pen=pg.mkPen('#006030', width=2),
                                         fillLevel=0.0,
                                         brush=pg.mkBrush(0, 96, 48, 90))
        self.plt_i.addItem(self.curve_i)

        # CamBox
        self.plt_c = self.glw.addPlot(row=2, col=0)
        self.plt_c.setLabel('left', 'CAM', color='#004466', **{'font-size':'9pt'})
        self.plt_c.getAxis('left').setTextPen('#004466')
        self.plt_c.getAxis('left').setWidth(55)
        self.plt_c.setYRange(-0.1, 1.4)
        self.plt_c.getAxis('left').setTicks([[(0,'0'),(1,'1')]])
        self.plt_c.setLabel('bottom', f'Samples  ({TELEMETRY_MS} ms each) — {N_SAMPLES * TELEMETRY_MS // 1000} sec window',
                             color='#333', **{'font-size':'9pt'})
        self.plt_c.getAxis('bottom').setTextPen('#333')
        self.plt_c.showGrid(x=True, y=False, alpha=0.3)
        self.plt_c.setMouseEnabled(x=True, y=False)
        self.plt_c.setXLink(self.plt_p)
        self.curve_c = pg.PlotCurveItem(X_STEP, [0.0]*(N_SAMPLES*2),
                                         pen=pg.mkPen('#004466', width=2),
                                         fillLevel=0.0,
                                         brush=pg.mkBrush(0, 68, 102, 90))
        self.plt_c.addItem(self.curve_c)

        self.glw.ci.layout.setRowStretchFactor(0, 3)
        self.glw.ci.layout.setRowStretchFactor(1, 2)
        self.glw.ci.layout.setRowStretchFactor(2, 2)

        lay.addWidget(self.glw)
        return box

    # ── helpers ───────────────────────────────────────────────────────
    def _btn_style(self, btn, c1, c2):
        btn.setStyleSheet(
            f"QPushButton{{background:{c1};color:white;font-weight:bold;}}"
            f"QPushButton:hover{{background:{c2};}}")

    def _cam_visible(self, vis):
        for w in [self.fr_lbl, self.fr_sp, self.fr_sl]:
            w.setVisible(not vis)
        for w in [self.an_lbl, self.an_sp, self.an_sl]:
            w.setVisible(vis)

    # ── actions ───────────────────────────────────────────────────────
    def _redraw_graph(self):
        if not self._graph_dirty or self.graph_paused:
            return
        self._graph_dirty = False
        self.curve_p.setData(X_DATA, list(self.pressure_buf))
        self.curve_i.setData(X_STEP, make_step(self.inj_buf))
        self.curve_c.setData(X_STEP, make_step(self.cam_buf))

    def _on_start(self):
        self.worker.send_command("start")
        self.graph_paused = False
        self.run_lbl.setText("RUNNING")
        self.run_lbl.setStyleSheet("color:#00FF88; font-weight:bold; font-size:15px;")

    def _on_stop(self):
        self.worker.send_command("stop")
        self.graph_paused = True
        self.run_lbl.setText("STOPPED")
        self.run_lbl.setStyleSheet("color:#EF5350; font-weight:bold; font-size:15px;")

    def _on_mode(self, mid):
        self.worker.send_command("mode")
        self._cam_visible(mid == 1)
        if mid == 0:
            self.mode_lbl.setText("CUSTOM")
            self.mode_lbl.setStyleSheet("color:#00ADB5; font-weight:bold; font-size:15px;")
        else:
            self.mode_lbl.setText("CAMBOX")
            self.mode_lbl.setStyleSheet("color:#AB47BC; font-weight:bold; font-size:15px;")

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
        if not ok:
            # reset فلاتر عند الفصل عشان ما تبداش من قيم قديمة
            self._rpm_ema = self._p_ema = self._inj_rate_ema = 0.0
            self._inj_hold = self._cam_hold = 0
        if ok:
            self.conn_btn.setText("DISCONNECT")
            self._btn_style(self.conn_btn, '#7F0000', '#B71C1C')
            self.conn_lbl.setText("CONNECTED")
            self.conn_lbl.setStyleSheet("color:#66BB6A; font-weight:bold; font-size:11px;")
            self.port_lbl.setText(self.port_combo.currentText())
            self.port_lbl.setStyleSheet("color:#CCC; font-weight:bold; font-size:15px;")
        else:
            self.conn_btn.setText("CONNECT")
            self._btn_style(self.conn_btn, '#0277BD', '#0288D1')
            self.conn_lbl.setText("DISCONNECTED")
            self.conn_lbl.setStyleSheet("color:#EF5350; font-weight:bold; font-size:11px;")
            self.port_lbl.setText("—")
            self.port_lbl.setStyleSheet("color:#555; font-weight:bold; font-size:15px;")

    # ── telemetry parser ──────────────────────────────────────────────
    def _on_data(self, raw):
        # تجاهل ردود الأوامر
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

            # ── EMA filters ───────────────────────────
            self._p_ema   = 0.15 * p + 0.85 * self._p_ema
            self._rpm_ema = 0.08 * r + 0.92 * self._rpm_ema

            # ── LCDs (قيم مفلترة) ─────────────────────
            self.lcd_p.display(f"{self._p_ema:.1f}")
            self.lcd_r.display(int(self._rpm_ema))
            self.lcd_a.display(a)
            raw_inj_rate = i * (1000 / TELEMETRY_MS)
            self._inj_rate_ema = 0.1 * raw_inj_rate + 0.9 * self._inj_rate_ema
            self.lcd_i.display(round(self._inj_rate_ema))

            # ── pulse counter ──────────────────────────
            self.total_pulses += i
            self.pulse_lbl.setText(f"{self.total_pulses:,}")

            # ── Pulse hold — نبضة ثابتة العرض ─────────
            if i > 0:
                self._inj_hold = 2          # امسك HIGH لمدة 2 frames
            elif self._inj_hold > 0:
                self._inj_hold -= 1

            if c > 0:
                self._cam_hold = 2
            elif self._cam_hold > 0:
                self._cam_hold -= 1

            inj_display = 1.0 if (i > 0 or self._inj_hold > 0) else 0.0
            cam_display = 1.0 if (c > 0 or self._cam_hold > 0) else 0.0

            # ── buffers ────────────────────────────────
            self.pressure_buf.append(self._p_ema)
            self.inj_buf.append(inj_display)
            self.cam_buf.append(cam_display)
            self._graph_dirty = True

        except Exception as e:
            logging.warning(f"Parse: {raw} → {e}")

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
                            "INJECTOR PRO شغال بالفعل!\nأغلق النسخة الموجودة الأول.")
        sys.exit(0)

    pg.setConfigOptions(antialias=True, foreground='#555')
    app.setStyle("Fusion")
    win = DieselDashboard()
    win.show()
    sys.exit(app.exec())
