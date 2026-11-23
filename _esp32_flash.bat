@echo off
setlocal enabledelayedexpansion
set "ROOT=C:\Users\LAPIX\OneDrive\Desktop\Diesel Dashboard"
set "LOG=%ROOT%\_esp32_flash_log.txt"
set "SKETCH=%ROOT%\ESP32_Injector_Final"
set "CLI=%LOCALAPPDATA%\Programs\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe"

echo ==== ESP32 FLASH %DATE% %TIME% ==== > "%LOG%"
echo ---- BOARD LIST ---- >> "%LOG%"
"%CLI%" board list >> "%LOG%" 2>&1
echo. >> "%LOG%"
echo ---- COMPILE + UPLOAD (port COM3) ---- >> "%LOG%"
"%CLI%" compile --upload -p COM3 --fqbn esp32:esp32:esp32 "%SKETCH%" >> "%LOG%" 2>&1
echo. >> "%LOG%"
echo ==== EXIT CODE !ERRORLEVEL! ==== >> "%LOG%"
echo ==== FINISHED %TIME% ==== >> "%LOG%"
