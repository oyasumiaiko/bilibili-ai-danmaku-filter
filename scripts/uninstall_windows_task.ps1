# Optional task cleanup, only for this GitHub repository's own task name.
$ErrorActionPreference='Stop'
$taskName='Bilibili AI Danmaku Filter (GitHub)'
$task=Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if(-not $task){Write-Output "Task is not installed: $taskName";exit 0}
$root=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$expected=Join-Path $root 'browser_filter\backend.py'
$actions=@($task.Actions)
if($actions.Count -ne 1 -or $actions[0].Arguments -notlike ('*'+$expected+'*')){
  throw "Task with this name points elsewhere; refusing to remove it."
}
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
Write-Output "Unregistered: $taskName"
