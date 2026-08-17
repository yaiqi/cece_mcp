"""集团信息查询：详情、成员企业、融资/产业/资质图谱、风险/商机事件。

精简逻辑（_simplify_finance_graphy / _simplify_qualification_graphy）跟
material/集团/融资图谱精简.py、资质图谱精简.py 保持一致（这是最新的版本，
比更早从 Dify workflow 导出文件里扒出来的版本做了调整：融资图谱不再对
企业数量做 50 条封顶，资质图谱去掉了 legalPerson/ipoCode 的特殊处理）。
"""

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from common.api_client import api_get, api_post, unwrap
from common.milvus_client import resolve_single
from common.business_protocol import 唯一匹配, 多候选, 未匹配, 调用失败
from models.entity_refs import GroupRef

# 硬编码别名：跟 material/集团/获取集团全称-生产.yml 里的 ALIAS_MAP 保持一致，
# 这条是当时手工加的例外，Milvus 检索覆盖不到就先留着。
_ALIAS_MAP = {
    "新华社": {"group_id": "G000041762", "group_name": "新华社投资控股有限公司"},
}

# 对外工具不暴露接口实现字段；其余字段只改中文名称，不调整原始层级、列表或数值。
_字段中文名 = {
    "data": "数据",
    "list": "列表",
    "rows": "列表",
    "records": "列表",
    "total": "总数",
    "totalCount": "总数",
    "count": "数量",
    "name": "名称",
    "value": "数值",
    "label": "名称",
    "groupName": "集团名称",
    "groupLevel": "集团级别",
    "groupClass": "集团级别",
    "groupType": "集团类型",
    "groupInfo": "集团信息",
    "companyInfo": "企业信息",
    "companyName": "企业名称",
    "companyCount": "企业数量",
    "companyType": "企业类型",
    "companyLevel": "企业层级",
    "companyStatus": "企业状态",
    "status": "状态",
    "industryName": "产业名称",
    "industryType": "产业类型",
    "industryInfo": "产业信息",
    "province": "省份",
    "city": "城市",
    "district": "区县",
    "address": "地址",
    "registeredCapital": "注册资本",
    "registCapiValue": "注册资本数额",
    "registCapiUnit": "注册资本单位",
    "legalPersonName": "法定代表人",
    "establishDate": "成立日期",
    "establishmentDate": "成立日期",
    "eventName": "事件名称",
    "eventType": "事件类型",
    "eventTypeName": "事件类型",
    "eventDate": "事件日期",
    "eventDt": "事件日期",
    "eventContent": "事件内容",
    "eventSummary": "事件摘要",
    "riskLevel": "风险等级",
    "riskName": "风险名称",
    "ratio": "占比",
    "proportion": "占比",
    "percent": "占比",
    "children": "子项",
    "qualification": "资质",
    "std": "标准",
    "ventureFinanceList": "创业融资",
    "stockFinanceList": "股票融资",
    "bondFinanceList": "债券融资",
    "bankFinanceList": "银行融资",
    "receivableFinanceList": "应收账款融资",
    "leaseFinanceList": "融资租赁",
    "trustFinanceList": "信托融资",
    "pledgeFinanceList": "股权质押融资",
    "otherFinanceList": "其他融资",
    "r": "右侧",
    "l": "左侧",
}


def _去除内部标识字段(data: Any) -> Any:
    """递归移除只供接口关联的 ID、code 字段。"""
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


def _中文化字段(data: Any) -> Any:
    """保持数据结构不变，仅将已知接口字段转为中文业务语义。"""
    if isinstance(data, list):
        return [_中文化字段(item) for item in data]
    if not isinstance(data, dict):
        return data
    return {
        _字段中文名.get(key, key): _中文化字段(value)
        for key, value in data.items()
    }


def _集团查询结果(result: dict, 成功摘要: str) -> dict:
    """将接口响应适配为便于模型阅读的中文业务结果。"""
    if result.get("status") != "success":
        return {
            "状态": "调用失败",
            "摘要": result.get("error_message", "集团信息查询失败。"),
        }
    data = result.get("data")
    if data is None or data == {} or data == []:
        return {"状态": "查询无数据", "摘要": "查询成功，但未返回相关数据。", "数据": []}
    data = _中文化字段(_去除内部标识字段(data))
    return {"状态": "查询成功", "摘要": 成功摘要, "数据": data}

