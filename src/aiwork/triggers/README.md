# Triggers

## Cron / Task Scheduler

```powershell
aiwork run workflows/smoke.yaml --root .
# or
python -m aiwork.triggers.cron_run workflows/smoke.yaml
```

Windows: use Task Scheduler to run the above on a schedule. See `scripts/register-windows-task.ps1`.

## Slack

Not a built-in always-on bot. Pattern:

1. Webhook or Slack MCP receives a message.
2. Write/update `briefs/<task-id>.md` (+ workflow if needed).
3. Invoke `aiwork run workflows/<task-id>.yaml`.

Status remains `runs/*/status.json` / `aiwork status`.
