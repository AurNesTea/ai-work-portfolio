import { useEffect, useState } from "react";
import type { ModelsResponseDto, RolesResponseDto } from "./types";

const SERVER_BASE = "http://127.0.0.1:8765";

const AGENT_LABELS: Record<string, string> = {
  cursor: "Cursor",
  claude: "Claude",
  codex: "Codex",
  gemini: "Gemini（agy）",
};

type Props = {
  subAgent1: string | null;
  subAgent2: string | null;
};

export function SubAgentModels({ subAgent1, subAgent2 }: Props) {
  const [catalog, setCatalog] = useState<Record<string, string[]>>({});
  const [roles, setRoles] = useState<Record<string, { agent: string; model: string }>>({});

  useEffect(() => {
    let active = true;
    async function fetchCatalogAndRoles() {
      try {
        const [mRes, rRes] = await Promise.all([
          fetch(`${SERVER_BASE}/models`),
          fetch(`${SERVER_BASE}/roles`),
        ]);
        if (mRes.ok && active) {
          const mData: ModelsResponseDto = await mRes.json();
          setCatalog(mData.models || {});
        }
        if (rRes.ok && active) {
          const rData: RolesResponseDto = await rRes.json();
          setRoles(rData.roles || {});
        }
      } catch {
        // ignore network error
      }
    }
    void fetchCatalogAndRoles();
    return () => {
      active = false;
    };
  }, []);

  const slots = [
    { title: "子代理 1", agent: subAgent1 },
    { title: "子代理 2", agent: subAgent2 },
  ];

  return (
    <section className="sub-model-panel" aria-label="子代理模型">
      <header className="agent-area-header">
        <h3 className="agent-area-title">子代理模型與角色</h3>
      </header>
      <div className="sub-model-body">
        {slots.map((slot) => {
          const models = slot.agent ? catalog[slot.agent] ?? [] : [];
          const name = slot.agent ? AGENT_LABELS[slot.agent] ?? slot.agent : "";
          const mappedRoles = slot.agent
            ? Object.entries(roles).filter(([, r]) => r.agent === slot.agent)
            : [];

          return (
            <div key={slot.title} className="sub-model-group">
              <p className="sub-model-heading">
                {slot.title}
                {name ? ` · ${name}` : ""}
              </p>
              {slot.agent ? (
                <>
                  {mappedRoles.length > 0 && (
                    <div style={{ marginBottom: "6px", fontSize: "11px" }}>
                      <span style={{ color: "rgba(128,128,128,0.8)" }}>對映角色：</span>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: "4px", marginTop: "2px" }}>
                        {mappedRoles.map(([rId, r]) => (
                          <span
                            key={rId}
                            style={{
                              background: "rgba(24, 144, 255, 0.15)",
                              padding: "1px 4px",
                              borderRadius: "3px",
                              fontSize: "10px",
                            }}
                          >
                            {rId} ({r.model})
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  <ul className="sub-model-list">
                    {models.map((model) => (
                      <li key={model}>{model}</li>
                    ))}
                  </ul>
                </>
              ) : (
                <p className="sub-model-empty">尚未選擇</p>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