_RISK_TYPE_CODES = [
    "Z0101", "Z0102", "Z0103", "Z0104", "Z0105", "Z0106", "Z0107", "Z0108", "Z0109",
    "Z0110", "Z0111", "Z0112", "Z0113", "Z0114",
    "Z0201", "Z0202", "Z0203", "Z0204", "Z0205", "Z0206", "Z0207", "Z0208", "Z0209",
    "Z0210", "Z0211", "Z0212", "Z0213", "Z0214",
    "Z0601", "Z0602", "Z0603", "Z0604", "Z0605", "Z0606", "Z0607", "Z0608", "Z0609",
    "Z0610", "Z0611", "Z0612", "Z0613", "Z0614", "Z0615",
    "Z0701", "Z0702", "Z0703", "Z0704", "Z0705", "Z0706", "Z0707", "Z0708", "Z0709",
    "Z0710", "Z0711",
]

_OPPORTUNITY_TYPE_CODES = [
    "Z0101", "Z0102", "Z0103", "Z0104", "Z0105", "Z0106", "Z0107", "Z0108", "Z0109",
    "Z0110", "Z0111", "Z0112", "Z0113", "Z0114",
    "Z0201", "Z0202", "Z0203", "Z0204", "Z0205", "Z0206", "Z0207", "Z0208", "Z0209",
    "Z0210", "Z0211", "Z0212", "Z0213", "Z0214",
    "Z0301", "Z0302", "Z0303", "Z0304", "Z0305", "Z0306", "Z0307",
    "Z0401", "Z0402", "Z0403", "Z0404",
    "Z0501", "Z0502", "Z0503", "Z0504", "Z0505", "Z0506", "Z0507", "Z0508", "Z0509",
    "Z0510", "Z0511", "Z0512",
]


async def resolve_group(query: str) -> dict:
    """识别集团名称、简称或别名，返回标准集团引用或候选列表。"""
    group_id, result = await _resolve_group_id(query)
    if result:
        if result.get("status") == "ambiguous":
            candidates = result.get("candidates", [])
            return 多候选("集团", query, candidates) if candidates else 未匹配("集团", query)
        return 调用失败(result.get("error_message", "集团消歧调用失败。"))
    return await _确认集团并生成引用(group_id, query)


async def _确认集团并生成引用(group_id: str, query: str) -> dict:
    """通过集团详情接口校验候选 ID，并生成对外标准集团实体。"""
    meta = await _get_group_meta(group_id)
    if not meta:
        return 调用失败("已识别集团，但获取标准集团引用失败。")
    return 唯一匹配("集团", query, {
        "group_id": group_id,
        "group_name": meta.get("group_name", ""),
    })


async def group_detail(group_ref: GroupRef) -> dict:
    """查询集团基本信息：规模、等级、财务评分、下属企业分类统计、标签。

    Args:
        group_ref: 由 ``resolve_group`` 返回或从其候选列表中经用户确认的标准集团实体。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    resp = await api_get(
        "/idis_industry/teis/landing/company/group/get", {"groupId": group_ref["group_id"]}
    )
    return _集团查询结果(unwrap(resp), "已查询到集团基本信息。")


async def group_class_count(group_ref: GroupRef) -> dict:
    """查询集团下属企业按类型划分的数量统计（如上市公司数、高新技术企业数等）。

    Args:
        group_ref: 已确认的标准集团实体。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    resp = await api_post(
        "/idis_industry/teis/landing/company/group/quickTab",
        {"groupId": group_ref["group_id"], "industryType": "GB"},
    )
    return _集团查询结果(unwrap(resp), "已查询到集团下属企业分类统计。")


