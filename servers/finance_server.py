"""创投融资（基金融资事件/早期获投企业/竞品融资）MCP 服务入口。"""

if __name__ == "__main__" and __package__ is None:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# from common.auth import create_oauth_provider
from common.server_factory import SERVICE_CONFIGS, create_mcp, get_transport_config, register_tools
from entities import finance

SERVICE_KEY = "finance"
ROUTE = SERVICE_CONFIGS[SERVICE_KEY].streamable_http_path
# OAUTH_PROVIDER = create_oauth_provider(SERVICE_KEY)
TOOLS = [
    finance.search_financing_companies,
    finance.get_industryFund_list,
    finance.search_industryFund_investmen_list,
    finance.get_industryFund_exit_list,
    finance.get_fund_detail_basic,
    finance.get_fund_detail_investor_list,
    finance.get_fund_detail_investment_list,
    finance.get_fund_detail_exit_list,
    finance.get_query_competitive_Finance,
]
TOOL_NAMES = tuple(tool.__name__ for tool in TOOLS)
# mcp = create_mcp(SERVICE_KEY, auth_provider=OAUTH_PROVIDER)
mcp = create_mcp(SERVICE_KEY)
register_tools(mcp, TOOLS)

if __name__ == "__main__":
    # import asyncio
    # from common.auth import register_static_client
    #
    # async def _init():
    #     await register_static_client(OAUTH_PROVIDER, client_id="zjs_test", client_secret="123456")
    #     print("Static client registered: zjs_test / 123456")
    #
    # asyncio.run(_init())
    mcp.run(transport="streamable-http", **get_transport_config("finance"))