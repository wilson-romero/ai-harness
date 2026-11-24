"""A synthetic MCP server written with the official SDK's MCPServer (interoperability check).

The lifecycle tests use the standard-library server next to this one, whose misbehaviours
are deterministic; this one proves the harness speaks to the SDK's own server. Synthetic data.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

server = MCPServer("synthetic-sdk")


@server.tool()
def get_project_metadata(project: str) -> dict:
    """Devuelve metadatos sinteticos de un proyecto de demostracion."""
    return {"project": project, "name": "Demo Alpha (SDK)", "status": "activo"}


if __name__ == "__main__":
    server.run("stdio")
