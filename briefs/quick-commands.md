# Brief: quick-commands

## Meta

| Field | Value |
|---|---|
| `task_id` | quick-commands |
| `owner` | <user> |
| `created` | 2026-10-11 |
| `preferred_agent` | gemini |
| `preferred_model` | gemini-3.8-flash-high |
| `approval_required` | false |
| `mcp_profile` | default |

## Outcome

主代理終端底下的「快捷指令」只留兩顆：`/sync-content`、`/update-progress`。測試用的 workflow 下拉和派工拿掉。

## Acceptance

- [ ] 快捷指令不再有 workflow 下拉，也不再有「派工」
- [ ] 按下 `/sync-content` 會把這行送進主代理 CLI
- [ ] 按下 `/update-progress` 會把這行送進主代理 CLI
- [ ] 子代理終端沒有這一列

## Non-goals

不改 runner、不實作這兩個技能本身、不改登入、不改主題、不 commit。

## Handoff to workflow

- Prompt：`prompts/home-stage/quick-commands.md`
- 用已開著、目前沒在做事的 agy 互動模式讀該 prompt，不另開視窗，不走 `agy --print`
