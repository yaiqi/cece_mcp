"""集团实体 MCP 服务入口。"""

if __name__ == "__main__" and __package__ is None:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.server_factory import SERVICE_CONFIGS, create_mcp
from entities import group

SERVICE_KEY = "group"
ROUTE = SERVICE_CONFIGS[SERVICE_KEY].streamable_http_path
TOOLS = [
    group.resolve_group,
    group.group_detail, group.group_class_count, group.group_companies,
    group.group_finance_graphy, group.group_industry_graphy,
    group.group_qualification_graphy, group.group_risk_events,
    group.group_opportunity_events,
]
TOOL_NAMES = tuple(tool.__name__ for tool in TOOLS)
mcp = create_mcp(SERVICE_KEY)
for tool in TOOLS:
    mcp.add_tool(tool)

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
