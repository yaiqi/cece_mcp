"""创建 Entity MCP 各实体服务的共享配置与 FastMCP 实例。"""

import os
from dataclasses import dataclass
from functools import wraps

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from common.output_shaping import _clean_output, shape_tool_output


@dataclass(frozen=True)
class ServiceConfig:
    """单个实体 MCP 服务的运行配置。

    resolver 为空时默认使用 `resolve_{service_key}` 作为消歧工具名；
    instructions 为空时使用默认实体规则模板生成，非空时原样使用。
    """

    name: str
    port: int
    streamable_http_path: str
    resolver: str = ""
    instructions: str = ""


SERVICE_CONFIGS = {
    # 行业洞察 MCP 清单（毅达客户）的 4 个独立服务
    "finance": ServiceConfig(
        "finance-mcp", 8907, "/cece-mcp-servers/PEVC/stream",
        instructions=(
            "这是 finance-mcp（创投融资服务），提供基金、融资事件、早期获投企业、"
            "竞品融资差异等查询能力。工具均按筛选条件直接检索，不需要消歧前置；"
            "日期格式统一为 yyyy-MM-dd，区域名称用中文（如\"江苏省\"），产业名称"
            "用中文（如\"人工智能\"）。返回状态遵循：查询成功 / 查询无数据 / 参数"
            "不合法 / 调用失败。"
        ),
    ),
    "enterprise": ServiceConfig(
        "enterprise-mcp", 8908, "/cece-mcp-servers/enterprise/stream",
        instructions=(
            "这是 enterprise-mcp（企业服务），提供企业标签、工商信息、股东、"
            "主要人员/董监高、各类融资（创投/股票/债券/银行借款/应收账款/租赁/"
            "信托/授信/债券持有人/对外投资）、企业关系图谱、融资图谱、招投标等"
            "查询能力。\n\n"
            "实体规则：上游企业接口只认工商登记全称，查询前请先用主体识别服务"
            "（entity-resolve-mcp）的 `search_enterprise_by_name` 把企业简称/"
            "品牌解析成工商全称，再以全称调用本服务工具；禁止自行猜测名称。\n\n"
            "业务状态：查询工具返回“查询成功 / 实体未匹配 / 查询无数据 / 参数"
            "不合法 / 无权限 / 调用失败”。“实体未匹配”时，可用用户原始输入调用"
            " `search_enterprise_by_name` 后最多重试一次原查询；“查询无数据”"
            "“调用失败”“无权限”不得触发消歧。"
        ),
    ),
    "person_insight": ServiceConfig(
        "person-insight-mcp", 8909, "/cece-mcp-servers/person/stream",
        resolver="resolve_person",
    ),
    "entity_resolve": ServiceConfig(
        "entity-resolve-mcp", 8910, "/cece-mcp-servers/NER/stream",
        instructions=(
            "这是 entity-resolve-mcp（主体识别服务），提供产业分类树、区域选择器树"
            "和企业名称识别（企业全称解析）三类能力。企业名称识别工具支持简称/"
            "品牌/模糊名称，返回工商全称与 companyId，供企业/创投融资类查询工具"
            "作为入参使用；产业/区域树用于把用户口述的产业、地区转换成标准代码"
            "或路径。返回状态遵循：查询成功 / 查询无数据 / 参数不合法 / 调用失败。"
        ),
    ),
}


def _instructions(service_key: str) -> str:
    config = SERVICE_CONFIGS[service_key]
    if config.instructions:
        return config.instructions
    resolver = config.resolver or f"resolve_{service_key}"
    return f"""这是 {config.name}，只提供{service_key}实体相关能力。

实体规则：查询具体实体前必须先调用 `{resolver}`。只有 `{resolver}` 返回“唯一匹配”时，才可将其“标准实体”原样传入查询工具；禁止自行补全名称、猜测 ID 或自动选择候选。

业务状态：消歧工具返回“唯一匹配 / 多候选 / 未匹配 / 调用失败”；查询工具返回“查询成功 / 实体未匹配 / 查询无数据 / 参数不合法 / 无权限 / 调用失败”。“多候选”必须完整展示候选列表并等待用户确认。“实体未匹配”时，可用用户原始输入调用 `{resolver}` 后最多重试一次原查询；“查询无数据”“调用失败”“无权限”不得触发消歧。
"""


def create_mcp(service_key: str) -> FastMCP:
    """按服务标识创建 FastMCP 实例。

    host/port 等传输参数通过 get_transport_config 获取，调用方在 run 时传入。
    """
    config = SERVICE_CONFIGS[service_key]
    return FastMCP(
        config.name,
        instructions=_instructions(service_key),
    )


def get_transport_config(service_key: str) -> dict:
    """获取 transport_kwargs：host、port、path、json_response 等。
    用于 mcp.run(transport="streamable-http", **get_transport_config(key))。
    """
    config = SERVICE_CONFIGS[service_key]
    return {
        "host": os.getenv("MCP_HOST", "0.0.0.0"),
        "port": config.port,
        "path": config.streamable_http_path,
        "json_response": True,
    }


_ERROR_STATUS_CODES = {"调用失败", "查询无数据", "实体未匹配", "参数不合法", "无权限"}


def _is_error_result(result: dict) -> str | None:
    """检查 dict 是否为错误返回，是则返回错误摘要，否则返回 None。"""
    code = result.get("状态码")
    if code in _ERROR_STATUS_CODES:
        return result.get("摘要", code)
    if result.get("status") == "error":
        return result.get("error_message") or result.get("摘要", "调用失败")
    return None


def register_tools(mcp: FastMCP, tools: list) -> None:
    """注册工具并在 MCP 边界统一整形出参（替代手工 for 循环 add_tool）：
    信封清理、ID 剔除、英文键翻译、拍平（最多 3 层）、按工具功能筛选字段。
    错误状态码自动转换为 MCP ToolExecutionError（isError=true）。"""
    for tool in tools:

        @wraps(tool)
        async def wrapper(*args, _tool=tool, **kwargs):
            result = await _tool(*args, **kwargs)
            if isinstance(result, dict):
                err_msg = _is_error_result(result)
                if err_msg:
                    raise ToolError(err_msg)
            return shape_tool_output(result, _tool.__name__)

        mcp.add_tool(wrapper)
