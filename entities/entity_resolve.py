"""主体识别 Sever（行业洞察 MCP 清单 - 主体识别sever.csv）工具实现。

四个工具都是"把用户口述的自然语言主体转成标准主体/代码"的检索类工具：
- get_industry_tree：产业分类树（向量库 + 简称字典，中文关键词 -> 节点代码/名称/产业链/类型）；
- get_region_tree：区域选择器树（Dify 地址打标工作流，地址关键词 -> 区域节点）；
- search_enterprise_by_name：企业名称识别（Dify 企业名称工作流，简称 -> 全称 + 编号）。
- search_person_by_name：人物名称搜索（ES 人物库，昵称/姓名 -> 人物编号/名称/角色分布）。

本模块还提供 resolve_industry_code（产业名 -> 产业代码）给 finance 等模块复用。

产业/区域功能通过 Dify 工作流服务（http://172.20.28.224/v1/workflows/run）实现。
人物搜索功能通过网关 API 实现。
"""

import asyncio
import httpx
import json
import os
from pathlib import Path

import dashscope
from dashscope import TextEmbedding
from pymilvus import connections, Collection

from common.api_client import api_post
from common.business_protocol import call_failed, multiple_candidates, no_match, unique_match

_DIFY_BASE = "http://172.20.28.224/v1/workflows/run"
_ENTERPRISE_APP_KEY = "app-EyvL0XZNESrqjAGH2LtMzZXG"
_INDUSTRY_APP_KEY = "app-j83SzkWnHWzxrJslwBgEKfbN"
_REGION_APP_KEY = "app-BuDh10T8bFEsIq2S1i0FoV4t"

_INDUSTRY_TYPES = ("SELECTED", "CSF", "NSEI", "GB", "DE")

# Milvus / DashScope 配置
_MILVUS_HOST = "172.29.19.25"
_MILVUS_PORT = 19530
_MILVUS_DB = "MCP_NER"
_MILVUS_USER = "root"
_MILVUS_PASSWORD = "nihuan@0612"
_COLLECTION_NAME = "industry_search"
_EMBEDDING_MODEL = "text-embedding-v4"
_EMBEDDING_DIM = 1024

# 是否已加载 DashScope API Key
_DASHSCOPE_LOADED = False

# 产业简称字典
_DICT_PATH = Path(__file__).resolve().parents[2] / "工具搭建" / "产业简称_code字典.json"
_ALIAS_MAP: dict[str, str] = {}

# tp 值 -> 中文类型映射
_TP_LABEL = {
    "1": "标准产业链",
    "2": "国战新产业链",
    "3": "国标产业链",
    "5": "特色产业链",
    "6": "数字经济产业链",
}


def _load_alias_map() -> None:
    global _ALIAS_MAP
    if _ALIAS_MAP:
        return
    try:
        path = Path(__file__).resolve().parents[3] / "工具搭建" / "产业简称_code字典.json"
        if path.exists():
            with open(path, encoding="utf-8") as f:
                _ALIAS_MAP = json.load(f)
    except (OSError, ValueError):
        _ALIAS_MAP = {}


def _ensure_dashscope() -> None:
    global _DASHSCOPE_LOADED
    if _DASHSCOPE_LOADED:
        return
    api_key = os.getenv("DASHSCOPE_API_KEY") or "sk-ed1d31448f2c461492da19441b4dcf88"
    dashscope.api_key = api_key
    _DASHSCOPE_LOADED = True


def _get_embedding(text: str) -> list[float]:
    _ensure_dashscope()
    resp = TextEmbedding.call(model=_EMBEDDING_MODEL, input=[text])
    if resp.status_code != 200:
        raise RuntimeError(f"Embedding API error: {resp.code} - {resp.message}")
    return resp.output["embeddings"][0]["embedding"]


