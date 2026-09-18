"""企业服务（标签/工商/融资/图谱/招投标）MCP 服务入口。"""

if __name__ == "__main__" and __package__ is None:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# from common.auth import create_oauth_provider
from common.server_factory import SERVICE_CONFIGS, create_mcp, get_transport_config, register_tools
from entities import enterprise

SERVICE_KEY = "enterprise"
ROUTE = SERVICE_CONFIGS[SERVICE_KEY].streamable_http_path
# OAUTH_PROVIDER = create_oauth_provider(SERVICE_KEY)
TOOLS = [
    enterprise.get_enterprise_tags,
    enterprise.get_enterprise_basic,
    enterprise.get_enterprise_shareholders,
    enterprise.get_enterprise_management,
    enterprise.get_enterprise_VCPE_financing,
    enterprise.get_enterprise_stock_financing,
    enterprise.get_enterprise_bond_financing,
    enterprise.get_enterprise_bondHolder,
    enterprise.get_enterprise_bank_financing,
    enterprise.get_enterprise_receivables_financing,
    enterprise.get_enterprise_leasing_financing,
    enterprise.get_enterprise_trust_financing,
    enterprise.get_enterprise_credit_financing,
    enterprise.get_enterprise_outbound_investment,
    enterprise.get_company_graphy,
    enterprise.get_businessFinance_graphy,
    enterprise.get_query_winTenderer_tenderee,
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
    #
    # asyncio.run(_init())
    mcp.run(transport="streamable-http", **get_transport_config("enterprise"))