import sys
import time
import logging
from PyQt6.QtCore import QObject, pyqtSignal, QThread, Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QGroupBox, QLabel, QComboBox, QPushButton, QSlider,
    QSpinBox, QRadioButton, QButtonGroup, QLCDNumber, QMessageBox
)
from PyQt6.QtGui import QFont
import serial
import serial.tools.list_ports
import pyqtgraph as pg

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

INDUSTRIAL_QSS = """
QMainWindow { background-color: #121212; }
QWidget { background-color: #121212; }
QGroupBox {
    background-color: #1A1A1A; border: 1px solid #2A2A2A;
    border-radius: 6px; margin-top: 12px;
    font-size: 12px; font-weight: bold; color: #888;
}
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 12px; padding: 0 4px; }
QLabel { color: #999; font-size: 12px; }
QComboBox, QSpinBox {
    background-color: #222; border: 1px solid #333;
    border-radius: 4px; padding: 4px 8px; color: #DDD; font-size: 12px;
}
QComboBox::drop-down { border: none; }
QSlider::groove:horizontal { border: none; height: 4px; background: #2A2A2A; border-radius: 2px; }
QSlider::handle:horizontal {
    background: #00ADB5; width: 14px; height: 14px;
    margin: -5px 0; border-radius: 7px;
}
QSlider::sub-page:horizontal { background: #00ADB5; border-radius: 2px; }
QPushButton {
    background-color: #222; border: 1px solid #333;
    color: #CCC; padding: 6px 12px; border-radius: 4px; font-size: 12px;
}
QPushButton:hover { background-color: #2A2A2A; border-color: #444; }
QPushButton:pressed { background-color: #1A1A1A; }
QLCDNumber { background-color: #0A0A0A; border: 1px solid #2A2A2A; border-radius: 4px; color: #00FF88; }
"""


class SerialWorker(QObject):
    data_received = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    connection_status = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self.serial_port = None
        self.is_running = False
        self._keep_running = True

    def connect_device(self, port, baudrate):
        try:
            self.serial_port = serial.Serial(port, baudrate, timeout=0.1)
            self.is_running = True
            self.connection_status.emit(True)
            logging.info(f"Connected to {port} at {baudrate}")
        except Exception as e:
            self.error_occurred.emit(str(e))
            self.connection_status.emit(False)

    def disconnect_device(self):
        self.is_running = False
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
        self.connection_status.emit(False)
        logging.info("Disconnected safely.")

    def read_loop(self):
        while self._keep_running:
            if self.is_running and self.serial_port and self.serial_port.is_open:
                try:
                    if self.serial_port.in_waiting > 0:
                        data = self.serial_port.readline().decode('utf-8', errors='ignore').strip()
                        if data:
                            self.data_received.emit(data)
                except Exception as e:
                    self.error_occurred.emit(f"Connection lost: {str(e)}")
                    self.disconnect_device()
            time.sleep(0.01)

    def send_command(self, cmd):
        if self.serial_port and self.serial_port.is_open:
            try:
                self.serial_port.write(f"{cmd}\n".encode('utf-8'))
                logging.info(f"Sent: {cmd}")
            except Exception as e:
                self.error_occurred.emit(f"Write error: {str(e)}")


class DieselDashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("INJECTOR PRO  —  ESP32 Diesel Control")
        self.resize(1000, 620)
        self.setStyleSheet(INDUSTRIAL_QSS)

        self.serial_thread = QThread()
        self.worker = SerialWorker()
        self.worker.moveToThread(self.serial_thread)

        self.serial_thread.started.connect(self.worker.read_loop)
        self.worker.data_received.connect(self.parse_telemetry)
        self.worker.error_occurred.connect(self.handle_error)
        self.worker.connection_status.connect(self.update_connection_ui)

        self.serial_thread.start()

        self.x_data = list(range(100))
        self.pressure_data = [0] * 100

        self.init_ui()

        self.port_timer = QTimer()
        self.port_timer.timeout.connect(self.refresh_ports)
        self.port_timer.start(2000)
        self.refresh_ports()

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        left_panel = QVBoxLayout()
        left_panel.setSpacing(8)
        left_panel.addWidget(self.create_connection_panel())
        left_panel.addWidget(self.create_mode_panel())
        left_panel.addWidget(self.create_control_panel())
        left_panel.addWidget(self.create_action_panel())
        left_panel.addStretch()

        right_panel = QVBoxLayout()
        right_panel.setSpacing(8)
        right_panel.addWidget(self.create_telemetry_panel())
        right_panel.addWidget(self.create_graph_panel())

        main_layout.addLayout(left_panel, stretch=2)
        main_layout.addLayout(right_panel, stretch=3)

    def create_connection_panel(self):
        box = QGroupBox("CONNECTION")
        layout = QGridLayout(box)
        layout.setSpacing(6)

        layout.addWidget(QLabel("Port:"), 0, 0)
        self.port_combo = QComboBox()
        layout.addWidget(self.port_combo, 0, 1)

        layout.addWidget(QLabel("Baud:"), 1, 0)
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["115200", "9600", "57600"])
        layout.addWidget(self.baud_combo, 1, 1)

        self.conn_btn = QPushButton("CONNECT")
        self.conn_btn.setStyleSheet("QPushButton { background-color: #0277BD; color: white; font-weight: bold; } QPushButton:hover { background-color: #0288D1; }")
        self.conn_btn.clicked.connect(self.toggle_connection)
        layout.addWidget(self.conn_btn, 2, 0, 1, 2)

        self.status_lbl = QLabel("DISCONNECTED")
        self.status_lbl.setStyleSheet("color: #EF5350; font-weight: bold; font-size: 11px;")
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_lbl, 3, 0, 1, 2)

        return box

    def create_mode_panel(self):
        box = QGroupBox("MODE")
        layout = QHBoxLayout(box)
        layout.setSpacing(12)

        self.mode_group = QButtonGroup(self)
        self.custom_mode_rb = QRadioButton("Custom (Freq)")
        self.cambox_mode_rb = QRadioButton("CamBox (Sync)")

        self.custom_mode_rb.setChecked(True)
        self.mode_group.addButton(self.custom_mode_rb, 0)
        self.mode_group.addButton(self.cambox_mode_rb, 1)

        layout.addWidget(self.custom_mode_rb)
        layout.addWidget(self.cambox_mode_rb)

        self.mode_group.idToggled.connect(lambda id, checked: self.handle_mode_change(id) if checked else None)
        return box

    def create_control_panel(self):
        box = QGroupBox("PARAMETERS")
        layout = QGridLayout(box)
        layout.setSpacing(6)

        layout.addWidget(QLabel("Pulse Width (µs)"), 0, 0)
        self.pw_spin = QSpinBox()
        self.pw_spin.setRange(200, 3000)
        self.pw_spin.setValue(1000)
        self.pw_spin.setSingleStep(50)
        layout.addWidget(self.pw_spin, 0, 1)

        self.pw_slider = QSlider(Qt.Orientation.Horizontal)
        self.pw_slider.setRange(200, 3000)
        self.pw_slider.setValue(1000)
        layout.addWidget(self.pw_slider, 1, 0, 1, 2)

        self.freq_lbl = QLabel("Frequency (Hz)")
        layout.addWidget(self.freq_lbl, 2, 0)
        self.freq_spin = QSpinBox()
        self.freq_spin.setRange(1, 100)
        self.freq_spin.setValue(25)
        layout.addWidget(self.freq_spin, 2, 1)

        self.freq_slider = QSlider(Qt.Orientation.Horizontal)
        self.freq_slider.setRange(1, 100)
        self.freq_slider.setValue(25)
        layout.addWidget(self.freq_slider, 3, 0, 1, 2)

        self.delay_lbl = QLabel("Delay Angle (°)")
        layout.addWidget(self.delay_lbl, 4, 0)
        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(0, 45)
        self.delay_spin.setValue(0)
        layout.addWidget(self.delay_spin, 4, 1)

        self.delay_slider = QSlider(Qt.Orientation.Horizontal)
        self.delay_slider.setRange(0, 45)
        self.delay_slider.setValue(0)
        layout.addWidget(self.delay_slider, 5, 0, 1, 2)

        self.pw_spin.valueChanged.connect(self.pw_slider.setValue)
        self.pw_slider.valueChanged.connect(self.pw_spin.setValue)
        self.pw_spin.valueChanged.connect(lambda v: self.worker.send_command(f"w{v}"))

        self.freq_spin.valueChanged.connect(self.freq_slider.setValue)
        self.freq_slider.valueChanged.connect(self.freq_spin.setValue)
        self.freq_spin.valueChanged.connect(lambda v: self.worker.send_command(f"f{v}"))

        self.delay_spin.valueChanged.connect(self.delay_slider.setValue)
        self.delay_slider.valueChanged.connect(self.delay_spin.setValue)
        self.delay_spin.valueChanged.connect(lambda v: self.worker.send_command(f"a{v}"))

        self.set_cambox_widgets_visible(False)
        return box

    def create_action_panel(self):
        box = QGroupBox("ACTUATORS")
        layout = QHBoxLayout(box)
        layout.setSpacing(8)

        self.start_btn = QPushButton("START")
        self.start_btn.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        self.start_btn.setMinimumHeight(52)
        self.start_btn.setStyleSheet("""
            QPushButton { background-color: #2E7D32; color: white; border-radius: 5px; border: none; }
            QPushButton:hover { background-color: #388E3C; }
            QPushButton:pressed { background-color: #1B5E20; }
        """)
        self.start_btn.clicked.connect(lambda: self.worker.send_command("start"))

        self.stop_btn = QPushButton("STOP")
        self.stop_btn.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        self.stop_btn.setMinimumHeight(52)
        self.stop_btn.setStyleSheet("""
            QPushButton { background-color: #B71C1C; color: white; border-radius: 5px; border: none; }
            QPushButton:hover { background-color: #C62828; }
            QPushButton:pressed { background-color: #7F0000; }
        """)
        self.stop_btn.clicked.connect(lambda: self.worker.send_command("stop"))

        layout.addWidget(self.start_btn)
        layout.addWidget(self.stop_btn)
        return box

    def create_telemetry_panel(self):
        box = QGroupBox("TELEMETRY")
        layout = QHBoxLayout(box)
        layout.setSpacing(12)

        pressure_layout = QVBoxLayout()
        p_lbl = QLabel("PRESSURE (BAR)")
        p_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pressure_lcd = QLCDNumber()
        self.pressure_lcd.setDigitCount(5)
        self.pressure_lcd.setMinimumHeight(60)
        self.pressure_lcd.setStyleSheet("QLCDNumber { border: 1px solid #FF8F00; color: #FFA726; }")
        pressure_layout.addWidget(p_lbl)
        pressure_layout.addWidget(self.pressure_lcd)

        angle_layout = QVBoxLayout()
        a_lbl = QLabel("DELAY ANGLE (°)")
        a_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.angle_lcd = QLCDNumber()
        self.angle_lcd.setDigitCount(3)
        self.angle_lcd.setMinimumHeight(60)
        angle_layout.addWidget(a_lbl)
        angle_layout.addWidget(self.angle_lcd)

        layout.addLayout(pressure_layout)
        layout.addLayout(angle_layout)
        return box

    def create_graph_panel(self):
        box = QGroupBox("LIVE PRESSURE")
        layout = QVBoxLayout(box)

        self.graph = pg.PlotWidget()
        self.graph.setBackground('#0D0D0D')
        self.graph.showGrid(x=True, y=True, alpha=0.15)
        self.graph.setLabel('left', 'Bar', color='#555')
        self.graph.setLabel('bottom', 'Samples', color='#555')
        self.graph.getAxis('left').setTextPen('#555')
        self.graph.getAxis('bottom').setTextPen('#555')

        pen = pg.mkPen(color='#00ADB5', width=2)
        self.curve = self.graph.plot(self.x_data, self.pressure_data, pen=pen)

        layout.addWidget(self.graph)
        return box

    def refresh_ports(self):
        if not self.worker.is_running:
            ports = [p.device for p in serial.tools.list_ports.comports()]
            current = self.port_combo.currentText()
            self.port_combo.clear()
            self.port_combo.addItems(ports)
            if current in ports:
                self.port_combo.setCurrentText(current)

    def toggle_connection(self):
        if not self.worker.is_running:
            port = self.port_combo.currentText()
            baud = int(self.baud_combo.currentText())
            if port:
                self.worker.connect_device(port, baud)
            else:
                QMessageBox.warning(self, "No Port", "No COM ports found.")
        else:
            self.worker.disconnect_device()

    def update_connection_ui(self, connected):
        if connected:
            self.conn_btn.setText("DISCONNECT")
            self.conn_btn.setStyleSheet("QPushButton { background-color: #B71C1C; color: white; font-weight: bold; } QPushButton:hover { background-color: #C62828; }")
            self.status_lbl.setText("CONNECTED")
            self.status_lbl.setStyleSheet("color: #66BB6A; font-weight: bold; font-size: 11px;")
        else:
            self.conn_btn.setText("CONNECT")
            self.conn_btn.setStyleSheet("QPushButton { background-color: #0277BD; color: white; font-weight: bold; } QPushButton:hover { background-color: #0288D1; }")
            self.status_lbl.setText("DISCONNECTED")
            self.status_lbl.setStyleSheet("color: #EF5350; font-weight: bold; font-size: 11px;")

    def handle_mode_change(self, mode_id):
        self.worker.send_command("mode")
        self.set_cambox_widgets_visible(mode_id == 1)

    def set_cambox_widgets_visible(self, visible):
        self.freq_lbl.setVisible(not visible)
        self.freq_spin.setVisible(not visible)
        self.freq_slider.setVisible(not visible)
        self.delay_lbl.setVisible(visible)
        self.delay_spin.setVisible(visible)
        self.delay_slider.setVisible(visible)

    def parse_telemetry(self, data_str):
        if data_str.startswith("OK:") or data_str.startswith("ERR:"):
            logging.info(f"ESP32: {data_str}")
            return
        try:
            if "P:" in data_str:
                parts = data_str.split(',')
                p_val, a_val = 0.0, 0
                for part in parts:
                    if part.startswith("P:"):
                        p_val = float(part.split(':')[1])
                    elif part.startswith("A:"):
                        a_val = int(part.split(':')[1])
                self.pressure_lcd.display(p_val)
                self.angle_lcd.display(a_val)
                self.pressure_data.pop(0)
                self.pressure_data.append(p_val)
                self.curve.setData(self.x_data, self.pressure_data)
        except Exception as e:
            logging.warning(f"Parse error: {data_str} -> {e}")

    def handle_error(self, err_msg):
        QMessageBox.critical(self, "Communication Error", err_msg)

    def closeEvent(self, event):
        self.worker._keep_running = False
        self.worker.disconnect_device()
        self.serial_thread.quit()
        self.serial_thread.wait()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    dashboard = DieselDashboard()
    dashboard.show()
    sys.exit(app.exec())
