"""Build a sanitized portfolio tree in the current worktree (orphan branch)."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

SRC = Path(r"C:\專案\ai-work")
DST = Path(r"C:\專案\ai-work-portfolio")

SKIP_DIR_NAMES = {
    ".git",
    "node_modules",
    "target",
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "venv",
    "dist",
    "build",
    ".superpowers",
    "runs",
    "data",
    ".tmp-agy-caps",
}

SKIP_FILE_NAMES = {
    "fyi.md",
    "FYI.md",
    ".tmp-import-agy-usage.py",
    ".tmp-wait-phase2-report.ps1",
    "launch-agy.cmd",
    "nudge-report.md",
}

SKIP_GLOBS_REL = [
    "docs/superpowers/reports/**",
    "docs/superpowers/plans/2026-10-16-aiwork-dispatch-and-packs.md",
    "prompts/phase1-dispatch/**",
    "prompts/phase2-packs/continue.md",
    "prompts/phase2-packs/nudge-report.md",
    "briefs/phase1-dispatch.md",
    "briefs/phase2-packs.md",
    ".cursor/mcp.json",
]

# Path / identity sanitization (content rewrite).
# Use forward-slash placeholders only — re.sub repl treats \U as bad escape.
REPLACEMENTS = [
    (re.compile(re.escape(r"C:\Users\kevin"), re.I), "C:/Users/<user>"),
    (re.compile(re.escape("C:/Users/kevin"), re.I), "C:/Users/<user>"),
    # Native + JSON-escaped Windows paths
    (re.compile(re.escape(r"C:\專案\ai-work"), re.I), "C:/path/to/ai-work"),
    (re.compile(re.escape(r"C:\\專案\\ai-work"), re.I), "C:/path/to/ai-work"),
    (re.compile(re.escape("C:/專案/ai-work"), re.I), "C:/path/to/ai-work"),
    (re.compile(re.escape(r"C:\專案"), re.I), "C:/path/to/projects"),
    (re.compile(re.escape(r"C:\\專案"), re.I), "C:/path/to/projects"),
    (re.compile(re.escape("C:/專案"), re.I), "C:/path/to/projects"),
    (re.compile(re.escape("X:\\")), "C:/path/to/ai-work/"),
    (re.compile(re.escape("X:/")), "C:/path/to/ai-work/"),
    (re.compile(r"Team · UDN_1"), "Team · ExampleOrg"),
    (re.compile(r"\bUDN_1\b"), "ExampleOrg"),
    (re.compile(r"UDN_1"), "ExampleOrg"),
    (re.compile(r"kevin011037@gmail\.com"), "<email@example.com>"),
    (re.compile(r"C:\\\\Users\\\\kevin\\\\OneDrive\\\\[^\n\r\"'`]+", re.I), "C:/Users/<user>/Documents/kit"),
    (re.compile(r"C:/Users/kevin/OneDrive/[^\n\r\"'`]+", re.I), "C:/Users/<user>/Documents/kit"),
    (re.compile(r"\| `owner` \| kevin \|"), "| `owner` | <user> |"),
    (re.compile(r"com\.aurnestea\.aiwork", re.I), "com.example.aiwork"),
    (re.compile(r"github\.com/AurNesTea/", re.I), "github.com/<user>/"),
    (re.compile(r"AurNesTea/", re.I), "<user>/"),
    (re.compile(r"AurNesTea", re.I), "<user>"),
    # Company Claude / org-seat dial-in
    (re.compile(r"公司 Claude(?:\s*帳號)?"), "Claude 組織帳號"),
    (re.compile(r"Claude 公司帳號"), "Claude 組織帳號"),
    (re.compile(r"公司 Team 席位"), "Team 方案席位"),
    (re.compile(r"公司組織座位"), "組織席位"),
    (re.compile(r"公司電腦"), "另一台電腦"),
    (re.compile(r"公司庫"), "第二台機器的素材庫"),
    (re.compile(r"個人帳號與公司帳號"), "多帳號"),
    (re.compile(r"個人與公司帳號"), "多帳號"),
    (re.compile(r"聯合報|udn\.com", re.I), "ExampleOrg"),
]


def should_skip(rel: Path) -> bool:
    parts = set(rel.parts)
    if parts & SKIP_DIR_NAMES:
        return True
    if rel.name in SKIP_FILE_NAMES:
        return True
    if rel.name.endswith((".sqlite", ".sqlite-journal", ".sqlite-wal", ".sqlite-shm")):
        return True
    s = rel.as_posix()
    for g in SKIP_GLOBS_REL:
        # simple prefix / exact checks
        g2 = g.replace("**/", "").replace("**", "")
        if g.endswith("/**"):
            prefix = g[: -3]
            if s == prefix.rstrip("/") or s.startswith(prefix):
                return True
        elif s == g or s.endswith("/" + g):
            return True
    return False


def sanitize_text(text: str) -> str:
    out = text
    for pat, repl in REPLACEMENTS:
        out = pat.sub(repl, out)
    return out


def is_text_file(path: Path) -> bool:
    if path.suffix.lower() in {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".json",
        ".jsonl",
        ".md",
        ".mdc",
        ".yaml",
        ".yml",
        ".toml",
        ".txt",
        ".css",
        ".html",
        ".svg",
        ".gitignore",
        ".cmd",
        ".ps1",
        ".sh",
    }:
        return True
    if path.name in {"AGENTS.md", "CLAUDE.md", "README.md", "LICENSE", "Dockerfile"}:
        return True
    return False


PORTFOLIO_README = """# aiwork

