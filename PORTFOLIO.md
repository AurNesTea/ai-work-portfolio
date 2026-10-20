# Portfolio one-pager

## One line

Local multi-agent CLI workbench: dispatch by role, observe usage, manage packs — without putting API keys in the repo.

## Proof points

1. Sequential workflows across Cursor / Claude / Codex / Gemini (Antigravity) CLIs
2. Role → agent/model mapping with pinned `resolved.json` per run
3. Panel for dispatch, roles/packs, and usage; automated tests included

## Not this project

- Not a cloud LLM router
- Not a RAG product (context is agent rules/skills/prompts, not a document index)

## How to demo

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q
python panel/scripts/snapshot_server.py --root .
cd panel; npm run dev
```
