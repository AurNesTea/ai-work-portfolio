# Brief: dispatch-smoke

## Meta

| Field | Value |
|---|---|
| `task_id` | dispatch-smoke |
| `trigger` | manual |
| `approval_required` | true |
| `mcp_profile` | default |

## Outcome

Prove aiwork can load a workflow using roles (builder -> agy, writer -> cursor), resolve models from roles table, pin them into resolved.json, pause for approval on step 2, and record dispatch_role in usage events.

## Acceptance

- [x] `aiwork run workflows/dispatch-smoke.yaml` writes `runs/<id>/resolved.json`
- [x] Step 1 resolves to role builder and step 2 to role writer
- [x] Step 2 pauses with `awaiting_approval`
- [x] Resuming keeps pinned models, `--re-resolve` updates uncompleted steps

## Constraints

- No codex references
- Do not modify existing `workflows/smoke.yaml`
