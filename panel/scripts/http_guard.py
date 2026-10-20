"""Origin / Host guard for the panel's local HTTP + WebSocket server.

The server listens on 127.0.0.1 with no login, and /pty starts agent CLIs. A browser
attaches an Origin header to cross-site requests and WebSocket handshakes, so without
this check any page the user has open could drive the server. DNS rebinding makes a
hostile page look same-origin but leaves its own hostname in Host, so Host is checked too.
Requests with no Origin (curl, tests, Python clients) are not browsers and pass.
"""
from __future__ import annotations

import os
from urllib.parse import urlsplit

DEFAULT_ORIGINS = frozenset(
    {
        "http://localhost:1420",  # tauri dev / vite (strictPort 1420)
        "http://127.0.0.1:1420",  # vite opened by IP in a browser
        "tauri://localhost",  # packaged app on macOS / Linux
        "http://tauri.localhost",  # packaged app on Windows
        "https://tauri.localhost",
    }
)
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def allowed_origins() -> frozenset[str]:
    """Defaults plus AIWORK_PANEL_ORIGINS (comma-separated), e.g. a custom dev port."""
    raw = os.environ.get("AIWORK_PANEL_ORIGINS", "")
    extra = {o.strip().rstrip("/") for o in raw.split(",") if o.strip()}
    return DEFAULT_ORIGINS | extra


def host_allowed(host_header: str | None) -> bool:
    if not host_header:
        return True
    try:
        hostname = urlsplit(f"//{host_header}").hostname
    except ValueError:
        return False
    return hostname in LOCAL_HOSTS


def origin_allowed(origin: str | None) -> bool:
    if origin is None:
        return True
    return origin.rstrip("/") in allowed_origins()


def request_allowed(headers) -> bool:
    return host_allowed(headers.get("Host")) and origin_allowed(headers.get("Origin"))
