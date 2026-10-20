# P5 Read-only Panel Implementation Plan

> **For agentic workers:** Execute task-by-task. Spec: `docs/superpowers/specs/2026-09-21-aiwork-panel-p5-readonly.md`

**Goal:** Ship a Tauri 2 + React panel under `panel/` that read-only observes `runs/` status and usage, with a swappable playful progress skin.

**Architecture:** Rust commands read JSON/JSONL from a chosen repo root; React polls `get_snapshot`; skin maps run state → board positions. No writes, no CLI spawn.

---

### Task 1: Spec + this plan

- [x] Spec at `docs/superpowers/specs/2026-09-21-aiwork-panel-p5-readonly.md`
- [x] This plan file

---

### Task 2: Scaffold `panel/`

- [x] Create Tauri 2 + Vite + React + TS app in `panel/`
- [x] `.gitignore`: `panel/src-tauri/target`, `panel/node_modules`, `panel/dist`
- [x] App title: `aiwork panel`

---

### Task 3: Rust read commands

- [x] `get_repo_root` / `set_repo_root` (persist via localStorage + dialog; HTTP mode uses server `--root`)
- [x] `get_snapshot(repo_root, selected_run_id: Option)` → current, status, usage_by_model, history
- [x] Parse `usage_events.jsonl` like Python `summarize_run`
- [x] Skip non-dirs and `.gitkeep` when listing history

---

### Task 4: React UI + polling

- [x] Pick repo root (dialog) on first launch
- [x] Poll snapshot every 1.5s (3s when idle)
- [x] Sections: Now, Usage, History

---

### Task 5: Progress skin

- [x] Theme hook: `skin` = `board-runner` (default)
- [x] Map states to cell index; CSS/SVG original art (no third-party IP)
- [x] Skin swap via simple toggle or `data-skin` without changing DTO

---

### Task 6: Docs + verify

- [x] README section: how to run panel
- [x] Update `fyi.md`
- [x] Manual or fixture verify: snapshot reads a sample `runs/<id>/`

---

## Ruling log

- **Rust missing on machine:** install rustup before `create-tauri-app` — required for plan tech choice.
- **No `aiwork status --json` in MVP:** Rust reads files directly per spec.
- **MSVC `rustc` crash (0xc0e90002) / WDAC blocks cargo build-scripts (os 4551):** keep Tauri source; add `snapshot_server.py` + UI HTTP fallback for browser-dev verify until host allows Rust builds.
