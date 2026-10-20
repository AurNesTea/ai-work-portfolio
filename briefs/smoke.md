# Brief: smoke

## Meta

| Field | Value |
|---|---|
| `task_id` | smoke |
| `preferred_agent` | cursor |
| `preferred_model` | composer-2 |
| `approval_required` | false |
| `mcp_profile` | default |

## Outcome

Prove aiwork can load a workflow and run two sequential fake/live steps.

## Acceptance

- [x] `aiwork run workflows/smoke.yaml` writes `runs/<id>/status.json`
- [x] `usage_events.jsonl` has one row per completed step

## Non-goals

- Real product work

## Constraints

- Use logged-in Cursor CLI for live smoke; unit tests use fakes
