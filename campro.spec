# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — CAM PRO (Diesel Dashboard)

block_cipher = None

a = Analysis(
    ['diesel_dashboard_FINAL.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('injector_db.json', '.'),   # database bundled next to exe
        ('campro.ico',       '.'),   # icon
    ],
    hiddenimports=[
        'PyQt6',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PyQt6.QtPrintSupport',
        'PyQt6.sip',
        'pyqtgraph',
        'pyqtgraph.graphicsItems',
        'pyqtgraph.graphicsItems.PlotItem',
        'pyqtgraph.graphicsItems.ViewBox',
        'pyqtgraph.graphicsItems.AxisItem',
        'pyqtgraph.graphicsItems.PlotCurveItem',
        'pyqtgraph.graphicsItems.GraphicsLayout',
        'pyqtgraph.widgets',
        'pyqtgraph.widgets.GraphicsLayoutWidget',
        'pyqtgraph.Qt',
        'pyqtgraph.Qt.QtCore',
        'pyqtgraph.Qt.QtGui',
        'pyqtgraph.Qt.QtWidgets',
        'serial',
        'serial.tools',
        'serial.tools.list_ports',
        'serial.tools.list_ports_common',
        'serial.tools.list_ports_windows',
        'datetime', 'json', 'csv', 'pathlib', 'collections',
        'logging', 'socket', 'uuid', 'os',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy.distutils', 'IPython'],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='CAM PRO',
    debug=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    icon='campro.ico',
)
