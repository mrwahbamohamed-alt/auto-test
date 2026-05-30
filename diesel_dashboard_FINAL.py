import sys
import time
import logging
from PyQt6.QtCore import QObject, pyqtSignal, QThread, Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QGroupBox, QLabel, QComboBox, QPushButton, QSlider,
    QSpinBox, QRadioButton, QButtonGroup, QLCDNumber, QLineEdit, QMessageBox
)
from PyQt6.QtGui import QFont
import serial
import serial.tools.list_ports
import pyqtgraph as pg

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

INDUSTRIAL_QSS = """
QMainWindow { background-color: #121212; }
QGroupBox {
    background-color: #1E1E1E; border: 2px solid #2D2D2D;
    border-radius: 8px; margin-top: 15px;
    font-size: 14px; font-weight: bold; color: #E0E0E0;
}
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 15px; padding: 0 5px; }
QLabel { color: #B0B0B0; font-size: 13px; }
QComboBox, QSpinBox, QLineEdit {
    background-color: #2A2A2A; border: 1px solid #404040;
    border-radius: 4px; padding: 5px; color: #FFFFFF; font-size: 13px;
}
QComboBox::drop-down { border: none; }
QSlider::groove:horizontal { border: 1px solid #444; height: 8px; background: #222; border-radius: 4px; }
QSlider::handle:horizontal {
    background: #00ADB5; border: 1px solid #00ADB5;
    width: 18px; margin: -5px 0; border-radius: 9px;
}
QPushButton {
    background-color: #3A3A3A; border: 1px solid #555;
    color: #FFFFFF; padding: 8px 15px; border-radius: 4px; font-weight: bold;
}
QPushButton:hover { background-color: #4A4A4A; }
QPushButton:pressed { background-color: #2A2A2A; }
QLCDNumber { background-color: #051A05; border: 2px solid #00FF00; border-radius: 4px; }
"""

class SerialWorker(QObject):
    data_received = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    connection_status = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self.serial_port = None
        self.is_running = False

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
        while True:
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
                logging.info(f"Sent command: {cmd}")
            except Exception as e:
                self.error_occurred.emit(f"Write error: {str(e)}")


class DieselDashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("INJECTOR PRO - Industrial Diesel Control Bench [ESP32]")
        self.resize(1280, 720)
        self.setStyleSheet(INDUSTRIAL_QSS)

        self.serial_thread = QThread()
        self.worker = SerialWorker()
        self.worker.moveToThread(self.serial_thread)

        self.serial_thread.started.connect(self.worker.read_loop)
        self.worker.data_received.connect(self.parse_telemetry)
        self.worker.error_occurred.connect(self.handle_error)
        self.worker.connection_status.connect(self.update_connection_ui)

        self.serial_thread.start()

        self.active_input_target = None
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

        left_panel = QVBoxLayout()
        left_panel.addWidget(self.create_connection_panel())
        left_panel.addWidget(self.create_mode_panel())
        left_panel.addWidget(self.create_control_panel())
        left_panel.addWidget(self.create_action_panel())

        center_panel = QVBoxLayout()
        center_panel.addWidget(self.create_telemetry_panel())
        center_panel.addWidget(self.create_graph_panel())

        right_panel = QVBoxLayout()
        right_panel.addWidget(self.create_virtual_keypad())

        main_layout.addLayout(left_panel, stretch=3)
        main_layout.addLayout(center_panel, stretch=5)
        main_layout.addLayout(right_panel, stretch=2)

    def create_connection_panel(self):
        box = QGroupBox("CONNECTION MANAGER")
        layout = QGridLayout(box)

        layout.addWidget(QLabel("Port/Device:"), 0, 0)
        self.port_combo = QComboBox()
        layout.addWidget(self.port_combo, 0, 1)

        layout.addWidget(QLabel("Baudrate:"), 1, 0)
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["115200", "9600", "57600"])
        layout.addWidget(self.baud_combo, 1, 1)

        self.conn_btn = QPushButton("CONNECT")
        self.conn_btn.setStyleSheet("background-color: #0288D1; color: white; font-size: 14px;")
        self.conn_btn.clicked.connect(self.toggle_connection)
        layout.addWidget(self.conn_btn, 2, 0, 1, 2)

        self.status_lbl = QLabel("STATUS: DISCONNECTED")
        self.status_lbl.setStyleSheet("color: #FF5252; font-weight: bold;")
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_lbl, 3, 0, 1, 2)

        return box

    def create_mode_panel(self):
        box = QGroupBox("OPERATION MODE Selection")
        layout = QHBoxLayout(box)

        self.mode_group = QButtonGroup(self)
        self.custom_mode_rb = QRadioButton("Custom Mode (Freq)")
        self.cambox_mode_rb = QRadioButton("CamBox Mode (Sync)")

        self.custom_mode_rb.setChecked(True)
        self.mode_group.addButton(self.custom_mode_rb, 0)
        self.mode_group.addButton(self.cambox_mode_rb, 1)

        layout.addWidget(self.custom_mode_rb)
        layout.addWidget(self.cambox_mode_rb)

        self.mode_group.idClicked.connect(self.handle_mode_change)
        return box

    def create_control_panel(self):
        box = QGroupBox("PARAMETER LIVE TUNING")
        layout = QGridLayout(box)

        layout.addWidget(QLabel("Pulse Width (us):"), 0, 0)
        self.pw_spin = QSpinBox()
        self.pw_spin.setRange(200, 3000)
        self.pw_spin.setValue(1000)
        self.pw_spin.setSingleStep(50)
        layout.addWidget(self.pw_spin, 0, 1)

        self.pw_slider = QSlider(Qt.Orientation.Horizontal)
        self.pw_slider.setRange(200, 3000)
        self.pw_slider.setValue(1000)
        layout.addWidget(self.pw_slider, 1, 0, 1, 2)

        self.freq_lbl = QLabel("Frequency (Hz):")
        layout.addWidget(self.freq_lbl, 2, 0)
        self.freq_spin = QSpinBox()
        self.freq_spin.setRange(1, 100)
        self.freq_spin.setValue(25)
        layout.addWidget(self.freq_spin, 2, 1)

        self.freq_slider = QSlider(Qt.Orientation.Horizontal)
        self.freq_slider.setRange(1, 100)
        self.freq_slider.setValue(25)
        layout.addWidget(self.freq_slider, 3, 0, 1, 2)

        self.delay_lbl = QLabel("Delay Angle (deg):")
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

        self.pw_spin.lineEdit().mousePressEvent = lambda e: self.set_keypad_target(self.pw_spin)
        self.delay_spin.lineEdit().mousePressEvent = lambda e: self.set_keypad_target(self.delay_spin)

        self.set_cambox_widgets_visible(False)
        return box

    def create_action_panel(self):
        box = QGroupBox("MAIN ACTUATORS")
        layout = QHBoxLayout(box)

        self.start_btn = QPushButton("START")
        self.start_btn.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        self.start_btn.setStyleSheet("""
            QPushButton { background-color: #2E7D32; color: white; min-height: 60px; border-radius: 6px; }
            QPushButton:hover { background-color: #388E3C; }
        """)
        self.start_btn.clicked.connect(lambda: self.worker.send_command("start"))

        self.stop_btn = QPushButton("STOP")
        self.stop_btn.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        self.stop_btn.setStyleSheet("""
            QPushButton { background-color: #C62828; color: white; min-height: 60px; border-radius: 6px; }
            QPushButton:hover { background-color: #D32F2F; }
        """)
        self.stop_btn.clicked.connect(lambda: self.worker.send_command("stop"))

        layout.addWidget(self.start_btn)
        layout.addWidget(self.stop_btn)
        return box

    def create_telemetry_panel(self):
        box = QGroupBox("REAL-TIME TELEMETRY")
        layout = QGridLayout(box)

        layout.addWidget(QLabel("FUEL PRESSURE (BAR)"), 0, 0, Qt.AlignmentFlag.AlignCenter)
        self.pressure_lcd = QLCDNumber()
        self.pressure_lcd.setDigitCount(4)
        self.pressure_lcd.setStyleSheet("QLCDNumber { border: 2px solid #FF9800; }")
        layout.addWidget(self.pressure_lcd, 1, 0)

        layout.addWidget(QLabel("ACTIVE DELAY ANGLE"), 0, 1, Qt.AlignmentFlag.AlignCenter)
        self.angle_lcd = QLCDNumber()
        self.angle_lcd.setDigitCount(2)
        layout.addWidget(self.angle_lcd, 1, 1)

        return box

    def create_graph_panel(self):
        box = QGroupBox("LIVE WAVEFORM MONITOR")
        layout = QVBoxLayout(box)

        self.graph = pg.PlotWidget()
        self.graph.setBackground('#1A1A1A')
        self.graph.showGrid(x=True, y=True, alpha=0.3)
        self.graph.setLabel('left', 'Pressure', units='Bar', color='#00ADB5')
        self.graph.setLabel('bottom', 'Time / Samples', color='#00ADB5')

        pen = pg.mkPen(color='#00ADB5', width=2)
        self.curve = self.graph.plot(self.x_data, self.pressure_data, pen=pen)

        layout.addWidget(self.graph)
        return box

    def create_virtual_keypad(self):
        box = QGroupBox("MEMBRANE KEYPAD")
        layout = QVBoxLayout(box)

        self.keypad_display = QLineEdit()
        self.keypad_display.setReadOnly(True)
        self.keypad_display.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.keypad_display.setFont(QFont("Consolas", 18, QFont.Weight.Bold))
        self.keypad_display.setStyleSheet("background-color: #000; color: #00FF00; padding: 8px;")
        layout.addWidget(self.keypad_display)

        grid = QGridLayout()
        buttons = ['7', '8', '9', '4', '5', '6', '1', '2', '3', 'C', '0', 'ENTER']
        pos = [(i, j) for i in range(4) for j in range(3)]

        for b_text, p in zip(buttons, pos):
            btn = QPushButton(b_text)
            btn.setMinimumSize(55, 55)
            btn.setFont(QFont("Arial", 12, QFont.Weight.Bold))
            if b_text == 'ENTER':
                btn.setStyleSheet("background-color: #00897B; color: white;")
            elif b_text == 'C':
                btn.setStyleSheet("background -color: #E53935; color: white;")
            else:
                btn.setStyleSheet("background-color: #263238; color: white; border: 1px solid #37474F;")
            btn.clicked.connect(self.handle_keypad_press)
            grid.addWidget(btn, p[0], p[1])

        layout.addLayout(grid)
        self.target_lbl = QLabel("Target: None (Click SpinBox)")
        self.target_lbl.setStyleSheet("color: #FFB300; font-style: italic;")
        layout.addWidget(self.target_lbl)
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
                QMessageBox.warning(self, "Port Error", "No COM Ports or Bluetooth Serial Devices found!")
        else:
            self.worker.disconnect_device()

    def update_connection_ui(self, connected):
        if connected:
            self.conn_btn.setText("DISCONNECT")
            self.conn_btn.setStyleSheet("background-color: #C62828; color: white;")
            self.status_lbl.setText("STATUS: CONNECTED")
            self.status_lbl.setStyleSheet("color: #4CAF50; font-weight: bold;")
        else:
            self.conn_btn.setText("CONNECT")
            self.conn_btn.setStyleSheet("background-color: #0288D1; color: white;")
            self.status_lbl.setText("STATUS: DISCONNECTED")
            self.status_lbl.setStyleSheet("color: #FF5252; font-weight: bold;")

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

    def set_keypad_target(self, spinbox_widget):
        self.active_input_target = spinbox_widget
        name = "Pulse Width" if spinbox_widget == self.pw_spin else "Delay Angle"
        self.target_lbl.setText(f"Target: [ {name} ]")
        self.keypad_display.clear()

    def handle_keypad_press(self):
        text = self.sender().text()
        if text == 'C':
            self.keypad_display.clear()
        elif text == 'ENTER':
            if self.active_input_target and self.keypad_display.text():
                val = int(self.keypad_display.text())
                clamped = max(self.active_input_target.minimum(),
                              min(val, self.active_input_target.maximum()))
                self.active_input_target.setValue(clamped)
                self.keypad_display.clear()
        else:
            if len(self.keypad_display.text()) < 5:
                self.keypad_display.setText(self.keypad_display.text() + text)

    def parse_telemetry(self, data_str):
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
        QMessageBox.critical(self, "Hardware Communication Error", f"An error occurred:\n{err_msg}")

    def closeEvent(self, event):
        self.worker.disconnect_device()
        self.serial_thread.quit()
        self.serial_thread.wait()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    dashboard = DieselDashboard()
    dashboard.show()
    sys.exit(app.exec())
