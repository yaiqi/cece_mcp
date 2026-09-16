"""人物 Sever（行业洞察 MCP 清单 - 人物sever.csv）工具实现。

所有工具只接收人物编号（person_no），不自动消歧。
使用前请先调用 NER MCP 的 search_person_by_name 获取人物编号。
"""

import asyncio

from fastmcp.exceptions import ToolError

from common.api_client import api_post, unwrap

_CATEGORY_LABEL = {
    "1": "法定代表人",
    "2": "实际控制人",
    "3": "受益所有人",
    "4": "股东",
    "5": "高管",
}


def _validate_person_no(person_no: str) -> None:
    if not person_no or not (len(person_no) == 32 and all(c in "0123456789abcdef" for c in person_no.lower())):
        raise ToolError("person_no 必须是 32 位 MD5 格式编号，请先通过 search_person_by_name 获取。")


def _parse_roles(union_list: list) -> str:
    """解析 unionCategorys / unionPartnerCategorys 为拼接字符串。"""
    parts = []
    for item in (union_list or []):
        if not isinstance(item, dict):
            continue
        cat = item.get("category") or item.get("公告类型", "")
        label = _CATEGORY_LABEL.get(cat, cat)
        ratio = item.get("shareholdingRatioStr") or ""
        if ratio:
            parts.append(f"{label}({ratio})")
        else:
            parts.append(label)
    return "，".join(parts)


def _format_path_detail(path_detail: dict) -> str:
    """从原始 pathDetail 格式化持股路径文字（在翻译前处理）。"""
    paths = path_detail.get("paths") or []
    if not paths:
        return ""
    lines = []
    for pi, path in enumerate(paths, 1):
        pct = path.get("percent")
        lines.append(f"路径{pi}（持股比例：{pct}%）" if pct is not None else f"路径{pi}")
        graphs = path.get("graphsList") or []
        for gi, g in enumerate(graphs):
            start = g.get("startCompanyName", "")
            end = g.get("endCompanyName", "")
            gpct = g.get("percent")
            start_fmt = f"{start}({gpct}%)" if gpct is not None else start
            if gi < len(graphs) - 1:
                lines.append(f"{start_fmt} →")
            else:
                lines.append(f"{start_fmt} → {end}")
    return "\n".join(lines)


async def _run(person_no: str, endpoint: str, body: dict | None = None, page: int = 1, page_size: int = 20) -> dict:
    _validate_person_no(person_no)
    req = {"no": person_no, "pageNow": page, "pageSize": page_size}
    if body:
        req.update(body)
    resp = await api_post(endpoint, req)
    result = unwrap(resp)
    return result


async def get_person_legal(
    person_no: str,
    page: int = 1,
    page_size: int = 20,
    start_percent: float | None = None,
    end_percent: float | None = None,
    status: list[str] | None = None,
) -> dict:
    """查询人物担任法定代表人的所有企业。

    Args:
        person_no: 32 位人物编号。
        page: 页码，默认 1。
        page_size: 每页条数，默认 20。
        start_percent: 持股比例区间下限（%）。
        end_percent: 持股比例区间上限（%）。
        status: 经营状态筛选，可选值：["存续(在营、开业、在册)", "迁出", "吊销", "注销", "停业", "撤销"]。

    Returns:
        状态码 及 数据（成功时）。
    """
    body = {}
    if start_percent is not None:
        body["startPercent"] = str(start_percent)
    if end_percent is not None:
        body["endPercent"] = str(end_percent)
    if status:
        body["status"] = status
    return await _run(person_no, "/cmp/person/detail/legal", body=body, page=page, page_size=page_size)


async def get_person_office(
    person_no: str,
    page: int = 1,
    page_size: int = 20,
    status: list[str] | None = None,
) -> dict:
    """查询人物在外任职。

    Args:
        person_no: 32 位人物编号。
        page: 页码，默认 1。
        page_size: 每页条数，默认 20。
        status: 经营状态筛选，可选值：["存续(在营、开业、在册)", "迁出", "吊销", "注销", "停业", "撤销"]。

    Returns:
        状态码 及 数据（成功时）。
    """
    body = {"officeType": "1"}
    if status:
        body["status"] = status
    return await _run(person_no, "/cmp/person/detail/office", body, page=page, page_size=page_size)


