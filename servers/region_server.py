"""区域实体 MCP 服务入口。"""

if __name__ == "__main__" and __package__ is None:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.server_factory import SERVICE_CONFIGS, create_mcp
from entities import region

SERVICE_KEY = "region"
ROUTE = SERVICE_CONFIGS[SERVICE_KEY].streamable_http_path
TOOLS = [
    region.resolve_region,
    region.region_score, region.region_company_stats, region.region_patent_stats,
    region.region_fourteenth_five_year_industries, region.region_finance_summary,
    region.region_finance_distribution, region.region_finance_trend,
    region.region_finance_by_subregion, region.region_finance_top_companies,
    region.region_finance_events, region.region_company_search, region.region_park_list,
    region.region_park_distribution, region.region_park_statistics,
    region.region_development_zone_list,
    region.region_macro_portrait, region.region_macro_key_indicators,
    region.region_social_financing,
]
TOOL_NAMES = tuple(tool.__name__ for tool in TOOLS)
mcp = create_mcp(SERVICE_KEY)
for tool in TOOLS:
    mcp.add_tool(tool)

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
