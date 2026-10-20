import { useCallback, useEffect, useRef, useState } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";
import type { RunStatusDto } from "./types";

const AGENT_NAMES: Record<string, string> = {
  cursor: "Cursor",
  claude: "Claude",
  codex: "Codex",
  gemini: "Gemini",
};

const PTY_WS_URL = "ws://127.0.0.1:8765/pty";

type Props = {
  agent: string | null;
  agentLabel?: string;
  agentState?: string; // "logged_in" | "logged_out" | "missing" | "unknown"
  repoRoot: string;
  title?: string;
  isSubAgent?: boolean;
  status?: RunStatusDto | null;
  workflow?: string;
  workflows?: string[];
  acting?: boolean;
  onWorkflowChange?: (wf: string) => void;
  onRun?: (wf?: string) => Promise<void>;
  onContinue?: (reResolve?: boolean) => Promise<void> | void;
  dispatchChanged?: boolean;
  onApprove?: () => Promise<void>;
  onCancel?: () => Promise<void>;
};

export function InteractiveTerminal({
  agent,
  agentLabel: propAgentLabel,
  agentState = "unknown",
  repoRoot,
  title = "CLI 終端",
  isSubAgent = false,
  status = null,
  acting = false,
  onContinue,
  dispatchChanged = false,
}: Props) {
  const terminalRef = useRef<HTMLDivElement>(null);
  const termInstance = useRef<Terminal | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const [inputVal, setInputVal] = useState("");
  const [connStatus, setConnStatus] = useState<
    "connected" | "connecting" | "disconnected"
  >("disconnected");

  const [localLoggedIn, setLocalLoggedIn] = useState(false);

  useEffect(() => {
    setLocalLoggedIn(false);
  }, [agent]);

  const currentAgentLabel =
    propAgentLabel || (agent ? AGENT_NAMES[agent] || agent : "（未選擇）");
  const isGemini = agent === "gemini";
  const isLoggedIn = agentState === "logged_in" || localLoggedIn;

  // Send input string to active PTY WebSocket
  const sendToPty = useCallback((text: string) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "input", data: text }));
    }
  }, []);

  // Connect native PTY WebSocket to xterm.js
  useEffect(() => {
    if (!agent) {
      setConnStatus("disconnected");
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      if (termInstance.current) {
        termInstance.current.dispose();
        termInstance.current = null;
      }
      return;
    }

    if (!terminalRef.current) return;

    // Clean up previous instance
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    if (termInstance.current) {
      termInstance.current.dispose();
      termInstance.current = null;
    }

    setConnStatus("connecting");

    const term = new Terminal({
      cursorBlink: true,
      fontFamily:
        "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace",
      fontSize: 13,
      lineHeight: 1.35,
      theme: {
        background: "#18181b",
        foreground: "#f4f4f5",
        cursor: "#4ade80",
        cursorAccent: "#18181b",
        selectionBackground: "rgba(74, 222, 128, 0.3)",
        black: "#4b5563",
        red: "#ef4444",
        green: "#22c55e",
        yellow: "#eab308",
        blue: "#3b82f6",
        magenta: "#d946ef",
        cyan: "#06b6d4",
        white: "#f4f4f5",
        brightBlack: "#71717a",
        brightRed: "#f87171",
        brightGreen: "#4ade80",
        brightYellow: "#fde047",
        brightBlue: "#60a5fa",
        brightMagenta: "#e879f9",
        brightCyan: "#22d3ee",
        brightWhite: "#ffffff",
      },
    });

    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.open(terminalRef.current);
    fitAddon.fit();

    termInstance.current = term;
    fitAddonRef.current = fitAddon;

    const qs = new URLSearchParams({
      agent,
      cwd: repoRoot || "",
      cols: String(term.cols || 80),
      rows: String(term.rows || 24),
    });

    const ws = new WebSocket(`${PTY_WS_URL}?${qs.toString()}`);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnStatus("connected");
      fitAddon.fit();
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(
          JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows })
        );
      }
    };

    ws.onmessage = (event) => {
      if (typeof event.data === "string" && event.data.trim().startsWith("{")) {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === "agent_status" && msg.state === "logged_in") {
            setLocalLoggedIn(true);
            window.dispatchEvent(
              new CustomEvent("agent-status-changed", { detail: msg })
            );
            return;
          }
        } catch {
          // not JSON control message, proceed to term.write
        }
      }
      term.write(event.data);
    };

    ws.onerror = () => {
      setConnStatus("disconnected");
    };

    ws.onclose = () => {
      setConnStatus("disconnected");
    };

    const dataDisposable = term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "input", data }));
      }
    });

    // Auto-fit on resize
    const resizeObserver = new ResizeObserver((entries) => {
      // The 用量 page hides the home page with display:none; fitting a zero-size box
      // would shrink every live PTY to a few columns.
      const box = entries[0]?.contentRect;
      if (!box || box.width === 0 || box.height === 0) return;
      try {
        fitAddon.fit();
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(
            JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows })
          );
        }
      } catch {
        // ignore
      }
    });

    if (terminalRef.current) {
      resizeObserver.observe(terminalRef.current);
    }

    return () => {
      resizeObserver.disconnect();
      dataDisposable.dispose();
      // Detach first: a late onclose from this socket must not mark its replacement offline.
      ws.onopen = null;
      ws.onmessage = null;
      ws.onerror = null;
      ws.onclose = null;
      ws.close();
      term.dispose();
      wsRef.current = null;
      termInstance.current = null;
      fitAddonRef.current = null;
    };
  }, [agent, repoRoot]);

  // Click on terminal body focuses terminal
  function handleBodyClick() {
    if (termInstance.current) {
      termInstance.current.focus();
    }
  }



  // Quick action toolbar handlers
  function handleSyncContent() {
    sendToPty("/sync-content\r");
    if (termInstance.current) {
      termInstance.current.focus();
    }
  }

  function handleUpdateProgress() {
    sendToPty("/update-progress\r");
    if (termInstance.current) {
      termInstance.current.focus();
    }
  }

  function handleInputSubmit(e: React.FormEvent) {
    e.preventDefault();
    const cmd = inputVal.trim();
    if (!cmd) return;
    setInputVal("");
    sendToPty(`${cmd}\r`);
    if (termInstance.current) {
      termInstance.current.focus();
    }
  }

  let statusText = "○ 離線";
  if (connStatus === "connecting") {
    statusText = "◌ 連線中...";
  } else if (connStatus === "connected") {
    if (isGemini) {
      statusText = "● agy 互動模式";
    } else if (isLoggedIn) {
      statusText = "● 互動模式";
    } else {
      statusText = "○ 登入模式";
    }
  }

  return (
    <section className="terminal-panel" aria-label={title}>
      <header className="terminal-header">
        <div className="terminal-controls">
          <span className="dot dot-red" />
          <span className="dot dot-yellow" />
          <span className="dot dot-green" />
          <span className="terminal-title">
            {title} · {agent ? currentAgentLabel : "未選擇"}
          </span>
        </div>
        <div className="terminal-path" title={repoRoot}>
          {repoRoot ? `cwd: ${repoRoot}` : "cwd: （未選擇專案）"}
        </div>
        <div className="terminal-status-actions">
          <span
            className={`terminal-status-pill ${
              !agent
                ? "status-unselected"
                : connStatus === "connected" && isLoggedIn
                ? "status-online"
                : "status-offline"
            }`}
          >
            {!agent ? "○ 尚未選擇" : statusText}
          </span>
        </div>
      </header>

      <div
        className="terminal-body"
        onClick={handleBodyClick}
        style={{ cursor: agent ? "text" : "default" }}
      >
        {!agent ? (
          <div className="terminal-empty-prompt">
            <p>尚未選擇</p>
          </div>
        ) : (
          <div ref={terminalRef} className="xterm-wrapper" />
        )}
      </div>

      {!isSubAgent && agent && (
        <div className="terminal-toolbar">
          <div className="terminal-quick-actions">
            <span className="quick-label">快捷指令：</span>
            <button
              type="button"
              className="term-chip"
              disabled={acting}
              onClick={handleSyncContent}
            >
              /sync-content
            </button>
            <button
              type="button"
              className="term-chip"
              disabled={acting}
              onClick={handleUpdateProgress}
            >
              /update-progress
            </button>
            {status?.state === "waiting" && (
              <>
                <button
                  type="button"
                  className="term-chip term-chip-continue"
                  disabled={acting || !onContinue}
                  onClick={() => onContinue?.(false)}
                >
                  繼續
                </button>
                {dispatchChanged && (
                  <button
                    type="button"
                    className="term-chip term-chip-continue"
                    disabled={acting || !onContinue}
                    onClick={() => onContinue?.(true)}
                    title="使用變更後的對照表重新解析未完成步驟並繼續"
                  >
                    用新對照表繼續
                  </button>
                )}
              </>
            )}
          </div>

          <form onSubmit={handleInputSubmit} className="terminal-input-row">
            <span className="prompt-symbol">{agent}&gt;</span>
            <input
              type="text"
              value={inputVal}
              onChange={(e) => setInputVal(e.target.value)}
              placeholder="在此對焦、派工、同意..."
              className="terminal-input"
              disabled={acting}
            />
            <button
              type="submit"
              disabled={acting || !inputVal.trim()}
              className="term-send-btn"
            >
              送出
            </button>
          </form>
        </div>
      )}
    </section>
  );
}
