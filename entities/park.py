"""园区信息查询：详情、子园区、产业分布、企业特征、园区内企业列表。

跟集团一样，消歧下沉到工具内部。园区这边还多一层参数依赖链：
`industrydistribution`/`companyfeatures` 接口要求 `companyCount`/`province`
必须来自 `parkdetail` 的出参、不能猜测——这个依赖关系也下沉到工具内部，
调用方只管传园区名字，不需要知道"要先查一次详情才能查产业分布"这种细节。

区域维度的园区/开发区列表（parklist/kaifaqulist/regiondisplaypark/
statisticpark）还没实现，需要先给 get_address 加一个返回完整省市区
breadcrumb 的能力，见 TODO。
"""

from entity_mcp.common.api_client import api_post, unwrap
from entity_mcp.common.milvus_client import resolve_entity
from entity_mcp.common.business_protocol import 唯一匹配, 多候选, 未匹配, 调用失败
from entity_mcp.models.entity_refs import ParkRef


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
    """识别具体园区，返回 park_id、zjs_park_id、park_name。"""
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
        name_or_id: 园区名称（如"张江高科技园区"）。

    Returns:
        status 及 data（成功时）或 error_message；消歧结果不唯一时返回
        status=ambiguous 和候选列表。
    """
    data = await _get_park_detail_raw(park_ref)
    if data is None:
        return {"status": "error", "error_message": "接口调用失败"}
    data.pop("shape", None)  # 地理边界坐标串，体积大且对回答没用
    return {"status": "success", "data": data}


async def park_sub_parks(park_ref: ParkRef) -> dict:
    """查询某个园区的子园区列表。

    Args:
        name_or_id: 园区名称。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    resp = await api_post(
        "/idis_industry/teis/park/sonpark",
        {"zjsParkId": park_ref["zjs_park_id"], "addrType": 0, "parkName": park_ref["park_name"]},
    )
    return unwrap(resp)


async def park_industry_distribution(park_ref: ParkRef) -> dict:
    """查询园区内各产业的企业数量占比分布。

    Args:
        name_or_id: 园区名称。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    detail = await _get_park_detail_raw(park_ref)
    if detail is None:
        return {"status": "error", "error_message": "查询园区详情失败，无法获取企业总数"}
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
    return unwrap(resp)


async def park_company_features(park_ref: ParkRef) -> dict:
    """查询园区内企业特征分布（注册资本、规模、成立时间、类型四个维度占比）。

    Args:
        name_or_id: 园区名称。

    Returns:
        status 及 data（成功时）或 error_message。
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
        return count_result
    company_count = (count_result["data"].get("全部企业") or {}).get("count")
    if company_count is None:
        return {
            "status": "error",
            "error_message": "园区企业数量统计未返回“全部企业”数量。",
            "状态码": "查询无数据",
            "摘要": "园区企业数量统计未返回“全部企业”数量。",
            "数据": [],
        }
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
        return features_result
    data = {
        "企业数量统计": count_result["data"],
        "企业特征分布": features_result["data"],
    }
    return {
        "status": "success", "data": data,
        "状态码": "查询成功", "摘要": "查询成功。", "数据": data,
    }


async def park_companies(
    park_ref: ParkRef,
    key: str = "",
    page_now: int = 1,
    page_size: int = 20,
) -> dict:
    """分页查询园区内的入驻企业列表，支持企业名称关键字搜索。

    Args:
        name_or_id: 园区名称。
        key: 企业名称关键字，不传则查全部。
        page_now: 页码，默认 1。
        page_size: 每页条数，默认 20。

    Returns:
        status 及 data（成功时）或 error_message。
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
    return unwrap(resp)
