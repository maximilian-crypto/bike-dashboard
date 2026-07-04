# Richtet eine geplante Windows-Aufgabe ein, die den Sync automatisch
# in einem Intervall ausführt (auch mehrmals täglich).
#
# Beispiele (in PowerShell im Projektordner ausführen):
#   .\setup_task.ps1                       # alle 4 Stunden, ab 07:00
#   .\setup_task.ps1 -IntervalHours 2      # alle 2 Stunden
#   .\setup_task.ps1 -IntervalHours 6 -StartTime "06:30"
#
# Entfernen:  Unregister-ScheduledTask -TaskName "BikeDashboardSync" -Confirm:$false

param(
    [int]$IntervalHours = 4,
    [string]$StartTime = "07:00",
    [string]$TaskName = "BikeDashboardSync"
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$script = Join-Path $root "run_sync.ps1"

if ($IntervalHours -lt 1) { throw "IntervalHours muss >= 1 sein." }

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`""

$trigger = New-ScheduledTaskTrigger -Once -At $StartTime `
    -RepetitionInterval (New-TimeSpan -Hours $IntervalHours) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Description "Bike-Dashboard: Strava/Whoop automatisch syncen" -Force

Write-Host ""
Write-Host "OK - Aufgabe '$TaskName' eingerichtet: alle $IntervalHours h ab $StartTime." -ForegroundColor Green
Write-Host "Sofort testen:  Start-ScheduledTask -TaskName $TaskName"
Write-Host "Log:            data\sync.log"