async def get_person_beneficial(
    person_no: str,
    page: int = 1,
    page_size: int = 20,
    beneficial_type: list[str] | None = None,
    status: list[str] | None = None,
) -> dict:
    """查询人物为受益所有人的所有企业。

    Args:
        person_no: 32 位人物编号。
        page: 页码，默认 1。
        page_size: 每页条数，默认 20。
        beneficial_type: 受益类型筛选，可选值：["法定代表人", "直接或间接持股"]。
        status: 经营状态筛选，可选值：["存续(在营、开业、在册)", "迁出", "吊销", "注销", "停业", "撤销"]。

    Returns:
        状态码 及 数据（成功时）。
    """
    body = {}
    if beneficial_type:
        body["beneficialType"] = beneficial_type
    if status:
        body["status"] = status
    return await _run(person_no, "/cmp/person/detail/beneficial", body=body, page=page, page_size=page_size)


async def get_person_controller(
    person_no: str,
    page: int = 1,
    page_size: int = 20,
    start_percent: float | None = None,
    end_percent: float | None = None,
    status: list[str] | None = None,
) -> dict:
    """查询人物为实控人的所有企业。

    Args:
        person_no: 32 位人物编号。
        page: 页码，默认 1。
        page_size: 每页条数，默认 20。
        start_percent: 持股比例区间下限（%）。
        end_percent: 持股比例区间上限（%）。
        status: 经营状态筛选，可选值：["存续(在营、开业、在册)", "迁出", "吊销", "注销", "停业", "撤销"]。

    Returns:
        状态码 及 数据（成功时）。
    """
    body = {}
    if start_percent is not None:
        body["startPercent"] = str(start_percent)
    if end_percent is not None:
        body["endPercent"] = str(end_percent)
    if status:
        body["status"] = status
    return await _run(person_no, "/cmp/person/detail/controller", body=body, page=page, page_size=page_size)


async def get_person_holder(
    person_no: str,
    page: int = 1,
    page_size: int = 20,
    start_percent: float | None = None,
    end_percent: float | None = None,
    status: list[str] | None = None,
    level: int = 4,
) -> dict:
    """查询人物直接或间接持股的所有企业。

    Args:
        person_no: 32 位人物编号。
        page: 页码，默认 1。
        page_size: 每页条数，默认 20。
        start_percent: 持股比例区间下限（%）。
        end_percent: 持股比例区间上限（%）。
        status: 经营状态筛选，可选值：["存续(在营、开业、在册)", "迁出", "吊销", "注销", "停业", "撤销"]。
        level: 持股层级范围，默认 4。

    Returns:
        状态码 及 数据（成功时）。
    """
    _validate_person_no(person_no)
    body: dict = {"personNo": person_no, "pageNow": page, "pageSize": page_size}
    if start_percent is not None:
        body["startPercent"] = str(start_percent)
    if end_percent is not None:
        body["endPercent"] = str(end_percent)
    if status:
        body["status"] = status
    if level is not None:
        body["level"] = level
    resp = await api_post("/cmp/graph-trace/holder/p", body)
    # 预处理 pathDetail：从原始响应提取，格式化后替换回翻译后的数据
    raw_data = resp.get("data") or {}
    raw_datas = raw_data.get("datas") or []
    result = unwrap(resp)
    if result.get("status") == "success":
        # 查找翻译后的列表 key（URL 不同翻译不同）
        result_data = result.get("data") or {}
        items = None
        for k in ("数据", "部分记录", "列表", "持股企业列表"):
            v = result_data.get(k)
            if isinstance(v, list):
                items = v
                break
        if items:
            for raw_item, item in zip(raw_datas, items):
                if isinstance(item, dict) and isinstance(raw_item, dict):
                    raw_pd = raw_item.get("pathDetail")
                    if isinstance(raw_pd, dict) and raw_pd.get("paths"):
                        formatted = _format_path_detail(raw_pd)
                        if formatted:
                            item["持股路径"] = formatted
    return result


