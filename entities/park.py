"""园区信息查询工具。

先用 ``resolve_park`` 获取并确认标准园区实体，再将其原样传入查询工具。
查询所需的园区 ID、ZJS 园区 ID 及名称均由 ``ParkRef`` 提供。
"""

from collections.abc import Callable
from typing import Any

from common.api_client import api_post, unwrap
from common.milvus_client import resolve_entity
from common.business_protocol import 唯一匹配, 多候选, 未匹配, 调用失败
from models.entity_refs import ParkRef


def _数值(value: object) -> int | float | object:
    if not isinstance(value, str):
        return value
    try:
        number = float(value)
    except ValueError:
        return value
    return int(number) if number.is_integer() else number


def _园区详情数据(raw: dict) -> dict:
    """将园区详情接口字段转换为面向 MCP 调用方的业务字段。"""
    address = raw.get("parkAddr")
    industries = raw.get("leadingIndsy")
    area = raw.get("parkArea")
    area_unit = raw.get("areaUnit")
    area_text = f"{_数值(area)}{area_unit or ''}" if area is not None else None
    return {
        "园区名称": raw.get("parkName"),
        "园区级别": raw.get("parkClass"),
        "园区类型": raw.get("parkType"),
        "所在地": "".join(filter(None, (raw.get("province"), raw.get("city"), raw.get("district")))) or None,
        "地址": address.strip() if isinstance(address, str) and address.strip() else None,
        "面积": area_text,
        "主导产业": [item for item in industries.split("|") if item] if isinstance(industries, str) else [],
        "企业数量": raw.get("companyCount"),
        "子园区数量": raw.get("sonParkCount"),
        "经纬度": {"经度": _数值(raw.get("lng")), "纬度": _数值(raw.get("lat"))} if raw.get("lng") is not None and raw.get("lat") is not None else None,
        "获批时间": raw.get("approvalTime"),
    }


def _去除内部标识字段(data: Any) -> Any:
    """递归移除仅供后端关联使用的 ID 与 code 字段，其余字段原样保留。"""
    if isinstance(data, list):
        return [_去除内部标识字段(item) for item in data]
    if not isinstance(data, dict):
        return data
    return {
        key: _去除内部标识字段(value)
        for key, value in data.items()
        if key not in {"id", "code"}
        and not key.endswith(("_id", "_code", "Id", "Code"))
    }


def _带单位(value: object, unit: str) -> str | None:
    if value is None:
        return None
    return f"{_数值(value)}{unit}"


def _第一个非空值(*values: object) -> object:
    return next((value for value in values if value is not None), None)


def _子园区列表数据(raw: object) -> list[dict]:
    """保留子园区名称及企业数量，移除空白的园区详情字段。"""
    if not isinstance(raw, list):
        return []
    return [
        {
            "子园区名称": item.get("parkName"),
            "子园区内企业数量": _带单位(item.get("companyCount"), "家"),
        }
        for item in raw
        if isinstance(item, dict)
    ]


def _产业分布数据(raw: object) -> list[dict]:
    """将产业分布转换为产业名称和占比的扁平列表。"""
    if not isinstance(raw, list):
        return []
    result = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        result.append({
            "产业名称": item.get("industryName") or item.get("name"),
            "占比": _带单位(_第一个非空值(item.get("ratio"), item.get("proportion"), item.get("percent")), "%"),
        })
    return result


def _企业数量统计数据(raw: object) -> dict:
    """将企业分类统计压缩为“分类名称: 数量家”。"""
    if not isinstance(raw, dict):
        return {}
    return {
        name: _带单位(value.get("count"), "家") if isinstance(value, dict) else _带单位(value, "家")
        for name, value in raw.items()
    }


def _企业特征分布数据(raw: object) -> dict:
    """将四个企业特征维度压缩为“类别: 占比%”。"""
    if not isinstance(raw, dict):
        return {}
    dimensions = {
        "regcap": "注册资本",
        "model": "企业规模",
        "time": "成立年限",
        "type": "企业性质",
    }
    result = {}
    for source_key, display_name in dimensions.items():
        entries = raw.get(source_key)
        if not isinstance(entries, list):
            continue
        result[display_name] = {
            str(item.get("name") or item.get("label") or item.get("typeName")): _带单位(
                _第一个非空值(
                    item.get("ratio"),
                    item.get("proportion"),
                    item.get("percent"),
                    item.get("value"),
                ),
                "%",
            )
            for item in entries
            if isinstance(item, dict)
        }
    return result