async def _search_milvus(vector: list[float], limit: int = 10) -> list[dict]:
    """异步搜索 Milvus，返回 [{code, name, tp, chain, score}]"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _search_milvus_sync, vector, limit)


def _search_milvus_sync(vector: list[float], limit: int = 10) -> list[dict]:
    connections.connect(
        host=_MILVUS_HOST, port=_MILVUS_PORT, db_name=_MILVUS_DB,
        user=_MILVUS_USER, password=_MILVUS_PASSWORD,
    )
    try:
        collection = Collection(_COLLECTION_NAME)
        collection.load()
        results = collection.search(
            data=[vector],
            anns_field="vector",
            param={"metric_type": "COSINE", "params": {"nprobe": 16}},
            limit=limit,
            output_fields=["code", "name", "tp", "chain"],
        )
        nodes = []
        for hit in results[0]:
            nodes.append({
                "code": hit.entity.get("code") or "",
                "name": hit.entity.get("name") or "",
                "tp": hit.entity.get("tp") or "",
                "chain": hit.entity.get("chain") or "",
                "score": hit.score,
            })
        return nodes
    finally:
        connections.disconnect("default")


def _has_cjk(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in text)


async def _dify_call(app_key: str, inputs: dict) -> dict:
    """调用 Dify 工作流服务，返回 outputs 字典。"""
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            _DIFY_BASE,
            headers={"Authorization": f"Bearer {app_key}", "Content-Type": "application/json"},
            json={"inputs": inputs, "response_mode": "blocking", "user": "mcp"},
        )
        resp.raise_for_status()
        body = resp.json()
        data = body.get("data") or {}
        if data.get("status") not in ("succeeded", "partial-succeeded"):
            error = data.get("error") or "Dify 工作流执行失败"
            return {"status": "error", "error_message": error, "状态码": "调用失败", "摘要": error}
        outputs = data.get("outputs") or {}
        if outputs is None:
            outputs = {}
        return outputs


async def resolve_industry_code(
    name_or_code: str, industry_type: str = "SELECTED"
) -> tuple[str | None, dict | None]:
    """产业名 -> 产业代码：不含中文字符的直接当 industryCode 用；否则调
    Dify 产业打标工作流，精确同名且唯一，或候选只有一条时自动采用。

    Returns:
        (industry_code, None) —— 解析成功
        (None, error_dict) —— 解析失败/候选不唯一
    """
    if industry_type not in _INDUSTRY_TYPES:
        return None, {
            "status": "error",
            "error_message": f"industry_type 不认识：{industry_type}，可选：{list(_INDUSTRY_TYPES)}",
        }
    if not name_or_code:
        return None, {"status": "error", "error_message": "industry_name_or_code 不能为空"}
    if not _has_cjk(name_or_code):
        return name_or_code, None

    outputs = await _dify_call(_INDUSTRY_APP_KEY, {"industry": name_or_code})
    if outputs.get("status") == "error":
        return None, outputs

    result = outputs.get("result") or []
    candidates = [{"name": r.get("name"), "code": r.get("id")} for r in result if isinstance(r, dict)]
    if not candidates:
        return None, {
            "status": "ambiguous",
            "message": f"没找到与'{name_or_code}'匹配的产业节点。",
            "candidates": [],
        }

    exact = [c for c in candidates if c.get("name") == name_or_code]
    if len(exact) == 1:
        return exact[0].get("code"), None
    if len(candidates) == 1:
        return candidates[0].get("code"), None

    pool = exact if exact else candidates
    return None, {
        "status": "ambiguous",
        "message": f"'{name_or_code}'匹配到 {len(candidates)} 个产业节点，无法自动确定。",
        "candidates": pool[:20],
    }


async def get_industry_tree(keyword: str, industry_type: str = "SELECTED") -> dict:
    """获取产业分类树：按产业关键词检索产业节点，返回节点代码、名称、产业链和类型。

    通过产业简称字典精确匹配 + Milvus 向量库语义搜索，合并排序后返回 Top 5。

    Args:
        keyword: 产业关键词，如"新能源汽车""人工智能"。
        industry_type: 保留参数，当前未使用。

    Returns:
        状态码 及 数据（成功时，数据.matchList 为匹配节点列表）或 error_message。
        每个节点包含 code（产业代码）、name（产业名称）、chain（产业链路）、
        type（产业类型：标准产业链/国战新产业链/国标产业链/特色产业链/数字经济产业链）。
    """
    if not keyword:
        return {
            "status": "error",
            "error_message": "keyword 必填，请提供产业关键词。",
        }

    _load_alias_map()

    # 步骤 2：简称字典精确匹配
    exact_code = _ALIAS_MAP.get(keyword)

    # 步骤 3：向量查询
    try:
        vector = _get_embedding(keyword)
        vector_results = await _search_milvus(vector, limit=10)
    except Exception as e:
        return {
            "status": "error",
            "error_message": f"向量查询失败：{e}",
            "状态码": "调用失败",
            "摘要": f"向量查询失败：{e}",
        }

    # 步骤 4：合并结果 + 打分
    scored = []
    for node in vector_results:
        score = node["score"]
        # 如果精确匹配结果在向量结果中，+5
        if exact_code and (node["code"] == exact_code or node["name"] == keyword):
            score += 5
        # tp=5 加权 *1.5
        if node["tp"] == "5":
            score *= 1.5
        scored.append({
            "code": node["code"],
            "name": node["name"],
            "chain": node["chain"],
            "type": _TP_LABEL.get(node["tp"], ""),
            "score": score,
        })

    # 如果精确匹配结果不在向量结果中，也加入
    if exact_code and not any(n["code"] == exact_code or n["name"] == keyword for n in vector_results):
        scored.append({
            "code": exact_code,
            "name": keyword,
            "chain": "",
            "type": "",
            "score": 5,
        })

    # 按分数降序排列，取 top 5
    scored.sort(key=lambda x: x["score"], reverse=True)
    top5 = scored[:5]

    # 移除内部 score 字段
    nodes = [{k: v for k, v in n.items() if k != "score"} for n in top5]

    return {
        "status": "success",
        "data": {"matchList": nodes},
        "状态码": "查询成功",
        "摘要": f"查询成功，共返回 {len(nodes)} 个匹配产业节点。",
        "数据": {"matchList": nodes},
    }


async def get_region_tree(keyword: str = "") -> dict:
    """获取区域选择器树：通过 Dify 地址打标工作流实现。

    Args:
        keyword: 区域关键词，如"江苏省南京市"。

    Returns:
        状态码 及 数据（成功时，数据.tree 为区域节点列表）或 error_message。
    """
    if not keyword:
        return {
            "status": "error",
            "error_message": "keyword 必填，请提供区域关键词。",
        }
    outputs = await _dify_call(_REGION_APP_KEY, {"address": keyword})
    if outputs.get("status") == "error":
        return outputs
    result = outputs.get("output") or []
    nodes = [{"name": r.get("name"), "code": r.get("code"), "level": r.get("level")} for r in result if isinstance(r, dict)]
    if not nodes:
        return no_match("区域", keyword)
    return {
        "status": "success",
        "data": {"tree": nodes},
        "状态码": "查询成功",
        "摘要": f"查询成功，命中 {len(nodes)} 个区域节点。",
        "数据": {"tree": nodes},
    }


async def search_enterprise_by_name(query: str) -> dict:
    """按名称搜索企业：把企业简称/品牌解析为工商全称和 companyId。

    通过 Dify 企业名称识别工作流实现。

    Args:
        query: 企业简称、品牌或名称关键词，如"比亚迪""宁德时代"。

    Returns:
        唯一匹配（含 company_name/company_id）或多候选/未匹配/调用失败。
    """
    outputs = await _dify_call(_ENTERPRISE_APP_KEY, {"short_name": query})
    if outputs.get("status") == "error":
        msg = outputs.get("error_message", "企业名称识别调用失败。")
        return call_failed(msg)

    full_name = outputs.get("full_name") or outputs.get("company_name") or ""
    company_id = outputs.get("company_id") or outputs.get("companyId") or ""

    if full_name:
        return unique_match("企业", query, {"company_name": str(full_name), "company_id": str(company_id)})

    candidates = outputs.get("candidates") or []
    if not candidates:
        return no_match("企业", query)

    exact = [c for c in candidates if c.get("name") == query or c.get("companyName") == query]
    if len(exact) == 1:
        name = exact[0].get("name") or exact[0].get("companyName")
        return unique_match("企业", query, {"company_name": name, "company_id": ""})
    return multiple_candidates("企业", query, candidates[:20])


async def search_person_by_name(keyword: str, page: int = 1, page_size: int = 10) -> dict:
    """按名称搜索人物：输入人名或昵称，返回多个人物名称及相关信息。

    通过 ES 人物库接口检索，返回人物编号、名称、关联企业数、合作伙伴数、
    角色数量分布（法人/实控人/受益所有人/股东/董监高）、区域分布及代表企业。

    Args:
        keyword: 人物姓名或昵称，如"雷军""程一笑"。
        page: 页码，默认 1。
        page_size: 每页条数，默认 10。

    Returns:
        状态码 及 数据（成功时，数据.matchList 为人物列表）或 error_message。
        每个人物包含：no（人物编号）、name（人物名称）、companyAmount（关联
        企业总数）、partnerAmount（合作伙伴数）、roleBreakdown（角色数量分布）、
        regionDistribution（区域分布，含代表企业）。
    """
    if not keyword:
        return {
            "status": "error",
            "error_message": "keyword 必填，请提供人物关键词。",
        }

    resp = await api_post(
        "/cmp/person/list",
        {
            "personName": keyword,
            "pageNow": page,
            "pageSize": page_size,
            "regionInfo": [],
            "categorys": [],
        },
    )
    if not resp.get("success"):
        return {
            "status": "error",
            "error_message": resp.get("msg", "人物搜索接口调用失败。"),
            "状态码": "调用失败",
            "摘要": resp.get("msg", "人物搜索接口调用失败。"),
        }

    data = resp.get("data") or {}
    items = data.get("datas") or []
    if not items:
        return {
            "status": "success",
            "data": {"matchList": []},
            "状态码": "查询无数据",
            "摘要": f"未找到与'{keyword}'匹配的人物。",
            "数据": {"matchList": []},
        }

    nodes = []
    for item in items:
        if not isinstance(item, dict):
            continue
        role_map = {
            "categoryOneAmount": "法人数量",
            "categoryTwoAmount": "实控人数量",
            "categoryThereAmount": "受益所有人数量",
            "categoryFourAmount": "股东数量",
            "categoryFiveAmount": "董监高数量",
        }
        roles = {}
        for src_key, label in role_map.items():
            val = item.get(src_key)
            if val and int(val) > 0:
                roles[label] = int(val)

        regions = []
        for region in (item.get("cityGroupList") or []):
            if isinstance(region, dict) and region.get("name"):
                regions.append({
                    "name": region.get("name"),
                    "amount": region.get("amount", 0),
                    "representative": region.get("companyName") or "",
                })

        node = {
            "no": item.get("no") or "",
            "name": item.get("name") or "",
            "companyAmount": item.get("companyAmount", 0),
            "partnerAmount": item.get("partnerAmount", 0),
        }
        if roles:
            node["roleBreakdown"] = roles
        if regions:
            node["regionDistribution"] = regions
        nodes.append(node)

    result = {
        "status": "success",
        "data": {"matchList": nodes, "total": data.get("total", 0)},
        "状态码": "查询成功",
        "摘要": f"查询成功，共返回 {len(nodes)} 个匹配人物。",
        "数据": {"matchList": nodes, "total": data.get("total", 0)},
    }
    return result