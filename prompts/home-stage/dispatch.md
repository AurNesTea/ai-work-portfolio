讀 `docs/superpowers/plans/2026-10-08-aiwork-home-stage.md`，只做尚未勾選的首頁。

要做的：
- 首頁上方是角色與橫向關卡，下方留互動終端的位置。拿掉原本工作頁的 workflow 下拉、執行／繼續／核准／取消、文字現況、這次用量、紀錄列表。
- 右上角漢堡按鈕。按下後畫面中央開半透明選單，項目是代理、用量、主題。選完或關閉後回到首頁。
- 主題可換角色、背景、魔王的本機圖檔。沒選圖用現在的簡易棋子。圖存在本機設定，不寫進 repo。
- 關卡數等於進行中 workflow 的步驟數。通關、魔王、暫停跟 `runs/<id>/status.json` 的狀態與 `lives_total`、`lives_left` 走。

不要改 runner 的關卡規則。不要用 headless，也不要加 `--print`。