def _园区企业列表数据(raw: object) -> dict:
    """仅保留园区企业列表中适合回答的业务字段。"""
    if isinstance(raw, dict):
        total_count = raw.get("totalCount")
        companies = raw.get("list") or raw.get("rows") or []
    elif isinstance(raw, list):
        total_count = len(raw)
        companies = raw
    else:
        return {"企业总数": 0, "企业列表": []}

    return {
        "企业总数": total_count,
        "企业列表": [
            {
                "企业名称": item.get("companyName"),
                "注册资本": "".join(
                    str(value)
                    for value in (item.get("registCapiValue"), item.get("registCapiUnit"))
                    if value is not None
                ) or None,
                "所在地": "".join(filter(None, (item.get("province"), item.get("city"), item.get("district")))) or None,
                "注册资本信息": item.get("registeredCapital"),
                "经营状态": item.get("status"),
                "企业类型": item.get("companyType"),
            }
            for item in companies
            if isinstance(item, dict)
        ],
    }


def _园区查询结果(
    result: dict,
    成功摘要: str,
    数据转换: Callable[[dict], dict] | None = None,
) -> dict:
    """统一园区查询工具的 MCP 返回契约。"""
    if result.get("status") != "success":
        return {"状态": "调用失败", "摘要": result.get("error_message", "接口调用失败")}
    data = result.get("data")
    if data is None:
        return {"状态": "查询无数据", "摘要": "查询成功，但未返回相关数据。", "数据": []}
    if 数据转换 is not None:
        data = 数据转换(data)
    data = _去除内部标识字段(data)
    return {"状态": "查询成功", "摘要": 成功摘要, "数据": data}


async def _resolve_park(name_or_id: str) -> tuple[dict | None, dict | None]:
    """消歧落脚点：园区没有能直接识别的固定ID格式（park_id 是一串 hex，
    zjs_park_id 才是 ZJS_PARK_xxx 格式，两个都不是人会直接输入的东西），
    所以统一走 Milvus 语义检索，一次性拿回 park_id/zjs_park_id/park_name
    三个字段。

    Returns:
        (park_fields, None) —— park_fields = {"park_id":..., "zjs_park_id":..., "park_name":...}
        (None, ambiguous_dict)
    """
    result = await resolve_entity(
        collection_name="park_name_embedding",
        embedding_field="embedding_name",
        output_fields=["park_id", "zjs_park_id", "park_name"],
        query_text=name_or_id,
    )
    if result["status"] == "resolved":
        return result["fields"], None
    candidates = [
        {key: value for key, value in candidate.items() if key != "score"}
        for candidate in result["candidates"]
    ]
    return None, {
        "status": "ambiguous",
        "message": f"没能唯一确定'{name_or_id}'对应哪个园区，请从候选里确认。",
        "candidates": candidates,
    }


async def resolve_park(query: str) -> dict:
    """识别园区并返回标准园区实体或候选列表。

    Args:
        query: 园区名称、简称或其他识别线索。

    Returns:
        唯一匹配时返回可直接传给园区查询工具的标准实体；多候选时返回候选列表。
    """
    try:
        park, result = await _resolve_park(query)
    except Exception:
        return 调用失败("园区实体识别服务暂不可用，请稍后重试。")
    if result:
        if result.get("status") == "ambiguous":
            candidates = result.get("candidates", [])
            return 多候选("园区", query, candidates) if candidates else 未匹配("园区", query)
        return 调用失败(result.get("error_message", "园区消歧调用失败。"))
    return 唯一匹配("园区", query, park)


async def _get_park_detail_raw(park: dict) -> dict | None:
    """内部专用：拿完整详情（含 companyCount/province），给其他工具做依赖链用。"""
    resp = await api_post(
        "/idis_industry/teis/park/parkdetail",
        {
            "parkId": park["park_id"],
            "zjsParkId": park["zjs_park_id"],
            "addrType": 0,
            "parkName": park["park_name"],
        },
    )
    result = unwrap(resp)
    if result["status"] != "success":
        return None
    return result["data"]


async def park_detail(park_ref: ParkRef) -> dict:
    """查询园区基本信息：级别、类型、面积、主导产业、企业总数、地理位置。

    Args:
        park_ref: 由 ``resolve_park`` 返回并确认的标准园区实体。

    Returns:
        园区基本信息；查询失败时返回对应业务状态。
    """
    data = await _get_park_detail_raw(park_ref)
    if data is None:
        return {"状态": "调用失败", "摘要": "园区基本信息查询失败。"}
    return _园区查询结果(
        {"status": "success", "data": data},
        f"已查询到{data.get('parkName', park_ref['park_name'])}的基本信息。",
        _园区详情数据,
    )


