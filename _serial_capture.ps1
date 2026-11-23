$ErrorActionPreference = "Continue"
try {
    $port = New-Object System.IO.Ports.SerialPort "COM3",115200,None,8,one
    $port.ReadTimeout = 1500
    $port.NewLine = "`n"
    $port.DtrEnable = $true
    $port.RtsEnable = $true
    $port.Open()
    # Opening the port toggles DTR/RTS -> ESP32 auto-resets. Wait for boot.
    Start-Sleep -Milliseconds 1800
    # Ask the firmware to identify itself.
    $port.WriteLine("STATUS")
    $count = 0
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt 7 -and $count -lt 90) {
        try {
            $line = $port.ReadLine()
            Write-Output $line
            $count++
        } catch { }
    }
    $port.Close()
    Write-Output "==== CAPTURE DONE (lines=$count) ===="
} catch {
    Write-Output ("ERROR: " + $_.Exception.Message)
}
