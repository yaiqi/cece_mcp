"""人物信息查询：概述、法定代表人、任职、受益所有人、实控企业、所属集团、
关联企业、合作伙伴、持股企业。

消歧机制跟集团/园区不一样：人物没有走 Milvus，是直接调 `/cmp/person/list`
这个模糊搜索接口（材料 `获取人物no-开发.yml` 证实了这一点）。这个接口不返回
相似度分数，但返回的 `companyAmount`（该人物关联的企业数量）是一个天然的
置信度信号——同名人物里，业务上真正有名的那个人关联企业数量通常远超其他
重名的人（实测"雷军"：第一名 138 家 vs 第二名 2 家，差距悬殊）。用这个差距
做置信度判断，不是瞎猜。
"""

from common.api_client import api_post, unwrap
from common.business_protocol import call_failed, multiple_candidates, no_match, unique_match
from models.entity_refs import PersonRef

_CONFIDENCE_RATIO = 5  # 第一名 companyAmount 至少是第二名的这个倍数，才自动采用


async def resolve_person(query: str) -> dict:
    """识别人物姓名或 personNo，返回标准人物引用。"""
    person_no, result = await _resolve_person(query)
    if result:
        if result.get("status") == "ambiguous":
            candidates = result.get("candidates", [])
            return multiple_candidates("人物", query, candidates) if candidates else no_match("人物", query)
        return call_failed(result.get("error_message", "人物消歧调用失败。"))
    return unique_match("人物", query, {"person_no": person_no})


async def _resolve_person(name_or_id: str) -> tuple[str | None, dict | None]:
    """消歧落脚点：32位 MD5 格式直接当 personNo 用；否则调 /cmp/person/list
    模糊搜索，用 companyAmount 的断层差距判断是否可以唯一确定。

    Returns:
        (person_no, None) —— 解析成功
        (None, ambiguous_dict) —— 解析失败/不够唯一
    """
    if len(name_or_id) == 32 and all(c in "0123456789abcdef" for c in name_or_id.lower()):
        return name_or_id, None

    resp = await api_post(
        "/cmp/person/list",
        {
            "personName": name_or_id,
            "pageNow": 1,
            "pageSize": 6,
            "regionInfo": [],
            "categorys": [],
        },
    )
    result = unwrap(resp)
    if result["status"] != "success" or not result["data"]:
        return None, {
            "status": "ambiguous",
            "message": f"没查到名为'{name_or_id}'的人物。",
            "candidates": [],
        }

    candidates = result["data"].get("datas", [])
    if not candidates:
        return None, {
            "status": "ambiguous",
            "message": f"没查到名为'{name_or_id}'的人物。",
            "candidates": [],
        }

    top = candidates[0]
    second_amount = candidates[1].get("companyAmount", 0) if len(candidates) > 1 else 0
    top_amount = top.get("companyAmount", 0)
    if len(candidates) == 1 or (top_amount > 0 and top_amount >= second_amount * _CONFIDENCE_RATIO):
        return top["no"], None

    return None, {
        "status": "ambiguous",
        "message": f"'{name_or_id}'同名的人物不止一个，无法自动确定，请从候选里确认。",
        "candidates": [
            {
                "no": c.get("no"),
                "name": c.get("name"),
                "company_amount": c.get("companyAmount"),
                "partner_amount": c.get("partnerAmount"),
            }
            for c in candidates
        ],
    }


async def person_detail(person_ref: PersonRef) -> dict:
    """查询人物基本概述：姓名、性别、出生年份、学历、简历背景、主要任职及所属集团。

    Args:
        name_or_id: 人物姓名（同名时可能需要从候选里确认）或 32位 MD5 编号。

    Returns:
        status 及 data（成功时）或 error_message；同名歧义时返回
        status=ambiguous 和候选列表（含 company_amount 帮助判断是哪一个）。
    """
    resp = await api_post("/cmp/person/detail/describe", {"no": person_ref["person_no"]})
    return unwrap(resp)