async def park_sub_parks(park_ref: ParkRef) -> dict:
    """查询某个园区的子园区列表。

    Args:
        park_ref: 由 ``resolve_park`` 返回并确认的标准园区实体。

    Returns:
        子园区列表；查询失败时返回对应业务状态。
    """
    resp = await api_post(
        "/idis_industry/teis/park/sonpark",
        {"zjsParkId": park_ref["zjs_park_id"], "addrType": 0, "parkName": park_ref["park_name"]},
    )
    return _园区查询结果(unwrap(resp), "已查询到子园区列表。", _子园区列表数据)


async def park_industry_distribution(park_ref: ParkRef) -> dict:
    """查询园区内各产业的企业数量占比分布。

    Args:
        park_ref: 由 ``resolve_park`` 返回并确认的标准园区实体。

    Returns:
        园区产业分布；查询失败时返回对应业务状态。
    """
    detail = await _get_park_detail_raw(park_ref)
    if detail is None:
        return {"状态": "调用失败", "摘要": "查询园区详情失败，无法获取企业总数。"}
    resp = await api_post(
        "/idis_industry/teis/park/industrydistribution",
        {
            "companyCount": detail.get("companyCount", 0),
            "industryChainType": "标准产业",
            "parkId": park_ref["park_id"],
            "parkName": park_ref["park_name"],
            "province": detail.get("province", ""),
            "addrType": 0,
            "zjsParkId": park_ref["zjs_park_id"],
        },
        params={"companyType": "全部企业"},
    )
    return _园区查询结果(unwrap(resp), "已查询到园区产业分布。", _产业分布数据)


async def park_company_features(park_ref: ParkRef) -> dict:
    """查询园区内企业特征分布（注册资本、规模、成立时间、类型四个维度占比）。

    Args:
        park_ref: 由 ``resolve_park`` 返回并确认的标准园区实体。

    Returns:
        企业数量统计和企业特征分布；查询失败时返回对应业务状态。
    """
    count_resp = await api_post(
        "/idis_industry/teis/park/tabcompanycount",
        {
            "parkId": park_ref["park_id"],
            "parkName": park_ref["park_name"],
            "addrType": 0,
            "zjsParkId": park_ref["zjs_park_id"],
        },
    )
    count_result = unwrap(count_resp)
    if count_result["status"] != "success":
        return _园区查询结果(count_result, "")
    company_count = (count_result["data"].get("全部企业") or {}).get("count")
    if company_count is None:
        return {"状态": "查询无数据", "摘要": "园区企业数量统计未返回“全部企业”数量。", "数据": []}
    resp = await api_post(
        "/idis_industry/teis/park/companyfeatures",
        {
            "companyCount": company_count,
            "parkId": park_ref["park_id"],
            "parkName": park_ref["park_name"],
            "addrType": 0,
            "zjsParkId": park_ref["zjs_park_id"],
        },
        params={"companyType": "全部企业"},
    )
    features_result = unwrap(resp)
    if features_result["status"] != "success":
        return _园区查询结果(features_result, "")
    data = {
        "企业数量统计": _企业数量统计数据(count_result["data"]),
        "企业特征分布": _企业特征分布数据(features_result["data"]),
    }
    return {
        "状态": "查询成功",
        "摘要": "已查询到园区企业特征分布。",
        "数据": data,
    }


async def park_companies(
    park_ref: ParkRef,
    key: str = "",
    page_now: int = 1,
    page_size: int = 20,
) -> dict:
    """分页查询园区内的入驻企业列表，支持企业名称关键字搜索。

    Args:
        park_ref: 由 ``resolve_park`` 返回并确认的标准园区实体。
        key: 企业名称关键字，不传则查全部。
        page_now: 页码，默认 1。
        page_size: 每页条数，默认 20。

    Returns:
        入驻企业列表；查询失败时返回对应业务状态。
    """
    resp = await api_post(
        "/idis_industry/teis/park/companyinpark",
        {
            "addrType": 0,
            "zjsParkId": park_ref["zjs_park_id"],
            "parkName": park_ref["park_name"],
            "pageNow": page_now,
            "pageSize": page_size,
            "sortCol": 1,
            "sortType": 1,
            "key": key,
        },
        params={"companyType": "全部企业"},
    )
    return _园区查询结果(unwrap(resp), "已查询到园区入驻企业列表。", _园区企业列表数据)
