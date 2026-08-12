"""产业实体 MCP 服务入口。"""

from entity_mcp.common.server_factory import SERVICE_CONFIGS, create_mcp
from entity_mcp.entities import industry

SERVICE_KEY = "industry"
ROUTE = SERVICE_CONFIGS[SERVICE_KEY].streamable_http_path
TOOLS = [
    industry.resolve_industry,
    industry.industry_score, industry.industry_score_comparison,
    industry.industry_concentration, industry.industry_company_portrait,
    industry.industry_financial_trend, industry.industry_company_financial,
    industry.industry_innovation,
]
TOOL_NAMES = tuple(tool.__name__ for tool in TOOLS)
mcp = create_mcp(SERVICE_KEY)
for tool in TOOLS:
    mcp.add_tool(tool)

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