async def person_legal_representative(
    person_ref: PersonRef, page_now: int = 1, page_size: int = 20
) -> dict:
    """查询人物担任法定代表人的企业列表。

    Args:
        name_or_id: 人物姓名或 32位 MD5 编号。
        page_now: 页码，默认 1。
        page_size: 每页条数，默认 20。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    resp = await api_post(
        "/cmp/person/detail/legal",
        {"no": person_ref["person_no"], "pageNow": page_now, "pageSize": page_size},
    )
    return unwrap(resp)


async def person_office(person_ref: PersonRef, page_now: int = 1, page_size: int = 20) -> dict:
    """查询人物在外任职的企业列表（职位、任职起止日期）。

    Args:
        name_or_id: 人物姓名或 32位 MD5 编号。
        page_now: 页码，默认 1。
        page_size: 每页条数，默认 20。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    resp = await api_post(
        "/cmp/person/detail/office",
        {"no": person_ref["person_no"], "officeType": "1", "pageNow": page_now, "pageSize": page_size},
    )
    return unwrap(resp)


async def person_beneficial(person_ref: PersonRef, page_now: int = 1, page_size: int = 20) -> dict:
    """查询人物作为受益所有人的企业列表（受益类型、受益比例）。

    Args:
        name_or_id: 人物姓名或 32位 MD5 编号。
        page_now: 页码，默认 1。
        page_size: 每页条数，默认 20。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    resp = await api_post(
        "/cmp/person/detail/beneficial",
        {"no": person_ref["person_no"], "pageNow": page_now, "pageSize": page_size},
    )
    return unwrap(resp)


async def person_controller(person_ref: PersonRef, page_now: int = 1, page_size: int = 20) -> dict:
    """查询人物实际控制的企业列表（持股比例、受益比例）。

    Args:
        name_or_id: 人物姓名或 32位 MD5 编号。
        page_now: 页码，默认 1。
        page_size: 每页条数，默认 20。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    resp = await api_post(
        "/cmp/person/detail/controller",
        {"no": person_ref["person_no"], "pageNow": page_now, "pageSize": page_size},
    )
    return unwrap(resp)


async def person_group(person_ref: PersonRef) -> dict:
    """查询人物所归属的企业集团信息（集团名称、规模、顶层控制人、该人物的角色）。

    Args:
        name_or_id: 人物姓名或 32位 MD5 编号。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    resp = await api_post("/cmp/person/detail/bloc", {"no": person_ref["person_no"]})
    return unwrap(resp)


async def person_union(person_ref: PersonRef, page_now: int = 1, page_size: int = 20) -> dict:
    """查询与人物有各类关联关系的企业列表（法定代表人/持股/受益/实控/任职）。

    Args:
        name_or_id: 人物姓名或 32位 MD5 编号。
        page_now: 页码，默认 1。
        page_size: 每页条数，默认 20。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    resp = await api_post(
        "/cmp/person/detail/union",
        {"no": person_ref["person_no"], "pageNow": page_now, "pageSize": page_size},
    )
    return unwrap(resp)


async def person_partners(person_ref: PersonRef, page_now: int = 1, page_size: int = 20) -> dict:
    """查询人物的合作伙伴列表（按共同出现在同一企业的次数降序）。

    Args:
        name_or_id: 人物姓名或 32位 MD5 编号。
        page_now: 页码，默认 1。
        page_size: 每页条数，默认 20。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    resp = await api_post(
        "/cmp/person/detail/partner",
        {"no": person_ref["person_no"], "pageNow": page_now, "pageSize": page_size},
    )
    return unwrap(resp)


async def person_shareholding(person_ref: PersonRef, page_now: int = 1, page_size: int = 20) -> dict:
    """查询人物持股的企业列表（持股比例、最短路径层级、股权路径详情）。

    Args:
        name_or_id: 人物姓名或 32位 MD5 编号。
        page_now: 页码，默认 1。
        page_size: 每页条数，默认 20。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    resp = await api_post(
        "/cmp/graph-trace/holder/p",
        {"personNo": person_ref["person_no"], "pageNow": page_now, "pageSize": page_size},
    )
    return unwrap(resp)
