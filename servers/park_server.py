"""园区实体 MCP 服务入口。"""

from entity_mcp.common.server_factory import SERVICE_CONFIGS, create_mcp
from entity_mcp.entities import park

SERVICE_KEY = "park"
ROUTE = SERVICE_CONFIGS[SERVICE_KEY].streamable_http_path
TOOLS = [
    park.resolve_park,
    park.park_detail, park.park_sub_parks, park.park_industry_distribution,
    park.park_company_features, park.park_companies,
]
TOOL_NAMES = tuple(tool.__name__ for tool in TOOLS)
mcp = create_mcp(SERVICE_KEY)
for tool in TOOLS:
    mcp.add_tool(tool)

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
