# Richtet eine geplante Windows-Aufgabe ein, die jeden Morgen den
# Trainings-Report aufs Handy schickt (via ntfy).
#
# Beispiele (in PowerShell im Projektordner):
#   .\setup_report_task.ps1                  # täglich 06:30 Uhr
#   .\setup_report_task.ps1 -At "07:15"
#
# Entfernen:  Unregister-ScheduledTask -TaskName "BikeDashboardReport" -Confirm:$false

param(
    [string]$At = "06:30",
    [string]$TaskName = "BikeDashboardReport"
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $root ".venv\Scripts\python.exe"
$script = Join-Path $root "send_report.py"

$action = New-ScheduledTaskAction -Execute $py `
    -Argument "`"$script`"" -WorkingDirectory $root

$trigger = New-ScheduledTaskTrigger -Daily -At $At

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Description "Bike-Dashboard: täglicher Morgen-Report" -Force

Write-Host ""
Write-Host "OK - Aufgabe '$TaskName' eingerichtet: täglich um $At." -ForegroundColor Green
Write-Host "Sofort testen:  python send_report.py"