async def group_companies(
    group_ref: GroupRef,
    industry_type: str = "GB",
    page_now: int = 1,
    page_size: int = 20,
    order_column: str = "VALUE_SCORE",
    order_type: str = "desc",
    member_level_in: list[str] | None = None,
    region_code_in: list[str] | None = None,
    control_ratio_interval_range: list[str] | None = None,
) -> dict:
    """分页查询集团成员企业清单，可按行业/层级/地区/持股比例筛选排序。

    按地区筛选前必须先调用 get_address 工具获取 region_code_in 的值，
    禁止直接猜测地区代码。

    Args:
        group_ref: 已确认的标准集团实体。
        industry_type: 产业体系类型，可选 SELECTED/CSF/NSEI/GB/DE，默认 GB（国标产业）。
        page_now: 页码，默认 1。
        page_size: 每页条数，默认 20，不得小于 20。
        order_column: 排序字段，可选 VALUE_SCORE/INNOVATION_SCORE/MARKET_SCORE/
            REGISTERED_CAPITAL/OPERATING_REVENUE/NET_PROFIT/TOTAL_ASSETS，默认 VALUE_SCORE。
        order_type: 排序方向 asc/desc，默认 desc。
        member_level_in: 成员层级筛选，可选 GROUP_COMPANY/FIRST_LEVEL_SUB_COMPANY/
            SECOND_LEVEL_SUB_COMPANY/THIRD_LEVEL_SUB_COMPANY/OTHER_SUB_COMPANY；
            不传则查全部层级。
        region_code_in: 注册地区代码数组，如 ["120000"]；需先调用 get_address 获取。
            不传则不限地区。
        control_ratio_interval_range: 实控人持股比例区间，如 ["15","22"] 表示
            15%~22%；不传则不限比例。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    meta = await _get_group_meta(group_ref["group_id"])
    member_company_query_id = (meta or {}).get("zjs_group_id")
    if not member_company_query_id:
        return {"状态": "调用失败", "摘要": "集团成员企业查询准备失败。"}
    body = {
        "groupId": member_company_query_id,
        "scene": "GROUP_COMPANY",
        "industryType": industry_type,
        "pageNow": page_now,
        "pageSize": max(page_size, 20),
        "orderColumn": order_column,
        "orderType": order_type,
    }
    if member_level_in:
        body["memberLevelIn"] = member_level_in
    if region_code_in:
        body["regionCodeIn"] = region_code_in
    if control_ratio_interval_range:
        body["controlRatioIntervalRange"] = control_ratio_interval_range

    resp = await api_post("/idis_industry/teis/landing/company/search", body)
    return _集团查询结果(unwrap(resp), "已查询到集团成员企业列表。")


def _simplify_finance_graphy(data: dict) -> dict:
    max_detail = 10
    tech_fields = {"nodeType", "nodeSort", "id", "financeType"}
    fl_keys = {
        "ventureFinanceList", "stockFinanceList", "bondFinanceList",
        "bankFinanceList", "receivableFinanceList", "leaseFinanceList",
        "trustFinanceList", "pledgeFinanceList", "otherFinanceList",
    }

    def clean_enterprise(node):
        cleaned = {}
        for k, v in node.items():
            if k in tech_fields:
                continue
            if k in fl_keys:
                if v:
                    cleaned[k] = v[:max_detail]
            else:
                cleaned[k] = v
        return cleaned

    def clean_category(node):
        children = node.get("children") or []
        if not children:
            return None
        is_enterprise_level = any(k in children[0] for k in fl_keys)
        cleaned_children = []
        for child in children:
            if is_enterprise_level:
                cleaned_children.append(clean_enterprise(child))
            else:
                cleaned = clean_category(child)
                if cleaned is not None:
                    cleaned_children.append(cleaned)
        if not cleaned_children:
            return None
        cleaned_node = {k: v for k, v in node.items() if k not in tech_fields}
        cleaned_node["children"] = cleaned_children
        return cleaned_node

    def simplify(graph_data):
        new_item = {}
        for k, v in graph_data.items():
            if k in ("r", "l") and isinstance(v, dict):
                cats = v.get("children") or []
                cleaned_cats = [c for c in (clean_category(cat) for cat in cats) if c is not None]
                new_item[k] = {"children": cleaned_cats}
            else:
                new_item[k] = v
        return new_item

    def is_empty(value):
        if value is None:
            return True
        if isinstance(value, str):
            return not any(ch.isalnum() or "一" <= ch <= "鿿" for ch in value)
        return False

    def remove_empty(obj):
        if isinstance(obj, dict):
            return {k: remove_empty(v) for k, v in obj.items() if not is_empty(v)}
        if isinstance(obj, list):
            return [remove_empty(i) for i in obj if not is_empty(i)]
        return obj if obj is not None else {}

    return remove_empty(simplify(data))


async def group_finance_graphy(group_ref: GroupRef) -> dict:
    """查询集团融资图谱（创投、股票、债券、银行借款、应收账款、股权出质等全景）。

    Args:
        group_ref: 已确认的标准集团实体。

    Returns:
        status 及 data（已精简，成功时）或 error_message。
    """
    resp = await api_get(
        "/cmp/groupGraphy/financeGraphy",
        {"groupId": group_ref["group_id"], "groupName": group_ref["group_name"]},
    )
    result = unwrap(resp)
    if result["status"] == "success" and result["data"]:
        result["data"] = _simplify_finance_graphy(result["data"])
    return _集团查询结果(result, "已查询到集团融资图谱。")


def _simplify_qualification_graphy(data: dict) -> dict:
    max_detail = 10
    tech_fields = {"nodeType", "nodeSort", "id"}
    detail_keys = {"qualification", "std"}

    def clean_enterprise(node):
        cleaned = {}
        for k, v in node.items():
            if k in tech_fields:
                continue
            if k in detail_keys:
                if v:
                    cleaned[k] = v[:max_detail]
            else:
                cleaned[k] = v
        return cleaned

    def clean_subcat(node):
        children = node.get("children") or []
        cleaned_children = [clean_enterprise(e) for e in children]
        cleaned_node = {k: v for k, v in node.items() if k not in tech_fields}
        cleaned_node["children"] = cleaned_children
        return cleaned_node

    def clean_category(node):
        children = node.get("children") or []
        cleaned_subcats = []
        for subcat in children:
            cs = clean_subcat(subcat)
            if cs.get("children"):
                cleaned_subcats.append(cs)
        if not cleaned_subcats:
            return None
        cleaned_node = {k: v for k, v in node.items() if k not in tech_fields}
        cleaned_node["children"] = cleaned_subcats
        return cleaned_node

    def simplify(graph_data):
        new_item = {}
        for k, v in graph_data.items():
            if k in ("r", "l") and isinstance(v, dict):
                cats = v.get("children") or []
                cleaned_cats = [c for c in (clean_category(cat) for cat in cats) if c is not None]
                new_side = {ck: cv for ck, cv in v.items() if ck != "children"}
                new_side["children"] = cleaned_cats
                new_item[k] = new_side
            else:
                new_item[k] = v
        return new_item

    def is_empty(value):
        if value is None:
            return True
        if isinstance(value, str):
            return not any(ch.isalnum() or "一" <= ch <= "鿿" for ch in value)
        return False

    def remove_empty(obj):
        if isinstance(obj, dict):
            return {k: remove_empty(v) for k, v in obj.items() if not is_empty(v)}
        if isinstance(obj, list):
            return [remove_empty(i) for i in obj if not is_empty(i)]
        return obj if obj is not None else {}

    return remove_empty(simplify(data))


async def group_qualification_graphy(group_ref: GroupRef) -> dict:
    """查询集团资质图谱（高新技术、专精特新、绿色制造等认证，荣誉榜单，主导标准）。

    Args:
        group_ref: 已确认的标准集团实体。

    Returns:
        status 及 data（已精简，成功时）或 error_message。
    """
    resp = await api_get(
        "/cmp/groupGraphy/qualificationGraphy",
        {"groupId": group_ref["group_id"], "groupName": group_ref["group_name"]},
    )
    result = unwrap(resp)
    if result["status"] == "success" and result["data"]:
        result["data"] = _simplify_qualification_graphy(result["data"])
    return _集团查询结果(result, "已查询到集团资质图谱。")


async def group_industry_graphy(
    group_ref: GroupRef,
    min_ratio: str = "0",
    max_ratio: str = "100",
) -> dict:
    """查询集团产业分布图谱（行业分布与产业结构）。

    Args:
        group_ref: 已确认的标准集团实体。
        min_ratio: 最小持股比例，默认 "0"（不限）。
        max_ratio: 最大持股比例，默认 "100"（不限）。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    resp = await api_get(
        "/cmp/groupGraphy/industryGraphy",
        {
            "groupId": group_ref["group_id"],
            "groupName": group_ref["group_name"],
            "minRatio": min_ratio,
            "maxRatio": max_ratio,
        },
    )
    return _集团查询结果(unwrap(resp), "已查询到集团产业分布图谱。")


