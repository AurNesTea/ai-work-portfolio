import React from "react";
import { AgentArea } from "./AgentArea";
import type { AgentRow, ColorScheme, ThemeConfig } from "./types";

export type ModalView = "menu" | "agents" | "theme";

type Props = {
  activeView: ModalView;
  onClose: () => void;
  onSelectView: (view: ModalView) => void;
  onOpenUsage: () => void;
  onOpenDispatch: () => void;
  onOpenRoles?: () => void;
  // Agents view props
  agents: AgentRow[];
  primaryAgent: string | null;
  subAgent1: string | null;
  subAgent2: string | null;
  onSetPrimaryAgent: (agentId: string) => void;
  onSetSubAgent1: (agentId: string) => void;
  onSetSubAgent2: (agentId: string) => void;
  onAgentLogin: (agentId: string) => Promise<void>;
  onAgentLogout: (agentId: string) => Promise<void>;
  acting: boolean;
  // Theme view props
  theme: ThemeConfig;
  onUpdateTheme: (key: keyof ThemeConfig, dataUrl: string | null) => void;
  scheme: ColorScheme;
  onSchemeChange: (scheme: ColorScheme) => void;
};

export function MenuModal({
  activeView,
  onClose,
  onSelectView,
  onOpenUsage,
  onOpenDispatch,
  onOpenRoles,
  agents,
  primaryAgent,
  subAgent1,
  subAgent2,
  onSetPrimaryAgent,
  onSetSubAgent1,
  onSetSubAgent2,
  onAgentLogin,
  onAgentLogout,
  acting,
  theme,
  onUpdateTheme,
  scheme,
  onSchemeChange,
}: Props) {
  function handleFileChange(
    key: keyof ThemeConfig,
    e: React.ChangeEvent<HTMLInputElement>
  ) {
    const file = e.target.files?.[0];
    if (!file) return;
    // 只接受 JPG、PNG，其他格式的圖檔不要收
    const isJpegOrPng =
      file.type === "image/jpeg" ||
      file.type === "image/png" ||
      /\.(jpe?g|png)$/i.test(file.name);
    if (!isJpegOrPng) {
      e.target.value = "";
      return;
    }
    const reader = new FileReader();
    reader.onload = (event) => {
      const result = event.target?.result;
      if (typeof result === "string") {
        onUpdateTheme(key, result);
      }
    };
    reader.readAsDataURL(file);
    // Reset file input value so re-selecting same file triggers change
    e.target.value = "";
  }

  return (
    <div
      className="modal-overlay"
      role="dialog"
      aria-modal="true"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className={`modal-dialog${activeView === "agents" ? " is-agents" : ""}`}>
        <header className="modal-header">
          {activeView !== "menu" && (
            <button
              type="button"
              className="modal-back-btn"
              onClick={() => onSelectView("menu")}
              title="返回選單"
            >
              ← 選單
            </button>
          )}
          <h2 className="modal-title">
            {activeView === "menu" && "選單"}
            {activeView === "agents" && "代理管理"}
            {activeView === "theme" && "主題設定"}
          </h2>
          <button
            type="button"
            className="modal-close-btn"
            onClick={onClose}
            aria-label="關閉回到首頁"
            title="關閉"
          >
            ✕
          </button>
        </header>

        <div className="modal-content">
          {activeView === "menu" && (
            <div className="menu-list">
              <button
                type="button"
                className="menu-item-btn"
                onClick={() => onSelectView("agents")}
              >
                <div className="menu-item-icon">🤖</div>
                <div className="menu-item-text">
                  <h3>代理</h3>
                  <p>選主代理、兩個子代理，並看登入狀態</p>
                </div>
                <div className="menu-item-arrow">→</div>
              </button>

              <button
                type="button"
                className="menu-item-btn"
                onClick={onOpenUsage}
              >
                <div className="menu-item-icon">📊</div>
                <div className="menu-item-text">
                  <h3>用量</h3>
                  <p>台北日曆月 Token 用量與牌價花費明細</p>
                </div>
                <div className="menu-item-arrow">→</div>
              </button>

              <button
                type="button"
                className="menu-item-btn"
                onClick={() => onSelectView("theme")}
              >
                <div className="menu-item-icon">🎨</div>
                <div className="menu-item-text">
                  <h3>主題</h3>
                  <p>模式切換、工作區背景與個性照片</p>
                </div>
                <div className="menu-item-arrow">→</div>
              </button>

              <button
                type="button"
                className="menu-item-btn"
                onClick={onOpenDispatch}
              >
                <div className="menu-item-icon">📋</div>
                <div className="menu-item-text">
                  <h3>派工</h3>
                  <p>派工角色對照表與模型清單維護</p>
                </div>
                <div className="menu-item-arrow">→</div>
              </button>

              <button
                type="button"
                className="menu-item-btn"
                onClick={onOpenRoles}
              >
                <div className="menu-item-icon">🎭</div>
                <div className="menu-item-text">
                  <h3>角色</h3>
                  <p>定義角色原則、技能與素材包套用</p>
                </div>
                <div className="menu-item-arrow">→</div>
              </button>
            </div>
          )}

          {activeView === "agents" && (
            <div className="agents-panel">
              <p className="modal-hint">
                上方選主代理和兩個子代理，三格不能選同一家。換主代理只重開下面的大終端，換子代理只重開對應的小終端，不取消已派出去的那一輪。
              </p>
              <AgentArea
                primaryAgent={primaryAgent}
                subAgent1={subAgent1}
                subAgent2={subAgent2}
                onSelectPrimaryAgent={onSetPrimaryAgent}
                onSelectSubAgent1={onSetSubAgent1}
                onSelectSubAgent2={onSetSubAgent2}
                agents={agents}
                onAgentLogin={onAgentLogin}
                onAgentLogout={onAgentLogout}
                acting={acting}
              />
            </div>
          )}

          {activeView === "theme" && (
            <div className="theme-panel">
              <p className="modal-hint">
                設定模式、工作區背景圖與個性照片。圖檔存在本機設定（localStorage），不寫進 repo。
              </p>
              <label className="skin-pick theme-scheme">
                模式
                <select
                  value={scheme}
                  onChange={(e) => onSchemeChange(e.target.value as ColorScheme)}
                  aria-label="模式：淺色或深色"
                >
                  <option value="light">淺色</option>
                  <option value="dark">深色</option>
                </select>
              </label>
              <div className="theme-fields">
                {/* 背景 */}
                <div className="theme-card">
                  <div className="theme-card-header">
                    <h3>背景</h3>
                    <span className="theme-card-sub">
                      建議尺寸 1920×1080，JPG / PNG
                    </span>
                  </div>
                  <div className="theme-preview-box">
                    {theme.background ? (
                      <img
                        src={theme.background}
                        alt="背景預覽"
                        className="preview-img"
                      />
                    ) : (
                      <span className="preview-fallback">底色</span>
                    )}
                  </div>
                  <div className="theme-actions">
                    <label className="file-upload-btn">
                      選擇圖檔
                      <input
                        type="file"
                        accept=".jpg,.jpeg,.png,image/jpeg,image/png"
                        onChange={(e) => handleFileChange("background", e)}
                      />
                    </label>
                    {theme.background && (
                      <button
                        type="button"
                        className="btn-clear-theme"
                        onClick={() => onUpdateTheme("background", null)}
                      >
                        重設
                      </button>
                    )}
                  </div>
                </div>

                {/* 個性照片 */}
                <div className="theme-card">
                  <div className="theme-card-header">
                    <h3>個性照片</h3>
                    <span className="theme-card-sub">
                      建議尺寸 1200×800，JPG / PNG
                    </span>
                  </div>
                  <div className="theme-preview-box">
                    {theme.portrait ? (
                      <img
                        src={theme.portrait}
                        alt="個性照片預覽"
                        className="preview-img"
                      />
                    ) : (
                      <span className="preview-fallback">無照片</span>
                    )}
                  </div>
                  <div className="theme-actions">
                    <label className="file-upload-btn">
                      選擇圖檔
                      <input
                        type="file"
                        accept=".jpg,.jpeg,.png,image/jpeg,image/png"
                        onChange={(e) => handleFileChange("portrait", e)}
                      />
                    </label>
                    {theme.portrait && (
                      <button
                        type="button"
                        className="btn-clear-theme"
                        onClick={() => onUpdateTheme("portrait", null)}
                      >
                        重設
                      </button>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        <footer className="modal-footer">
          <button type="button" className="btn-modal-close" onClick={onClose}>
            回到首頁
          </button>
        </footer>
      </div>
    </div>
  );
}
