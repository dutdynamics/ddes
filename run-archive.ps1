# DDES background archive, 2026-10-08 (UTC+8). No browser or visible window.
param([Parameter(Mandatory=$true)][string]$PythonPath,
      [Parameter(Mandatory=$true)][string]$GitHubCli)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw 'The configured Python executable is missing.' }
if (-not (Test-Path -LiteralPath $GitHubCli -PathType Leaf)) { throw 'The configured GitHub CLI executable is missing.' }
$ddesArchiveScript = Join-Path $PSScriptRoot 'scripts/run_archive.py'
if (-not (Test-Path -LiteralPath $ddesArchiveScript -PathType Leaf)) { throw 'The DDES archive program is missing.' }
& $PythonPath -B $ddesArchiveScript --write --gh $GitHubCli
exit $LASTEXITCODE
