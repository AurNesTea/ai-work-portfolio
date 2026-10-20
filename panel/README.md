# aiwork panel (P5 read-only)

Tauri 2 + React observer for `runs/` status and usage. Does **not** start workflows.

## Prerequisites

- Node 20+
- Rust + Tauri deps ([prerequisites](https://tauri.app/start/prerequisites/)) for desktop shell
- If `cargo` build-scripts are blocked (Windows WDAC / Smart App Control, os error 4551), use **browser-dev** below until policy allows Rust builds

## Install

```powershell
cd panel
npm install
```

## Browser-dev (no Tauri binary)

Terminal 1 — snapshot API over fixtures or a real repo:

```powershell
# fixtures
python panel/scripts/snapshot_server.py --root panel/fixtures
# or real repo
python panel/scripts/snapshot_server.py --root .
```

Terminal 2:

```powershell
cd panel
npm run dev
```

Open the Vite URL. UI polls `http://127.0.0.1:8765/snapshot`.

## Desktop (Tauri)

Requires Rust **and** Windows Smart App Control / WDAC allowing `rustc` and cargo build-scripts. If `rustc -vV` crashes (`0xc0e90002`) or cargo reports os error 4551, stay on browser-dev.

```powershell
cd panel
npm run tauri dev
```

Pick the ai-work repo root once; panel reads `runs/` and can spawn `python -m aiwork`.

## Dispatch (P5.1)

Select a relative `workflows/*.yaml`, then Run / Approve / Cancel. Approve is enabled only when status is `awaiting_approval`.

## Verify

```powershell
python panel/scripts/verify_fixtures.py
cd panel; npm run build
```

## Skins

`board-runner` (default playful board) or `plain` — toggle in the header. Swap assets/CSS under `src/` without changing the snapshot DTO.
