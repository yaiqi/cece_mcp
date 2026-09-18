"""人物画像（法定代表人/任职/受益所有/实控/持股/关联企业/合作伙伴/人才）MCP 服务入口。"""

if __name__ == "__main__" and __package__ is None:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# from common.auth import create_oauth_provider
from common.server_factory import SERVICE_CONFIGS, create_mcp, get_transport_config, register_tools
from entities import person_insight

SERVICE_KEY = "person_insight"
ROUTE = SERVICE_CONFIGS[SERVICE_KEY].streamable_http_path
# OAUTH_PROVIDER = create_oauth_provider(SERVICE_KEY)
TOOLS = [
    person_insight.get_person_legal,
    person_insight.get_person_office,
    person_insight.get_person_beneficial,
    person_insight.get_person_controller,
    person_insight.get_person_holder,
    person_insight.get_person_union,
    person_insight.get_person_partner,
    person_insight.get_talent_basic,
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
    mcp.run(transport="streamable-http", **get_transport_config("person_insight"))