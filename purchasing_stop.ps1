$ErrorActionPreference = 'Stop'
$expectedPython = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '.venv\Scripts\python.exe'))
$listeners = @(Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue)
foreach ($ownerId in ($listeners.OwningProcess | Sort-Object -Unique)) {
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $ownerId"
    if (-not $processInfo -or -not $processInfo.ExecutablePath -or
        -not [string]::Equals($processInfo.ExecutablePath, $expectedPython, [StringComparison]::OrdinalIgnoreCase) -or
        $processInfo.CommandLine -notmatch '(?<!\S)app\.purchasing\.web:app_from_env(?!\S)') {
        throw "Port 8765 belongs to a different process. Refusing to stop PID $ownerId."
    }
    Stop-Process -Id $ownerId -ErrorAction Stop
    Write-Output "Stopped purchasing review PID $ownerId."
}
