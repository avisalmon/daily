# Run today's digest.
param([switch]$DryRun)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$pyArgs = @("-m", "dailydigest")
if ($DryRun) { $pyArgs += "--dry-run" }
& .\.venv\Scripts\python.exe @pyArgs
