# Brief: cli-readable

## Meta

| Field | Value |
|---|---|
| `task_id` | cli-readable |
| `owner` | <user> |
| `created` | 2026-10-10 |
| `preferred_agent` | gemini |
| `preferred_model` | gemini-3.8-flash-high |
| `approval_required` | false |
| `mcp_profile` | default |

## Outcome

首頁依實際視窗重排。CLI 和選單跟著視窗變大，左下角輸出文字看得清楚。

## Acceptance

- [ ] 不再把整頁鎖死在參考圖 `942 / 578`，操作區隨視窗變大
- [ ] 左下角 xterm 有多行可讀文字，不是一片黑或只剩標題
- [ ] 右下角選單按鈕在一般桌面視窗裡好點
- [ ] 終端仍是現有的 PTY／xterm，不改成假日誌
- [ ] 舞台仍可用 `panel/public/stage-skin.png` 當背景，選單項目不變
- [ ] 不再加回頂部「Cursor／尚未派工／待命」那條

## Non-goals

不改 runner、不改關卡規則、不重畫角色動畫。

## Constraints

用 agy 互動模式做。不要加 `--print`。

## Context

預覽：http://127.0.0.1:1420/ 。`.stage-screen` 鎖 `aspect-ratio: 942 / 578`。終端約舞台高度 27%，選單約 31%。標題列、快捷列、輸入列把 xterm 正文擠沒了。

## Handoff to workflow

- Prompt：`prompts/home-stage/cli-readable.md`
- 這次用 agy 互動模式讀該 prompt，不走 `agy --print`
