"""创建 Entity MCP 各实体服务的共享配置与 FastMCP 实例。"""

from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP


@dataclass(frozen=True)
class ServiceConfig:
    """单个实体 MCP 服务的运行配置。"""

    name: str
    port: int
    streamable_http_path: str


SERVICE_CONFIGS = {
    "company": ServiceConfig("company-mcp", 8901, "/mcp/company/stream"),
    "group": ServiceConfig("group-mcp", 8902, "/mcp/group/stream"),
    "industry": ServiceConfig("industry-mcp", 8903, "/mcp/industry/stream"),
    "park": ServiceConfig("park-mcp", 8904, "/mcp/park/stream"),
    "person": ServiceConfig("person-mcp", 8905, "/mcp/person/stream"),
    "region": ServiceConfig("region-mcp", 8906, "/mcp/region/stream"),
}


def _instructions(service_key: str) -> str:
    resolver = f"resolve_{service_key}"
    return f"""这是 {SERVICE_CONFIGS[service_key].name}，只提供{service_key}实体相关能力。

实体规则：查询具体实体前必须先调用 `{resolver}`。只有 `{resolver}` 返回“唯一匹配”时，才可将其“标准实体”原样传入查询工具；禁止自行补全名称、猜测 ID 或自动选择候选。

业务状态：消歧工具返回“唯一匹配 / 多候选 / 未匹配 / 调用失败”；查询工具返回“查询成功 / 实体未匹配 / 查询无数据 / 参数不合法 / 无权限 / 调用失败”。“多候选”必须完整展示候选列表并等待用户确认。“实体未匹配”时，可用用户原始输入调用 `{resolver}` 后最多重试一次原查询；“查询无数据”“调用失败”“无权限”不得触发消歧。
"""


def create_mcp(service_key: str) -> FastMCP:
    """按服务标识创建绑定本机地址的 FastMCP 实例。"""
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    config = SERVICE_CONFIGS[service_key]
    return FastMCP(
        config.name,
        instructions=_instructions(service_key),
        host="127.0.0.1",
        port=config.port,
        streamable_http_path=config.streamable_http_path,
    )
