"""人物实体 MCP 服务入口。"""

if __name__ == "__main__" and __package__ is None:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.server_factory import SERVICE_CONFIGS, create_mcp
from entities import person

SERVICE_KEY = "person"
ROUTE = SERVICE_CONFIGS[SERVICE_KEY].streamable_http_path
TOOLS = [
    person.resolve_person,
    person.person_detail, person.person_legal_representative, person.person_office,
    person.person_beneficial, person.person_controller, person.person_group,
    person.person_union, person.person_partners, person.person_shareholding,
]
TOOL_NAMES = tuple(tool.__name__ for tool in TOOLS)
mcp = create_mcp(SERVICE_KEY)
for tool in TOOLS:
    mcp.add_tool(tool)

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