async def get_person_union(
    person_no: str,
    page: int = 1,
    page_size: int = 20,
    categorys: list[str] | None = None,
    start_percent: float | None = None,
    end_percent: float | None = None,
    status: list[str] | None = None,
) -> dict:
    """查询人物的关联企业。

    Args:
        person_no: 32 位人物编号。
        page: 页码，默认 1。
        page_size: 每页条数，默认 20。
        categorys: 集团角色/关联类型筛选，支持多选，可选值：["1"(法定代表人),"2"(实控人),"3"(受益所有人),"4"(股东),"5"(高管)]。
        start_percent: 持股比例区间下限（%），如 10。
        end_percent: 持股比例区间上限（%），如 50。
        status: 经营状态筛选，支持多选，可选值：["存续(在营、开业、在册)", "迁出", "吊销", "注销", "停业", "撤销"]。

    Returns:
        状态码 及 数据（成功时）。
    """
    body = {}
    if categorys:
        body["categorys"] = categorys
    if start_percent is not None:
        body["startPercent"] = str(start_percent)
    if end_percent is not None:
        body["endPercent"] = str(end_percent)
    if status:
        body["status"] = status
    result = await _run(person_no, "/cmp/person/detail/union", body=body, page=page, page_size=page_size)
    # 处理 unionCategorys 为拼接字符串
    if result.get("status") == "success":
        items = result.get("data", {}).get("数据") or []
        for item in items:
            if isinstance(item, dict) and item.get("unionCategorys"):
                item["unionCategorys"] = _parse_roles(item["unionCategorys"])
    return result


async def get_person_partner(person_no: str, page: int = 1, page_size: int = 20) -> dict:
    """查询人物的合作伙伴，包含合作详情（共同企业、角色、持股比例等）。

    Args:
        person_no: 32 位人物编号，请先通过 search_person_by_name 获取。
        page: 页码，默认 1。
        page_size: 每页条数，默认 20。

    Returns:
        状态码 及 数据（成功时）。
        列表每个元素：name/totalCount/no/companyName/amount + detailTotal/detailTop10。
    """
    _validate_person_no(person_no)

    resp = await api_post("/cmp/person/detail/partner", {"no": person_no, "pageNow": page, "pageSize": page_size})
    result = unwrap(resp)

    items = result.get("data", {}).get("数据") or []
    if not items:
        return result

    async def _fetch_detail(item):
        partner_no = item.get("编号") or item.get("no") or ""
        if not partner_no:
            return
        detail_resp = await api_post(
            "/cmp/person/detail/partner/detail",
            {"no": person_no, "partnerNo": partner_no, "pageNow": 1, "pageSize": 10},
        )
        if detail_resp.get("success"):
            detail_data = detail_resp.get("data", {})
            detail_list = detail_data.get("datas") or detail_data.get("list") or []
            item["_detailTotal"] = detail_data.get("total", 0) or len(detail_list)
            if detail_list:
                items_out = []
                for d in detail_list:
                    if not isinstance(d, dict):
                        continue
                    items_out.append({
                        "companyName": d.get("companyName", ""),
                        "registCapiStr": d.get("registCapiStr", ""),
                        "status": d.get("status", ""),
                        f"{d.get('name', '')}角色": _parse_roles(d.get("unionCategorys")),
                        f"{d.get('partnerName', '')}角色": _parse_roles(d.get("unionPartnerCategorys")),
                    })
                item["_detailList"] = items_out

    await asyncio.gather(*(_fetch_detail(item) for item in items))

    reshaped = []
    for item in items:
        entry = {
            "name": f"{item.get('名称', '')}（{item.get('数据总量', 0)}家关联企业）",
            "no": item.get("编号", ""),
            "companyName": item.get("企业名称", ""),
            "amount": item.get("金额", 0),
        }
        detail_list = item.get("_detailList")
        if detail_list:
            entry["detailTotal"] = item.get("_detailTotal", len(detail_list))
            entry["detailTop10"] = detail_list
        reshaped.append(entry)

    result_data = result.get("data", {})
    result_data["数据"] = reshaped
    result["data"] = result_data
    result["数据"] = result_data
    return result


async def get_talent_basic(person_no: str) -> dict:
    """查询人物基本信息：职业背景、履历、学术成就等。

    Args:
        person_no: 32 位人物编号，请先通过 search_person_by_name 获取。

    Returns:
        状态码 及 数据（成功时）。
    """
    _validate_person_no(person_no)
    talent_resp = await api_post("/idis_industry/teis/talent/basic", {"personNo": person_no})
    talent = unwrap(talent_resp)
    describe_resp = await api_post("/cmp/person/detail/describe", {"no": person_no})
    describe = unwrap(describe_resp)
    if talent["status"] != "success":
        merged = {"科技人才信息": None, "人物简介": describe.get("data")}
        return {
            "status": "success",
            "data": merged,
            "状态码": "查询成功",
            "摘要": "科技人才信息接口当前不可用，仅返回人物简介。",
            "数据": merged,
        }
    merged = {"科技人才信息": talent.get("data"), "人物简介": describe.get("data")}
    return {
        "status": "success",
        "data": merged,
        "状态码": "查询成功",
        "摘要": "查询成功。",
        "数据": merged,
    }