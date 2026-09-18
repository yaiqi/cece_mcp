"""主体识别（产业分类树/区域选择器树/企业名称识别）MCP 服务入口。"""

if __name__ == "__main__" and __package__ is None:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# from common.auth import create_oauth_provider
from common.server_factory import SERVICE_CONFIGS, create_mcp, get_transport_config, register_tools
from entities import entity_resolve

SERVICE_KEY = "entity_resolve"
ROUTE = SERVICE_CONFIGS[SERVICE_KEY].streamable_http_path
# OAUTH_PROVIDER = create_oauth_provider(SERVICE_KEY)
TOOLS = [
    entity_resolve.get_industry_tree,
    entity_resolve.get_region_tree,
    entity_resolve.search_enterprise_by_name,
    entity_resolve.search_person_by_name,
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
    mcp.run(transport="streamable-http", **get_transport_config("entity_resolve"))