async def _group_events(
    group_id: str,
    emotions: list[int],
    type_codes: list[str],
    is_core: bool | None,
    control_ratio_interval_range: list[str] | None,
    page_num: int,
    page_size: int,
) -> dict:
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    body = {
        "groupId": group_id,
        "emotions": emotions,
        "typeCodes": type_codes,
        "orderColumn": "cnt",
        "orderType": "desc",
        "pageNum": page_num,
        "pageSize": page_size,
        "eventDtFrom": (now - timedelta(days=180)).strftime("%Y-%m-%d"),
        "eventDtTo": now.strftime("%Y-%m-%d"),
    }
    if is_core:
        body["isCore"] = True
    if control_ratio_interval_range:
        body["controlRatioIntervalRange"] = control_ratio_interval_range

    resp = await api_post("/cmp/mnt/user/group-lib/overview", body)
    return unwrap(resp)


async def group_risk_events(
    group_ref: GroupRef,
    is_core: bool = False,
    control_ratio_interval_range: list[str] | None = None,
    page_num: int = 1,
    page_size: int = 10,
) -> dict:
    """查询集团及下属企业近6个月的风险事件（负面事件及类型分布）。

    Args:
        group_ref: 已确认的标准集团实体。
        is_core: 是否只查核心成员企业，默认 False（查全部成员）。
        control_ratio_interval_range: 实控人持股比例区间，如 ["15","22"]。
        page_num: 页码，默认 1。
        page_size: 每页条数，默认 10。

    Returns:
        status 及 data（成功时，totalCount 表示涉及的不重复企业数）或 error_message。
    """
    result = await _group_events(
        group_ref["group_id"], [1, 2], _RISK_TYPE_CODES, is_core,
        control_ratio_interval_range, page_num, page_size,
    )
    return _集团查询结果(result, "已查询到集团风险事件。")


