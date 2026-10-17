# Optional per-user Windows logon task. Does not change the currently running service.
$ErrorActionPreference='Stop'
$root=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$pythonw=Join-Path $root '.venv\Scripts\pythonw.exe'
$backend=Join-Path $root 'browser_filter\backend.py'
$taskName='Bilibili AI Danmaku Filter (GitHub)'
if(-not (Test-Path -LiteralPath $pythonw)){ throw "Install the local .venv first: $pythonw" }
if(-not (Test-Path -LiteralPath $backend)){ throw "Missing backend: $backend" }
if(Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue){
  throw "Task already exists: $taskName. Nothing changed."
}
$user=[System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action=New-ScheduledTaskAction -Execute $pythonw -Argument ('"'+$backend+'"') -WorkingDirectory $root
$trigger=New-ScheduledTaskTrigger -AtLogOn -User $user
$principal=New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings | Out-Null
Write-Output "Registered local task: $taskName"
Write-Output "To start it immediately: Start-ScheduledTask -TaskName '$taskName'"
Write-Output "Make sure port 39683 is free before starting."
