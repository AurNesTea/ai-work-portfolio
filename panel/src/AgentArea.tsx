import type { AgentRow } from "./types";

type Props = {
  primaryAgent: string | null;
  subAgent1: string | null;
  subAgent2: string | null;
  onSelectPrimaryAgent: (id: string) => void;
  onSelectSubAgent1: (id: string) => void;
  onSelectSubAgent2: (id: string) => void;
  agents: AgentRow[];
  onAgentLogin: (id: string) => Promise<void>;
  onAgentLogout: (id: string) => Promise<void>;
  acting: boolean;
};

const AGENT_OPTIONS = [
  { id: "cursor", label: "Cursor" },
  { id: "claude", label: "Claude" },
  { id: "codex", label: "Codex" },
  { id: "gemini", label: "Gemini" },
];

export function AgentArea({
  primaryAgent,
  subAgent1,
  subAgent2,
  onSelectPrimaryAgent,
  onSelectSubAgent1,
  onSelectSubAgent2,
  agents,
  onAgentLogin,
  onAgentLogout,
  acting,
}: Props) {
  return (
    <section className="agent-area-panel" aria-label="代理區">
      <header className="agent-area-header">
        <h3 className="agent-area-title">代理區</h3>
      </header>

      <div className="agent-area-body">
        {/* 上方三個選擇：主代理一個、子代理兩個。三格不能選同一家。 */}
        <div className="agent-selectors-group">
          <div className="agent-select-row">
            <label htmlFor="primary-agent-select" className="agent-select-label">
              主代理
            </label>
            <select
              id="primary-agent-select"
              className="agent-dropdown"
              value={primaryAgent || ""}
              onChange={(e) => onSelectPrimaryAgent(e.target.value)}
            >
              <option value="">（請選擇主代理）</option>
              {AGENT_OPTIONS.map((opt) => (
                <option
                  key={opt.id}
                  value={opt.id}
                  disabled={opt.id === subAgent1 || opt.id === subAgent2}
                >
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          <div className="agent-select-row">
            <label htmlFor="sub-agent-1-select" className="agent-select-label">
              子代理 1
            </label>
            <select
              id="sub-agent-1-select"
              className="agent-dropdown"
              value={subAgent1 || ""}
              onChange={(e) => onSelectSubAgent1(e.target.value)}
            >
              <option value="">（尚未選擇）</option>
              {AGENT_OPTIONS.map((opt) => (
                <option
                  key={opt.id}
                  value={opt.id}
                  disabled={opt.id === primaryAgent || opt.id === subAgent2}
                >
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          <div className="agent-select-row">
            <label htmlFor="sub-agent-2-select" className="agent-select-label">
              子代理 2
            </label>
            <select
              id="sub-agent-2-select"
              className="agent-dropdown"
              value={subAgent2 || ""}
              onChange={(e) => onSelectSubAgent2(e.target.value)}
            >
              <option value="">（尚未選擇）</option>
              {AGENT_OPTIONS.map((opt) => (
                <option
                  key={opt.id}
                  value={opt.id}
                  disabled={opt.id === primaryAgent || opt.id === subAgent1}
                >
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* 下方列出四家：每家各自有登入與登出按鈕 */}
        <div className="agent-providers-list">
          {AGENT_OPTIONS.map((provider) => {
            const row = agents.find((a) => a.id === provider.id);
            const isMissing = row?.state === "missing";
            const isLoggedIn = row?.state === "logged_in";

            return (
              <div key={provider.id} className="agent-provider-row">
                <span className="agent-provider-name">
                  {provider.label}
                  {isLoggedIn && row?.account_label && (
                    <span className="agent-account-label"> · {row.account_label}</span>
                  )}
                </span>
                <div className="agent-provider-actions">
                  <span
                    className={`agent-status-tag ${
                      isMissing || !isLoggedIn
                        ? "tag-logged-out"
                        : "tag-logged-in"
                    }`}
                  >
                    {isMissing ? "找不到執行檔" : isLoggedIn ? "已登入" : "未登入"}
                  </span>
                  <button
                    type="button"
                    className="btn-agent-login-compact"
                    disabled={acting || isMissing}
                    title="登入或切換帳號"
                    onClick={() => void onAgentLogin(provider.id)}
                  >
                    登入
                  </button>
                  <button
                    type="button"
                    className="btn-agent-logout-compact"
                    disabled={acting || isMissing || !isLoggedIn}
                    title="登出並清除驗證"
                    onClick={() => void onAgentLogout(provider.id)}
                  >
                    登出
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
