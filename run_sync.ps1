# Holt neue Daten von Strava + Whoop. Wird von der geplanten Aufgabe aufgerufen.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $root ".venv\Scripts\python.exe"
$dataDir = Join-Path $root "data"
if (-not (Test-Path $dataDir)) { New-Item -ItemType Directory -Path $dataDir | Out-Null }
Set-Location $root
& $py "sync.py" | Out-File -FilePath (Join-Path $dataDir "sync.log") -Append -Encoding utf8
