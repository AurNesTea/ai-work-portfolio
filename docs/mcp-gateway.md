# MCP Gateway (P3)

This repo does **not** ship a gateway. Point `mcp-profiles/gateway-default.yaml` at a local gateway (e.g. Conduit, mcp-gateway, omni-mcp).

1. Install and authenticate MCP servers once in the gateway.
2. Set `url` (or stdio command, depending on gateway) in the profile.
3. Configure each agent CLI to use **one** MCP endpoint = the gateway.
4. Workflow steps still select `mcp_profile`; `AIWORK_MCP_GATEWAY_*` env vars are set for adapters/audit.

OAuth stays in the gateway / vendor apps — aiwork never stores API keys.
