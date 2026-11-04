$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw 'Run purchasing_install.bat first.' }
$originalPassword = $env:PURCHASING_REVIEW_PASSWORD
$pointer = [IntPtr]::Zero
try {
    if (-not $env:PURCHASING_REVIEW_PASSWORD) {
        $securePassword = Read-Host 'Choose a local review password (8 or more characters)' -AsSecureString
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
        $env:PURCHASING_REVIEW_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    if ($env:PURCHASING_REVIEW_PASSWORD.Length -lt 8) { throw 'Password must have at least 8 characters.' }
    Write-Output 'Open http://127.0.0.1:8765 in Chrome. Default username: reviewer. Press Ctrl+C to stop.'
    & $python -m uvicorn app.purchasing.web:app_from_env --factory --host 127.0.0.1 --port 8765
    if ($LASTEXITCODE -ne 0) { throw "Review server exited with code $LASTEXITCODE" }
} finally {
    $env:PURCHASING_REVIEW_PASSWORD = $originalPassword
    if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
}
