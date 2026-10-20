from pathlib import Path

import yaml

from aiwork.profiles import resolve_profile


def test_gateway_profile_sets_env(tmp_path: Path):
    (tmp_path / "mcp-profiles").mkdir()
    (tmp_path / "mcp-profiles" / "gateway-default.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "gateway-default",
                "transport": "gateway",
                "url": "http://127.0.0.1:3000/mcp/http",
                "gateway_profile": "default",
            }
        ),
        encoding="utf-8",
    )
    resolved = resolve_profile(
        root=tmp_path, mcp_profile="gateway-default", skills=[]
    )
    assert resolved.env["AIWORK_MCP_GATEWAY_URL"] == "http://127.0.0.1:3000/mcp/http"
    assert resolved.env["AIWORK_MCP_GATEWAY_PROFILE"] == "default"