async def group_opportunity_events(
    group_ref: GroupRef,
    is_core: bool = False,
    control_ratio_interval_range: list[str] | None = None,
    page_num: int = 1,
    page_size: int = 10,
) -> dict:
    """查询集团及下属企业近6个月的商机事件（中标、融资、扩张等正面事件）。

    Args:
        group_ref: 已确认的标准集团实体。
        is_core: 是否只查核心成员企业，默认 False（查全部成员）。
        control_ratio_interval_range: 实控人持股比例区间，如 ["15","22"]。
        page_num: 页码，默认 1。
        page_size: 每页条数，默认 10。

    Returns:
        status 及 data（成功时，totalCount 表示涉及的不重复企业数）或 error_message。
    """
    result = await _group_events(
        group_ref["group_id"], [3, 4], _OPPORTUNITY_TYPE_CODES, is_core,
        control_ratio_interval_range, page_num, page_size,
    )
    return _集团查询结果(result, "已查询到集团商机事件。")


async def _resolve_group_id(name_or_id: str) -> tuple[str | None, dict | None]:
    """消歧的落脚点：名称和别名统一走别名映射或 Milvus 语义检索。

    Returns:
        (group_id, None) —— 解析成功；
        (None, ambiguous_dict) —— 解析失败/置信度不够，ambiguous_dict 是可以
        直接作为工具返回值的 {"status": "ambiguous", "candidates": [...]}。
    """
    if name_or_id in _ALIAS_MAP:
        return _ALIAS_MAP[name_or_id]["group_id"], None

    result = await resolve_single(
        collection_name="group_name_collection",
        embedding_field="embedding_name",
        id_field="group_id",
        name_field="group_name",
        query_text=name_or_id,
    )
    if result["status"] == "resolved":
        return result["id"], None
    candidates = [
        {key: value for key, value in candidate.items() if key != "score"}
        for candidate in result["candidates"]
    ]
    return None, {
        "status": "ambiguous",
        "message": f"没能唯一确定'{name_or_id}'对应哪个集团，请从候选里确认。",
        "candidates": candidates,
    }


async def _get_group_meta(group_id: str) -> dict | None:
    """查一次 /group/get，获取服务端内部所需的关联字段：

    - group_name：groupIndustryGraphy 这类接口实测要求 groupName 必须传真实值，
      传空字符串会直接 400（"系统异常"），得先查出来自动补上。
    - zjs_group_id：成员企业列表接口的内部查询标识；它与对外 ``group_id``
      不是同一套编号，不能通过字符串换算，只能由服务端从详情中获取。
    """
    resp = await api_get(
        "/idis_industry/teis/landing/company/group/get", {"groupId": group_id}
    )
    result = unwrap(resp)
    if result["status"] != "success" or not result["data"]:
        return None
    data = result["data"]
    return {
        "group_name": data.get("groupName"),
        "zjs_group_id": data.get("companyInfo", {}).get("groupInfo", {}).get("groupId"),
    }
