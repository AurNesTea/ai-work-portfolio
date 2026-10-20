# Brief: theme-merge

## Meta

| Field | Value |
|---|---|
| `task_id` | theme-merge |
| `owner` | <user> |
| `created` | 2026-10-10 |
| `preferred_agent` | gemini |
| `preferred_model` | gemini-3.8-flash-high |
| `approval_required` | false |
| `mcp_profile` | default |

## Outcome

選單只留一顆「主題」。主題裡有淺色／深色、背景圖、右側圖片格的個性照片，並標 JPG/PNG 與建議尺寸。

## Acceptance

- [ ] 外觀、場景兩顆按鈕合成一顆主題
- [ ] 背景是 1920×1080 的 JPG/PNG，鋪在首頁工作區後面
- [ ] 個性照片是 1200×800 的 JPG/PNG，只出現在右側圖片格
- [ ] 主題畫面不再有角色、魔王、場景

## Handoff to workflow

- Prompt：`prompts/home-stage/theme-merge.md`
- 用 agy 互動模式讀該 prompt，不走 `agy --print`
