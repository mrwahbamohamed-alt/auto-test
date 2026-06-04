# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — Auto Test (Diesel Dashboard)

block_cipher = None

a = Analysis(
    ['diesel_dashboard_FINAL.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        # PyQt6
        'PyQt6',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PyQt6.QtPrintSupport',
        'PyQt6.sip',
        # datetime (used for PDF report timestamps)
        'datetime',
        # pyqtgraph
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
        # pyserial
        'serial',
        'serial.tools',
        'serial.tools.list_ports',
        'serial.tools.list_ports_common',
        'serial.tools.list_ports_windows',
        # stdlib
        'collections',
        'logging',
        'socket',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy.distutils',
        'IPython',
        'notebook',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
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
    name='Auto Test',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='injector.ico',
)
