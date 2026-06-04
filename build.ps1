# ================================================================
#  build.ps1 — Build "Auto Test.exe" and place it on the Desktop
#  Run from: C:\Users\LAPIX\OneDrive\Desktop\Diesel Dashboard
#  Usage:    Right-click → Run with PowerShell
#            OR in terminal: .\build.ps1
# ================================================================

$ErrorActionPreference = "Stop"
$ProjectDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$Desktop      = [Environment]::GetFolderPath('Desktop')
$ExeName      = "Auto Test"
$ExePath      = "$ProjectDir\dist\$ExeName.exe"
$DestExe      = "$Desktop\$ExeName.exe"
$ShortcutPath = "$Desktop\$ExeName.lnk"
$IcoPath      = "$ProjectDir\injector.ico"

Write-Host ""
Write-Host "=======================================" -ForegroundColor Cyan
Write-Host "  Auto Test — Build Script" -ForegroundColor Cyan
Write-Host "=======================================" -ForegroundColor Cyan
Write-Host ""

# ── 1. Check Python ───────────────────────────────────────────
Write-Host "[1/6] Checking Python..." -ForegroundColor Yellow
try {
    $pyVer = python --version 2>&1
    Write-Host "      Found: $pyVer" -ForegroundColor Green
} catch {
    Write-Host "ERROR: Python not found. Install Python 3.10+ and try again." -ForegroundColor Red
    pause; exit 1
}

# ── 2. Install dependencies ───────────────────────────────────
Write-Host "[2/6] Installing dependencies (PyInstaller, Pillow)..." -ForegroundColor Yellow
pip install --upgrade pyinstaller pillow | Out-Null
Write-Host "      Dependencies ready." -ForegroundColor Green

# ── 3. Generate icon ──────────────────────────────────────────
Write-Host "[3/6] Generating injector.ico..." -ForegroundColor Yellow
Set-Location $ProjectDir
python create_icon.py injector.ico
if (-not (Test-Path $IcoPath)) {
    Write-Host "ERROR: Icon generation failed — injector.ico not found." -ForegroundColor Red
    pause; exit 1
}
Write-Host "      Icon ready: $IcoPath" -ForegroundColor Green

# ── 4. Clean previous build ───────────────────────────────────
Write-Host "[4/6] Cleaning previous build..." -ForegroundColor Yellow
if (Test-Path "$ProjectDir\dist")  { Remove-Item "$ProjectDir\dist"  -Recurse -Force }
if (Test-Path "$ProjectDir\build") { Remove-Item "$ProjectDir\build" -Recurse -Force }
Write-Host "      Clean done." -ForegroundColor Green

# ── 5. Build with PyInstaller ─────────────────────────────────
Write-Host "[5/6] Building executable (1-3 minutes)..." -ForegroundColor Yellow
pyinstaller auto_test.spec --clean --noconfirm

if (-not (Test-Path $ExePath)) {
    Write-Host "ERROR: Build failed — 'Auto Test.exe' not found in dist\." -ForegroundColor Red
    Write-Host "       Check the output above for errors." -ForegroundColor Red
    pause; exit 1
}
Write-Host "      Build successful!" -ForegroundColor Green

# ── 6. Copy to Desktop + shortcut ─────────────────────────────
Write-Host "[6/6] Copying to Desktop and creating shortcut..." -ForegroundColor Yellow

Copy-Item $ExePath -Destination $DestExe -Force
Write-Host "      Copied: $DestExe" -ForegroundColor Green

# Create .lnk shortcut — icon comes from the exe itself (embedded)
$WsShell  = New-Object -ComObject WScript.Shell
$Shortcut = $WsShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath       = $DestExe
$Shortcut.WorkingDirectory = $Desktop
$Shortcut.IconLocation     = "$DestExe,0"   # use the injector icon embedded in the exe
$Shortcut.Description      = "Injector Pro — Diesel Injection Test System"
$Shortcut.Save()
Write-Host "      Shortcut created: $ShortcutPath" -ForegroundColor Green

# ── Done ──────────────────────────────────────────────────────
$sizeMB = [math]::Round((Get-Item $DestExe).Length / 1MB, 1)
Write-Host ""
Write-Host "=======================================" -ForegroundColor Cyan
Write-Host "  DONE!  'Auto Test.exe' is ready." -ForegroundColor Green
Write-Host "  Location : $DestExe" -ForegroundColor Green
Write-Host "  Size     : $sizeMB MB" -ForegroundColor Green
Write-Host "  Icon     : injector.ico (embedded)" -ForegroundColor Green
Write-Host "=======================================" -ForegroundColor Cyan
Write-Host ""

pause
