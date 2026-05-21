param(
    [string]$Port = "COM13",
    [int]$BaudRate = 115200
)

$ErrorActionPreference = "Stop"

$serial = [System.IO.Ports.SerialPort]::new(
    $Port,
    $BaudRate,
    [System.IO.Ports.Parity]::None,
    8,
    [System.IO.Ports.StopBits]::One
)

$serial.DtrEnable = $false
$serial.RtsEnable = $false
$serial.ReadTimeout = 250
$serial.WriteTimeout = 250

try {
    $serial.Open()
    Write-Output "Connected to $Port at $BaudRate. Reading ESP32 serial logs..."

    while ($true) {
        $text = $serial.ReadExisting()
        if ($text.Length -gt 0) {
            [Console]::Write($text)
        }
        Start-Sleep -Milliseconds 50
    }
}
finally {
    if ($serial -and $serial.IsOpen) {
        $serial.Close()
    }
}
