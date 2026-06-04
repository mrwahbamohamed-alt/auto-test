"""
build_auto_test.py
==================
All-in-one build script for "Auto Test" (Diesel Dashboard).

Steps
-----
1. Install / verify dependencies  (PyInstaller, Pillow, pyserial, pyqtgraph)
2. Create injector.ico             (downloads first; falls back to Pillow draw)
3. Compile with PyInstaller        (single .exe, no console, custom icon)
4. Copy Auto Test.exe to Desktop
5. Create / refresh Desktop shortcut with the embedded icon

Usage
-----
    python build_auto_test.py
"""

import os
import sys, io
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import sys
import math
import shutil
import struct
import subprocess
import importlib
import winreg
from pathlib import Path


# -- Paths -------------------------------------------------------------
HERE      = Path(__file__).resolve().parent
MAIN_PY   = HERE / "diesel_dashboard_FINAL.py"
ICON_PATH = HERE / "injector.ico"
DIST_EXE  = HERE / "dist" / "Auto Test.exe"
def _get_desktop() -> Path:
    """Return the real Desktop path (works with OneDrive Desktop Sync)."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as k:
            return Path(winreg.QueryValueEx(k, "Desktop")[0])
    except Exception:
        pass
    onedrive = Path(os.path.expandvars(r"%USERPROFILE%\OneDrive\Desktop"))
    if onedrive.exists():
        return onedrive
    return Path(os.path.expandvars(r"%USERPROFILE%\Desktop"))

DESKTOP   = _get_desktop()
DEST_EXE  = DESKTOP / "Auto Test.exe"
SHORTCUT  = DESKTOP / "Auto Test.lnk"
APP_NAME  = "Auto Test"


# ======================================================================
#  STEP 0 — helpers
# ======================================================================
def banner(msg: str):
    print(f"\n{'-'*56}")
    print(f"  {msg}")
    print(f"{'-'*56}")


def run(cmd: list[str], **kw):
    """Run a subprocess; raise on failure."""
    print("  $", " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True, **kw)


def pip_install(*packages: str):
    run([sys.executable, "-m", "pip", "install", "--upgrade", "--quiet", *packages])


def ensure(module: str, package: str | None = None):
    """Import module; install package if missing."""
    try:
        importlib.import_module(module)
    except ModuleNotFoundError:
        print(f"  Installing {package or module}…")
        pip_install(package or module)


# ======================================================================
#  STEP 1 — dependencies
# ======================================================================
def step_deps():
    banner("STEP 1 / 5  ·  Checking dependencies")
    ensure("PIL",         "pillow")
    ensure("serial",      "pyserial")
    ensure("pyqtgraph",   "pyqtgraph")
    ensure("PyInstaller", "pyinstaller")
    print("  [OK] All dependencies present.")


# ======================================================================
#  STEP 2 — icon
# ======================================================================

# -- Pillow-drawn injector icon ----------------------------------------
def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(len(a)))

def _draw_injector(size: int = 256):
    from PIL import Image, ImageDraw, ImageFilter

    BG         = (11,  13,  17)
    BORDER     = (44,  51,  71)
    METAL_HI   = (195, 205, 215)
    METAL_MID  = (130, 142, 158)
    METAL_LO   = ( 75,  85, 100)
    METAL_DK   = ( 50,  58,  72)
    NUT        = ( 85,  96, 112)
    CONNECTOR  = ( 60,  70,  85)
    PIN_GOLD   = (200, 170,  80)
    GREEN      = (  0, 230, 118)
    AMBER      = (255, 179,   0)

    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    s    = size / 256.0
    cx   = size // 2

    sc = lambda v: int(v * s)
    sx = lambda v: int(cx + v * s)
    sy = lambda v: int(v * s)

    # background
    draw.rounded_rectangle([0, 0, size-1, size-1], radius=sc(24),
                            fill=BG+(255,), outline=BORDER+(255,), width=max(1,sc(2)))

    # -- electrical connector cap (top) ----------------------------
    cw = sc(38); ch = sc(28)
    cx1, cx2 = sx(-cw//2), sx(cw//2)
    cy1, cy2 = sy(14),     sy(14+ch)
    draw.rounded_rectangle([cx1,cy1,cx2,cy2], radius=sc(5),
                            fill=CONNECTOR+(255,), outline=METAL_DK+(255,),
                            width=max(1,sc(1)))
    draw.line([(cx1+sc(4),cy1+sc(2)),(cx2-sc(4),cy1+sc(2))],
              fill=METAL_MID+(120,), width=max(1,sc(1)))
    for px in [-sc(8), 0, sc(8)]:
        draw.rectangle([sx(px)-sc(3),cy1+sc(4),sx(px)+sc(3),cy1+sc(14)],
                       fill=PIN_GOLD+(255,))

    # -- main body -------------------------------------------------
    bw = sc(54)
    bx1, bx2 = sx(-bw//2), sx(bw//2)
    by1, by2 = cy2-sc(4), sy(128)
    for xi in range(bx1, bx2+1):
        t_x   = (xi-bx1)/max(1,bx2-bx1)
        shine = math.exp(-((t_x-0.28)**2)/0.015)
        for yi in range(by1, by2+1):
            t_y   = (yi-by1)/max(1,by2-by1)
            base  = _lerp(METAL_HI, METAL_LO, t_y)
            col   = _lerp(base, METAL_HI, shine*0.55)
            draw.point((xi,yi), fill=col+(255,))
    draw.rounded_rectangle([bx1,by1,bx2,by2], radius=sc(4),
                            outline=METAL_DK+(255,), width=max(1,sc(1)))
    gy = sy(90)
    draw.rectangle([bx1,gy,bx2,gy+sc(5)], fill=METAL_DK+(255,))
    draw.line([(bx1,gy+sc(2)),(bx2,gy+sc(2))], fill=METAL_MID+(160,), width=max(1,sc(1)))

    # -- hex nut ---------------------------------------------------
    hw = sc(76)
    hx1, hx2 = sx(-hw//2), sx(hw//2)
    hy1, hy2 = sy(128),    sy(156)
    for xi in range(hx1, hx2+1):
        t_x   = (xi-hx1)/max(1,hx2-hx1)
        shine = math.exp(-((t_x-0.25)**2)/0.018)
        for yi in range(hy1, hy2+1):
            t_y = (yi-hy1)/max(1,hy2-hy1)
            base = _lerp(NUT, METAL_DK, t_y*0.6)
            col  = _lerp(base, METAL_HI, shine*0.4)
            draw.point((xi,yi), fill=col+(255,))
    draw.rectangle([hx1,hy1,hx2,hy2], outline=METAL_DK+(255,), width=max(1,sc(1)))
    for oy in [sc(4), hy2-hy1-sc(4)]:
        draw.line([(hx1+sc(6),hy1+oy),(hx2-sc(6),hy1+oy)],
                  fill=METAL_DK+(180,), width=max(1,sc(1)))
    draw.line([(hx1,hy1),(hx2,hy1)], fill=METAL_HI+(150,), width=max(1,sc(1)))

    # -- tapered nozzle body ---------------------------------------
    ntw, nbw = sc(50), sc(20)
    ny1, ny2 = hy2-sc(2), sy(214)
    for yi in range(ny1, ny2+1):
        t = (yi-ny1)/max(1,ny2-ny1)
        w = int((ntw+(nbw-ntw)*t)/2)
        col = _lerp(METAL_MID, METAL_LO, t)
        draw.line([(cx-w,yi),(cx+w,yi)], fill=col+(255,))
    draw.polygon([(cx-ntw//2,ny1),(cx+ntw//2,ny1),(cx+nbw//2,ny2),(cx-nbw//2,ny2)],
                 outline=METAL_DK+(255,))

    # tip
    tw = sc(16)
    draw.rectangle([cx-tw//2, ny2-sc(2), cx+tw//2, ny2+sc(12)],
                   fill=METAL_DK+(255,))

    # amber glow ring
    for r in range(sc(22), 0, -1):
        a = int(55*(r/sc(22))**2)
        draw.ellipse([cx-r, ny2+sc(12)-r//2, cx+r, ny2+sc(12)+r//2],
                     outline=AMBER+(a,), width=1)

    # -- spray lines -----------------------------------------------
    org_y = ny2 + sc(14)
    end_y = sy(252)
    length = end_y - org_y
    for angle_deg, alpha, lw in [(0,255,sc(2)),(-20,200,sc(2)),(20,200,sc(2)),
                                  (-42,100,sc(1)),(42,100,sc(1))]:
        ar = math.radians(angle_deg)
        for seg in range(4):
            t0, t1 = seg/4, (seg+1)/4
            sa = int(alpha*(1-t0*0.7))
            p0 = (cx+int(length*t0*math.sin(ar)), org_y+int(length*t0*math.cos(ar)))
            p1 = (cx+int(length*t1*math.sin(ar)), org_y+int(length*t1*math.cos(ar)))
            ov  = Image.new("RGBA",(size,size),(0,0,0,0))
            odw = ImageDraw.Draw(ov)
            odw.line([p0,p1], fill=GREEN+(sa,), width=lw)
            img = Image.alpha_composite(img, ov)
            draw = ImageDraw.Draw(img)

    # spray dot
    dr = sc(5)
    draw.ellipse([cx-dr,org_y-dr,cx+dr,org_y+dr], fill=GREEN+(200,))
    draw.ellipse([cx-sc(2),org_y-sc(2),cx+sc(2),org_y+sc(2)], fill=(255,255,255,240))

    # glow overlay
    glow  = Image.new("RGBA",(size,size),(0,0,0,0))
    gdraw = ImageDraw.Draw(glow)
    gr    = sc(48)
    gdraw.ellipse([cx-gr,org_y-gr//2,cx+gr,org_y+gr], fill=GREEN+(22,))
    glow  = glow.filter(ImageFilter.GaussianBlur(sc(12)))
    img   = Image.alpha_composite(img, glow)

    return img


def _save_ico(img, path: Path):
    from PIL import Image, ImageEnhance
    sizes  = [256, 128, 64, 48, 32, 16]
    frames = []
    base   = img.resize((256,256), Image.LANCZOS) if img.size != (256,256) else img
    for sz in sizes:
        f = base if sz == 256 else base.resize((sz,sz), Image.LANCZOS)
        if sz <= 32:
            f = ImageEnhance.Contrast(f).enhance(1.25)
            f = ImageEnhance.Sharpness(f).enhance(1.4)
        frames.append(f)
    frames[0].save(str(path), format="ICO",
                   sizes=[(sz,sz) for sz in sizes],
                   append_images=frames[1:])


def step_icon():
    banner("STEP 2 / 5  ·  Creating injector.ico")
    print("  Drawing diesel injector icon with Pillow...")
    img = _draw_injector(256)
    _save_ico(img, ICON_PATH)
    print(f"  [OK] Generated: {ICON_PATH}")


# ======================================================================
#  STEP 3 — PyInstaller
# ======================================================================
def step_build():
    banner("STEP 3 / 5  ·  Compiling with PyInstaller")

    if not MAIN_PY.exists():
        sys.exit(f"  ERROR: {MAIN_PY} not found.")

    # wipe previous build artefacts
    for folder in [HERE / "dist", HERE / "build"]:
        if folder.exists():
            shutil.rmtree(folder)
            print(f"  Removed {folder.name}/")

    spec_file = HERE / "auto_test.spec"
    if spec_file.exists():
        # use the existing spec (has hiddenimports etc.)
        cmd = [
            sys.executable, "-m", "PyInstaller",
            str(spec_file),
            "--clean", "--noconfirm",
        ]
    else:
        # fallback: direct invocation with all needed flags
        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--onefile",
            "--noconsole",
            f"--name={APP_NAME}",
            f"--icon={ICON_PATH}",
            "--hidden-import=PyQt6.QtCore",
            "--hidden-import=PyQt6.QtGui",
            "--hidden-import=PyQt6.QtWidgets",
            "--hidden-import=PyQt6.sip",
            "--hidden-import=pyqtgraph",
            "--hidden-import=serial",
            "--hidden-import=serial.tools.list_ports",
            "--hidden-import=serial.tools.list_ports_windows",
            "--noconfirm",
            str(MAIN_PY),
        ]

    run(cmd, cwd=HERE)

    if not DIST_EXE.exists():
        sys.exit(f"\n  ERROR: Build failed — {DIST_EXE} not found.\n"
                 "  Check PyInstaller output above for details.")
    print(f"\n  [OK] Built: {DIST_EXE}  "
          f"({DIST_EXE.stat().st_size / 1_048_576:.1f} MB)")


# ======================================================================
#  STEP 4 — copy to Desktop
# ======================================================================
def step_copy():
    banner("STEP 4 / 5  ·  Copying to Desktop")
    DESKTOP.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DIST_EXE, DEST_EXE)
    print(f"  [OK] {DEST_EXE}  ({DEST_EXE.stat().st_size / 1_048_576:.1f} MB)")


# ======================================================================
#  STEP 5 — Desktop shortcut  (pure-Python, no COM / PowerShell)
# ======================================================================
#  Windows .lnk format — minimal implementation
#  Reference: MS-SHLLINK specification §2
# ----------------------------------------------------------------------
def _write_lnk(lnk_path: Path, target: Path, working_dir: Path,
               icon_path: Path, description: str = ""):
    """
    Write a minimal Windows Shell Link (.lnk) file.
    Supports: LocalPath target, working directory, icon, description.
    """
    CLSID_SHELL_LINK = b'\x01\x14\x02\x00\x00\x00\x00\x00\xc0\x00\x00\x00\x00\x00\x00\x46'

    def wstr(s: str) -> bytes:
        """UTF-16LE prefixed with uint16 char-count (not byte-count)."""
        enc = s.encode("utf-16-le")
        return struct.pack("<H", len(s)) + enc

    def pack_u16(v: int) -> bytes: return struct.pack("<H", v)
    def pack_u32(v: int) -> bytes: return struct.pack("<I", v)

    # -- LinkFlags ----------------------------------------------------
    # HasLinkTargetIDList=0, HasLinkInfo=1, HasName=0(unused),
    # HasRelativePath=0, HasWorkingDir=1, HasArguments=0,
    # HasIconLocation=1, IsUnicode=1, ForceNoLinkInfo=0
    HAS_LINK_INFO        = 1 << 1
    HAS_WORKING_DIR      = 1 << 4
    HAS_ICON_LOCATION    = 1 << 6
    IS_UNICODE           = 1 << 7
    HAS_EXP_STRING       = 1 << 8
    link_flags = HAS_LINK_INFO | HAS_WORKING_DIR | HAS_ICON_LOCATION | IS_UNICODE

    if description:
        HAS_NAME = 1 << 2
        link_flags |= HAS_NAME

    # -- FileAttributes -----------------------------------------------
    file_attrs = 0x20  # FILE_ATTRIBUTE_ARCHIVE

    # -- ShellLinkHeader (76 bytes) ------------------------------------
    header = (
        pack_u32(76)                # HeaderSize
        + CLSID_SHELL_LINK          # LinkCLSID
        + pack_u32(link_flags)      # LinkFlags
        + pack_u32(file_attrs)      # FileAttributes
        + b'\x00' * 8               # CreationTime
        + b'\x00' * 8               # AccessTime
        + b'\x00' * 8               # WriteTime
        + pack_u32(0)               # FileSize
        + pack_u32(0)               # IconIndex
        + pack_u32(1)               # ShowCommand = SW_NORMAL
        + pack_u16(0)               # HotKey
        + pack_u16(0)               # Reserved1
        + pack_u32(0)               # Reserved2
        + pack_u32(0)               # Reserved3
    )
    assert len(header) == 76

    # -- LinkInfo (VolumeID + LocalBasePath) ---------------------------
    target_str   = str(target)
    local_path_b = target_str.encode("ascii", errors="replace") + b'\x00'
    working_b    = str(working_dir).encode("ascii", errors="replace") + b'\x00'

    LINK_INFO_FLAGS = 0x01  # VolumeIDAndLocalBasePath
    volume_id_size  = 16
    local_base_off  = 28
    link_info_size  = local_base_off + len(local_path_b)
    link_info_size  = (link_info_size + 3) & ~3  # align 4

    link_info = (
        pack_u32(link_info_size)
        + pack_u32(28)              # LinkInfoHeaderSize
        + pack_u32(LINK_INFO_FLAGS)
        + pack_u32(28)              # VolumeIDOffset (right after header)
        + pack_u32(local_base_off)  # LocalBasePathOffset
        + pack_u32(0)               # CommonNetworkRelativeLinkOffset (none)
        + pack_u32(0)               # CommonPathSuffixOffset
    )
    # Minimal VolumeID block (16 bytes)
    volume_id = (
        pack_u32(16)       # VolumeIDSize
        + pack_u32(3)      # DriveType = DRIVE_FIXED
        + pack_u32(0)      # DriveSerialNumber
        + pack_u32(16)     # VolumeLabelOffset (past struct = empty string)
    )
    link_info += volume_id + local_path_b
    # pad to link_info_size
    link_info += b'\x00' * (link_info_size - len(link_info))

    # -- StringData ----------------------------------------------------
    string_data = b''
    if description:
        string_data += wstr(description)      # NAME_STRING (only if HAS_NAME)
    string_data += wstr(str(working_dir))     # WORKING_DIR
    string_data += wstr(str(icon_path))       # ICON_LOCATION

    lnk_path.write_bytes(header + link_info + string_data)


def step_shortcut():
    banner("STEP 5 / 5  ·  Creating Desktop shortcut")

    # Try the COM approach first (most reliable on Windows)
    _shortcut_com()

    if SHORTCUT.exists():
        print(f"  [OK] Shortcut: {SHORTCUT}")
    else:
        print("  WARNING: shortcut not created — run as administrator or check permissions.")


def _shortcut_com():
    """Create shortcut via Windows Script Host COM object (most reliable)."""
    import ctypes, ctypes.wintypes

    # Load OLE / COM
    try:
        import win32com.client  # type: ignore  (pywin32)
        shell     = win32com.client.Dispatch("WScript.Shell")
        shortcut  = shell.CreateShortcut(str(SHORTCUT))
        shortcut.TargetPath       = str(DEST_EXE)
        shortcut.WorkingDirectory = str(DESKTOP)
        shortcut.IconLocation     = f"{DEST_EXE},0"
        shortcut.Description      = "Injector Pro — Diesel Injection Test System"
        shortcut.Save()
        print("  [OK] Shortcut created via win32com.")
        return
    except ImportError:
        pass

    # Fallback: PowerShell one-liner
    try:
        ps_cmd = (
            f'$s=(New-Object -COM WScript.Shell).CreateShortcut("{SHORTCUT}");'
            f'$s.TargetPath="{DEST_EXE}";'
            f'$s.WorkingDirectory="{DESKTOP}";'
            f'$s.IconLocation="{DEST_EXE},0";'
            f'$s.Description="Injector Pro";'
            f'$s.Save()'
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            check=True, capture_output=True
        )
        print("  [OK] Shortcut created via PowerShell.")
        return
    except Exception as e:
        print(f"  PowerShell shortcut failed: {e}")

    # Last resort: pure-Python .lnk writer
    try:
        _write_lnk(SHORTCUT, DEST_EXE, DESKTOP, DEST_EXE,
                   "Injector Pro — Diesel Injection Test System")
        print("  [OK] Shortcut created via built-in .lnk writer.")
    except Exception as e:
        print(f"  Built-in writer failed: {e}")


# ======================================================================
#  MAIN
# ======================================================================
def main():
    print()
    print("=" * 56)
    print("  AUTO TEST  --  Build & Package Script")
    print("  Diesel Injection Test System")
    print("=" * 56)

    if sys.platform != "win32":
        sys.exit("ERROR: This script is Windows-only (.exe target).")

    step_deps()
    step_icon()
    step_build()
    step_copy()
    step_shortcut()

    size_mb = DEST_EXE.stat().st_size / 1_048_576
    print()
    print("=" * 56)
    print("  BUILD COMPLETE")
    print(f"  EXE  : {DEST_EXE}")
    print(f"  Size : {size_mb:.1f} MB")
    print("  Icon : injector.ico  (embedded + shortcut)")
    print("=" * 56)
    print()
    input("Press Enter to exit…")


if __name__ == "__main__":
    main()

