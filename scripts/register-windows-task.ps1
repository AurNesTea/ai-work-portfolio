# Example scheduled task (edit paths)
$Action = New-ScheduledTaskAction -Execute "aiwork" -Argument "run workflows/smoke.yaml --root C:/path/to/ai-work" -WorkingDirectory "C:/path/to/ai-work"
$Trigger = New-ScheduledTaskTrigger -Daily -At 9am
Register-ScheduledTask -TaskName "aiwork-smoke" -Action $Action -Trigger $Trigger
