const STATE_LABEL: Record<string, string> = {
  queued: "排隊",
  running: "執行中",
  awaiting_approval: "待核准",
  waiting: "等待",
  succeeded: "成功",
  failed: "失敗",
  cancelled: "已取消",
};

export function stateLabel(state: string | null | undefined): string {
  if (!state) return "—";
  return STATE_LABEL[state] ?? state;
}

export function actionLabel(detail: string, ok: boolean): string {
  const text = detail.trim();
  if (!text) return ok ? "已啟動" : "失敗";
  if (text === "no run to cancel") return "沒有可取消的執行";
  if (text.startsWith("started pid=")) return `已啟動（${text.slice("started ".length)}）`;
  if (text.startsWith("cancelled ")) return `已取消 ${text.slice("cancelled ".length)}`;
  if (text.startsWith("approved ")) return `已核准 ${text.slice("approved ".length)}`;
  return text;
}
