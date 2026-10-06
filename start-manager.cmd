@echo off
setlocal
if exist "%~dp0start-manager.ps1" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-manager.ps1"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "& { $ErrorActionPreference='Stop'; $ddesStamp=[Guid]::NewGuid().ToString('N'); $ddesZip=Join-Path $env:TEMP ('ddes-'+$ddesStamp+'.zip'); $ddesFolder=Join-Path $env:LOCALAPPDATA ('DDESManager/'+$ddesStamp); Invoke-WebRequest -Uri 'https://github.com/dutdynamics/ddes/archive/refs/heads/main.zip' -OutFile $ddesZip; Expand-Archive -LiteralPath $ddesZip -DestinationPath $ddesFolder; & (Join-Path $ddesFolder 'ddes-main/start-manager.ps1') }"
)
if errorlevel 1 pause
endlocal
