@echo off
setlocal enabledelayedexpansion
set "ROOT=C:\Users\LAPIX\OneDrive\Desktop\Diesel Dashboard"
set "LOG=%ROOT%\_esp32_build_log.txt"
set "SKETCH=%ROOT%\ESP32_Injector_Final"

echo ==== ESP32 BUILD %DATE% %TIME% ==== > "%LOG%"

set "CLI="
where arduino-cli >nul 2>&1 && set "CLI=arduino-cli"

if not defined CLI if exist "%LOCALAPPDATA%\Programs\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe" set "CLI=%LOCALAPPDATA%\Programs\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe"

if not defined CLI (
  for /f "delims=" %%F in ('dir /b /s "%LOCALAPPDATA%\arduino-cli.exe" 2^>nul') do set "CLI=%%F"
)
if not defined CLI (
  echo arduino-cli NOT FOUND on PATH or in Arduino IDE. >> "%LOG%"
  echo Searching common locations... >> "%LOG%"
  dir /b /s "%LOCALAPPDATA%\Programs\Arduino IDE\arduino-cli.exe" >> "%LOG%" 2>&1
  dir /b /s "%LOCALAPPDATA%\Programs\Arduino IDE\resources\arduino-cli.exe" >> "%LOG%" 2>&1
  dir /b /s "%USERPROFILE%\.vscode\extensions\*arduino*\assets\platform\win32\arduino-cli.exe" >> "%LOG%" 2>&1
  echo ==== SEARCH DONE ==== >> "%LOG%"
  goto :end
)

echo Using CLI: !CLI! >> "%LOG%"
"!CLI!" version >> "%LOG%" 2>&1
echo. >> "%LOG%"
echo ---- COMPILE (fqbn esp32:esp32:esp32) ---- >> "%LOG%"
"!CLI!" compile --fqbn esp32:esp32:esp32 "%SKETCH%" >> "%LOG%" 2>&1
echo. >> "%LOG%"
echo ==== EXIT CODE !ERRORLEVEL! ==== >> "%LOG%"

:end
echo ==== FINISHED %TIME% ==== >> "%LOG%"
