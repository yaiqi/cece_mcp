"""公司实体 MCP 服务入口。"""

from entity_mcp.common.server_factory import SERVICE_CONFIGS, create_mcp
from entity_mcp.entities import company

SERVICE_KEY = "company"
ROUTE = SERVICE_CONFIGS[SERVICE_KEY].streamable_http_path
TOOLS = [
    company.resolve_company,
    company.company_judicial_risk, company.company_operating_risk,
    company.company_registration_info, company.company_ip, company.company_graph,
    company.company_score, company.company_news, company.company_qualification,
    company.company_financials, company.company_business_detail,
    company.company_advanced_search, company.company_finance_summary,
    company.company_finance_events, company.company_credit_and_investment,
]
TOOL_NAMES = tuple(tool.__name__ for tool in TOOLS)
mcp = create_mcp(SERVICE_KEY)
for tool in TOOLS:
    mcp.add_tool(tool)

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
