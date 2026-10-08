# Install only this user's DDES Thursday archive task, 2026-10-08 (UTC+8).
param([switch]$Remove)
$ErrorActionPreference = 'Stop'
$ddesTaskName = 'DDES-Seminar-Archive'
$ddesExisting = Get-ScheduledTask -TaskName $ddesTaskName -ErrorAction SilentlyContinue
if ($ddesExisting -and $ddesExisting.Description -notlike 'DDES seminar archive*') { throw 'An unrelated task uses the same name.' }
if ($Remove) {
    if ($ddesExisting) { Unregister-ScheduledTask -TaskName $ddesTaskName -Confirm:$false }
    exit 0
}
$ddesRunner = Join-Path $PSScriptRoot 'run-archive.ps1'
if (-not (Test-Path -LiteralPath $ddesRunner)) { throw 'Extract the complete DDES repository first.' }
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
if (-not $ddesPython) { throw 'Python 3.11 or later is required.' }
$ddesGh = Get-Command gh -ErrorAction SilentlyContinue
if (-not $ddesGh) { throw 'GitHub CLI was not found.' }
& $ddesGh.Source auth status --hostname github.com 1>$null 2>$null
if ($LASTEXITCODE -ne 0) { throw 'Run gh auth login --web using an account with repository write access.' }
foreach ($ddesPath in @($ddesRunner, $ddesPython, $ddesGh.Source)) {
    if ($ddesPath.Contains('"')) { throw 'Executable paths cannot contain quotes.' }
}
$ddesOffset = [TimeSpan]::FromHours(8)
$ddesNow = [DateTimeOffset]::UtcNow.ToOffset($ddesOffset)
$ddesDate = [DateTime]::SpecifyKind($ddesNow.Date.AddHours(10), [DateTimeKind]::Unspecified)
$ddesFirst = [DateTimeOffset]::new($ddesDate, $ddesOffset).AddDays((4 - [int]$ddesNow.DayOfWeek + 7) % 7)
if ($ddesFirst -le $ddesNow) { $ddesFirst = $ddesFirst.AddDays(7) }
$ddesTrigger = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek Thursday -At $ddesFirst.DateTime
$ddesTrigger.StartBoundary = $ddesFirst.ToString('yyyy-MM-ddTHH:mm:sszzz')
$ddesArguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $ddesRunner + '" -PythonPath "' + $ddesPython + '" -GitHubCli "' + $ddesGh.Source + '"'
$ddesAction = New-ScheduledTaskAction -Execute (Join-Path $PSHOME 'powershell.exe') -Argument $ddesArguments -WorkingDirectory $PSScriptRoot
$ddesUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$ddesPrincipal = New-ScheduledTaskPrincipal -UserId $ddesUser -LogonType Interactive -RunLevel Limited
$ddesSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 5)
$ddesTask = New-ScheduledTask -Action $ddesAction -Trigger $ddesTrigger -Principal $ddesPrincipal -Settings $ddesSettings -Description 'DDES seminar archive: Thursday 10:00 Beijing UTC+8; ended reports only; ordinary GitHub pull requests.'
Register-ScheduledTask -TaskName $ddesTaskName -InputObject $ddesTask -Force | Out-Null
Get-ScheduledTaskInfo -TaskName $ddesTaskName | Select-Object TaskName,NextRunTime,LastTaskResult