Local orchestrator for agent CLIs (Cursor, Claude Code, Codex, Gemini / Antigravity).

**No model HTTP API and no API keys in this repository.** Each agent uses its own CLI login on the machine.

## What it is

A personal workbench to:

- run sequential workflows across multiple agent CLIs
- map **roles** → agent + model (`config/roles.yaml`)
- observe runs, usage, and account labels in a desktop/web panel
- manage role/rule/skill **packs** (upload, apply, probe) without putting secrets in git

## Quick start

```powershell
cd C:\\path\\to\\ai-work
python -m pip install -e ".[dev]"
aiwork run workflows/smoke.yaml
aiwork status
aiwork usage
```

Panel (browser / Tauri):

```powershell
python panel/scripts/snapshot_server.py --root .
cd panel; npm install; npm run dev
```

## Portfolio notes

This public snapshot is sanitized for sharing:

- no `fyi.md` session diary
- no local usage SQLite / run artifacts
- host paths and org examples replaced with placeholders
- tests use mock org names only (e.g. `MockOrg`, `Acme Corp`)

## License / authorship

Personal side project. GitHub: see repository owner page.
"""


def main() -> None:
    # Clear destination except .git
    for child in DST.iterdir():
        if child.name == ".git" or child.name == "_build_portfolio.py":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()

    copied = 0
    sanitized = 0
    for path in SRC.rglob("*"):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(SRC)
        except ValueError:
            continue
        if should_skip(rel):
            continue
        # skip build script itself if any
        if rel.name.startswith(".tmp-"):
            continue
        dest = DST / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if is_text_file(path):
            try:
                raw = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                shutil.copy2(path, dest)
                copied += 1
                continue
            new = sanitize_text(raw)
            dest.write_text(new, encoding="utf-8", newline="\n")
            copied += 1
            if new != raw:
                sanitized += 1
        else:
            shutil.copy2(path, dest)
            copied += 1

    (DST / "README.md").write_text(PORTFOLIO_README, encoding="utf-8", newline="\n")
    # Ensure ignore covers local data
    gi = DST / ".gitignore"
    extra = "\n# portfolio hygiene\nfyi.md\nFYI.md\ndata/\nruns/*/\n!runs/.gitkeep\n.cursor/mcp.json\n"
    if gi.exists():
        text = gi.read_text(encoding="utf-8")
        if "fyi.md" not in text:
            gi.write_text(text.rstrip() + "\n" + extra, encoding="utf-8", newline="\n")
    (DST / "PORTFOLIO.md").write_text(
        """# Portfolio one-pager

## One line

Local multi-agent CLI workbench: dispatch by role, observe usage, manage packs — without putting API keys in the repo.

## Proof points

1. Sequential workflows across Cursor / Claude / Codex / Gemini (Antigravity) CLIs
2. Role → agent/model mapping with pinned `resolved.json` per run
3. Panel for dispatch, roles/packs, and usage; automated tests included

## Not this project

- Not a cloud LLM router
- Not a RAG product (context is agent rules/skills/prompts, not a document index)

## How to demo

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q
python panel/scripts/snapshot_server.py --root .
cd panel; npm run dev
```
""",
        encoding="utf-8",
        newline="\n",
    )
    print(f"copied={copied} sanitized_files={sanitized}")


if __name__ == "__main__":
    main()
