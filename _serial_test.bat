@echo off
set "ROOT=C:\Users\LAPIX\OneDrive\Desktop\Diesel Dashboard"
set "LOG=%ROOT%\_serial_log.txt"
echo ==== SERIAL TEST %DATE% %TIME% ==== > "%LOG%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\_serial_capture.ps1" >> "%LOG%" 2>&1
echo ==== FINISHED %TIME% ==== >> "%LOG%"
