"""Entity MCP 面向 Agent 的中文业务状态返回合同。"""


def _response(status_code: str, summary: str, **fields: object) -> dict:
    return {"状态码": status_code, "摘要": summary, **fields}


def unique_match(entity_type: str, query: str, entity_ref: dict) -> dict:
    return _response("唯一匹配", f"已唯一识别{entity_type}主体。", 检索关键字=query, 标准实体=entity_ref)


def multiple_candidates(entity_type: str, query: str, candidates: list[dict]) -> dict:
    return _response("多候选", f"命中多个{entity_type}主体，无法自动确定，请用户确认。", 检索关键字=query, 候选列表=candidates)


def no_match(entity_type: str, query: str) -> dict:
    return _response("未匹配", f"未匹配到{entity_type}主体，请检查关键词后重试。", 检索关键字=query, 候选列表=[])


def entity_not_matched(entity_type: str, raw_input: str) -> dict:
    return _response("实体未匹配", f"未匹配到{entity_type}主体，请调用对应实体消歧工具获取候选。", 原始输入=raw_input)


def query_success(data: object) -> dict:
    return _response("查询成功", "查询成功。", 数据=data)


def no_data(summary: str) -> dict:
    return _response("查询无数据", summary, 数据=[])


def call_failed(summary: str) -> dict:
    return _response("调用失败", summary)
