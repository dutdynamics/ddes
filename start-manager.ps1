# Launch the private editor with existing tools. No software is installed.
$ErrorActionPreference = 'Stop'
$ddesPort = 8765
$ddesUrl = "http://127.0.0.1:$ddesPort/manager.html"
try {
    $ddesStatus = Invoke-RestMethod -Uri "http://127.0.0.1:$ddesPort/api/status" -TimeoutSec 2
    if ($ddesStatus.service -eq 'ddes-manager') { Start-Process $ddesUrl; exit 0 }
    throw 'Port 8765 is used by another application.'
} catch {
    if ($_.Exception.Message -eq 'Port 8765 is used by another application.') { throw }
}
$ddesScript = Join-Path $PSScriptRoot 'scripts/manager_server.py'
if (-not (Test-Path -LiteralPath $ddesScript)) { throw 'Please download and extract the complete DDES repository first.' }
$ddesCandidates = @()
$ddesSystemPython = Get-Command python -ErrorAction SilentlyContinue
if ($ddesSystemPython -and $ddesSystemPython.Source -notlike '*WindowsApps*') { $ddesCandidates += $ddesSystemPython.Source }
$ddesCandidates += Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
$ddesPython = $null
foreach ($ddesCandidate in $ddesCandidates) {
    if (Test-Path -LiteralPath $ddesCandidate) {
        & $ddesCandidate -c 'import sys; assert sys.version_info >= (3, 11)' 2>$null
        if ($LASTEXITCODE -eq 0) { $ddesPython = $ddesCandidate; break }
    }
}
if (-not $ddesPython) { throw 'Python 3.11 or later is required. The Codex bundled Python is supported.' }
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { throw 'GitHub CLI (gh) was not found. Please use the existing GitHub login on this computer.' }
$ddesLog = Join-Path $env:TEMP 'ddes-manager.log'
$ddesErrorLog = Join-Path $env:TEMP 'ddes-manager-errors.log'
Start-Process -FilePath $ddesPython -ArgumentList @('-B', ('"' + $ddesScript + '"'), '--port', $ddesPort) -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput $ddesLog -RedirectStandardError $ddesErrorLog
for ($ddesAttempt = 0; $ddesAttempt -lt 20; $ddesAttempt++) {
    Start-Sleep -Milliseconds 250
    try {
        $ddesStatus = Invoke-RestMethod -Uri "http://127.0.0.1:$ddesPort/api/status" -TimeoutSec 2
        if ($ddesStatus.service -eq 'ddes-manager') { Start-Process $ddesUrl; exit 0 }
    } catch { }
}
throw "The assistant did not start. Check $ddesErrorLog."
