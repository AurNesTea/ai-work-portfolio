import type { UsageLogItem } from "./types";

type Props = {
  month: string;
  onMonthChange: (m: string) => void;
  usageLog: UsageLogItem[];
  formatUsd: (val: number | null | undefined) => string;
  onBackToHome?: () => void;
};

export function UsagePage({
  month,
  onMonthChange,
  usageLog,
  formatUsd,
}: Props) {
  // Token and cost totals for usage
  const tokenTotal = usageLog.reduce(
    (sum, row) => ({
      input_uncached: sum.input_uncached + row.input_uncached,
      cache_read: sum.cache_read + row.cache_read,
      cache_write: sum.cache_write + row.cache_write,
      output: sum.output + row.output,
    }),
    { input_uncached: 0, cache_read: 0, cache_write: 0, output: 0 }
  );
  const priced = usageLog
    .map((row) => row.usd)
    .filter((v): v is number => typeof v === "number");
  const usdTotal = priced.length
    ? priced.reduce((sum, v) => sum + v, 0)
    : null;

  return (
    <div className="usage-page">
      <section className="usage-summary-grid" aria-label="Token 費用與用量統計">
        <div className="usage-stat-card usage-stat-cost">
          <p className="usage-stat-label">預估總費用 (USD)</p>
          <p className="usage-stat-value usage-cost-val">
            {usdTotal != null ? `$${formatUsd(usdTotal)}` : "—"}
          </p>
        </div>
        <div className="usage-stat-card">
          <p className="usage-stat-label">未快取輸入</p>
          <p className="usage-stat-value">
            {tokenTotal.input_uncached.toLocaleString()}
          </p>
        </div>
        <div className="usage-stat-card">
          <p className="usage-stat-label">快取讀取</p>
          <p className="usage-stat-value">
            {tokenTotal.cache_read.toLocaleString()}
          </p>
        </div>
        <div className="usage-stat-card">
          <p className="usage-stat-label">快取寫入</p>
          <p className="usage-stat-value">
            {tokenTotal.cache_write.toLocaleString()}
          </p>
        </div>
        <div className="usage-stat-card">
          <p className="usage-stat-label">輸出 Token</p>
          <p className="usage-stat-value">
            {tokenTotal.output.toLocaleString()}
          </p>
        </div>
      </section>

      <div className="usage-bar">
        <div className="usage-bar-left">
          <label className="month-pick">
            <span className="month-pick-label">統計月份</span>
            <input
              type="month"
              className="month-input"
              value={month}
              onChange={(e) => onMonthChange(e.target.value)}
            />
          </label>
        </div>
        <p className="usage-page-hint">
          台北日曆月。美元依公開牌價計算；未設定牌價之模型留空。
        </p>
      </div>

      {usageLog.length === 0 ? (
        <div className="usage-empty-state">
          <p className="usage-empty-icon">📊</p>
          <p className="usage-empty-text">{month} 尚無任何用量紀錄</p>
        </div>
      ) : (
        <div className="usage-table-wrap">
          <table className="usage-table">
            <thead>
              <tr>
                <th>時間</th>
                <th>執行 ID</th>
                <th>步驟</th>
                <th>角色</th>
                <th>代理</th>
                <th>模型</th>
                <th className="num">輸入</th>
                <th className="num">快取讀</th>
                <th className="num">快取寫</th>
                <th className="num">輸出</th>
                <th className="num">美元</th>
              </tr>
            </thead>
            <tbody>
              {usageLog.map((row, i) => (
                <tr key={`${row.run_id}-${row.step_id}-${row.at}-${i}`}>
                  <td className="cell-time">{row.at || "—"}</td>
                  <td className="hid" title={row.run_id}>
                    {row.run_id.slice(0, 8)}
                  </td>
                  <td>{row.step_id || "—"}</td>
                  <td>{row.role || "—"}</td>
                  <td>
                    <span className="agent-badge">{row.agent || "—"}</span>
                  </td>
                  <td className="cell-model">{row.model}</td>
                  <td className="num">{row.input_uncached.toLocaleString()}</td>
                  <td className="num">{row.cache_read.toLocaleString()}</td>
                  <td className="num">{row.cache_write.toLocaleString()}</td>
                  <td className="num">{row.output.toLocaleString()}</td>
                  <td className="num cost-cell">
                    {row.usd != null ? `$${formatUsd(row.usd)}` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th colSpan={6}>合計（{usageLog.length} 筆紀錄）</th>
                <td className="num">{tokenTotal.input_uncached.toLocaleString()}</td>
                <td className="num">{tokenTotal.cache_read.toLocaleString()}</td>
                <td className="num">{tokenTotal.cache_write.toLocaleString()}</td>
                <td className="num">{tokenTotal.output.toLocaleString()}</td>
                <td className="num cost-cell">
                  {usdTotal != null ? `$${formatUsd(usdTotal)}` : "—"}
                </td>
              </tr>
            </tfoot>

          </table>
        </div>
      )}
    </div>
  );
}
