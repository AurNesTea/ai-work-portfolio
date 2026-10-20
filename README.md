# aiwork

Local orchestrator for agent CLIs (Cursor, Claude Code, Codex, Gemini / Antigravity).

**No model HTTP API and no API keys in this repository.** Each agent uses its own CLI login on the machine.

## What it is

A personal workbench to:

- run sequential workflows across multiple agent CLIs
- map **roles** → agent + model (`config/roles.yaml`)
- observe runs, usage, and account labels in a desktop/web panel
- manage role/rule/skill **packs** (upload, apply, probe) without putting secrets in git

## Quick start

```powershell
cd C:\path\to\ai-work
python -m pip install -e ".[dev]"
aiwork run workflows/smoke.yaml
aiwork status
aiwork usage
```

Panel (browser / Tauri):

```powershell
python panel/scripts/snapshot_server.py --root .
cd panel; npm install; npm run dev
```

## Portfolio notes

This public snapshot is sanitized for sharing:

- no `fyi.md` session diary
- no local usage SQLite / run artifacts
- host paths and org examples replaced with placeholders
- tests use mock org names only (e.g. `MockOrg`, `Acme Corp`)

## License / authorship

Personal side project. GitHub: see repository owner page.
