"""企业 Sever（行业洞察 MCP 清单 - 企业Sever.csv）工具实现。

按需求文档单独建立一个企业级服务（enterprise-mcp），工具命名与需求清单一致
（get_enterprise_* / get_company_graphy / get_businessFinance_graphy /
get_query_winTenderer_tenderee），共 17 个查询工具。

企业名称识别（简称 -> 工商全称）由主体识别服务（entity-resolve-mcp）的
`search_enterprise_by_name` 承担，本服务不重复提供。

上游企业侧接口只认工商全称（简称查不到数据），因此本模块所有查询工具建议
先用 search_enterprise_by_name 拿到全称再调用；查不到主体时统一返回
「实体未匹配」并引导调用名称识别工具。

融资类型标志：1=创投融资 2=股票融资 3=债券融资 4=应收账款 5=租赁融资
6=信托融资 7=银行借款 8=其他融资。
"""

from functools import wraps

from fastmcp.exceptions import ToolError

from common.api_client import api_get, api_post, unwrap

_FINANCE_BASE = "/idis_industry/teis/v2/businessFinance"

# 融资类型标志（需求清单的 financeType 约定）
_VCPE, _STOCK, _BOND, _RECEIVABLES, _LEASING, _TRUST, _BANK = 1, 2, 3, 4, 5, 6, 7

# 股票融资细分类型 -> childType 代码（与 region_finance_events 口径一致）
_STOCK_CHILD_TYPES = {
    "A股IPO": 20, "A股增发": 21, "A股配股": 22,
    "港股IPO": 23, "港股增发": 24, "新三板发行": 25,
}


def _enterprise_query_tool(tool):
    """把“成功但 data=null”统一解释为企业主体未匹配。"""
    @wraps(tool)
    async def wrapper(company_name: str, *args, **kwargs):
        result = await tool(company_name, *args, **kwargs)
        if result.get("status") == "success" and result.get("data") is None:
            raise ToolError(f"未匹配到企业主体'{company_name}'，请调用主体识别服务的 search_enterprise_by_name 获取企业全称。")
        return result
    return wrapper


def _financing_events(company_name: str, finance_type: int, extra: dict, page: int, page_size: int) -> dict:
    """v2 融资事件分页查询的公共入口。"""
    body: dict = {
        "companyName": company_name,
        "financeType": finance_type,
        "desc": True,
        "page": page,
        "pageSize": page_size,
        **extra,
    }
    return body


@_enterprise_query_tool
async def get_enterprise_tags(company_name: str, credit_code: str = "") -> dict:
    """获取企业标签信息：资本市场标签、科技标签、榜单荣誉标签、标准制定标签、
    产业标签、风险标签。

    Args:
        company_name: 企业工商登记全称（简称请先用主体识别服务的
            search_enterprise_by_name 解析）。
        credit_code: 统一社会信用代码（需求要求补充的入参，可选），与名称
            一并传给上游做主体校验。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    params = {"companyName": company_name}
    if credit_code:
        params["creditCode"] = credit_code
    resp = await api_get("/idis_industry/teis/landing/company/get", params)
    result = unwrap(resp)
    basic_resp = await api_post("/cmp/detail/basic", {}, params={"name": company_name})
    if basic_resp.get("success") and isinstance(basic_resp.get("data"), dict):
        basic = basic_resp["data"]
        if isinstance(result.get("data"), dict):
            if basic.get("productClsNames"):
                result["data"]["productClsNames"] = basic["productClsNames"]
            if basic.get("nseiClsNames"):
                result["data"]["nseiClsNames"] = basic["nseiClsNames"]
            if basic.get("industrycoName"):
                result["data"]["industrycoName"] = basic["industrycoName"]
    return result


@_enterprise_query_tool
async def get_enterprise_basic(company_name: str, credit_code: str = "") -> dict:
    """获取企业工商信息：经营状态、企业规模、组织机构代码、工商注册号、
    纳税人识别号、登记机关、注册地址、经营范围、注册资本、法定代表人、
    成立日期等基础工商登记内容。

    Args:
        company_name: 企业工商登记全称。
        credit_code: 统一社会信用代码，可选核验入参。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    params = {"name": company_name}
    if credit_code:
        params["creditCode"] = credit_code
    resp = await api_post("/cmp/detail/basic", {}, params=params)
    return unwrap(resp)


@_enterprise_query_tool
async def get_enterprise_shareholders(company_name: str, credit_code: str = "") -> dict:
    """获取企业股东信息：整合上市公告口径与工商登记口径的股东构成，包括股东
    名称、类型、持股比例、持股数及股份变动情况。

    Args:
        company_name: 企业工商登记全称。
        credit_code: 统一社会信用代码，可选核验入参。

    Returns:
        status 及 data（成功时，data.上市公告股东 / data.工商登记股东）或
        error_message。
    """
    params = {"name": company_name}
    if credit_code:
        params["creditCode"] = credit_code
    ipo_resp = await api_post("/cmp/holder/ipo/partner", {}, params=params)
    normal_resp = await api_post("/cmp/holder/normal/partner", {}, params=params)
    ipo = unwrap(ipo_resp)
    normal = unwrap(normal_resp)
    if ipo["status"] != "success" or normal["status"] != "success":
        failed = ipo if ipo["status"] != "success" else normal
        return failed

    # 只保留最新报告日期的记录
    ipo_data = ipo.get("data")
    if isinstance(ipo_data, list):
        max_date = ""
        for item in ipo_data:
            if isinstance(item, dict):
                pub_date = str(item.get("publicDate") or item.get("报告日期") or "")
                if pub_date > max_date:
                    max_date = pub_date
        if max_date:
            ipo_data = [
                item for item in ipo_data
                if isinstance(item, dict)
                and str(item.get("publicDate") or item.get("报告日期") or "") == max_date
            ]

    normal_data = normal.get("data")
    if isinstance(normal_data, list):
        max_date = ""
        for item in normal_data:
            if isinstance(item, dict):
                pub_date = str(item.get("publicDate") or item.get("报告日期") or "")
                if pub_date > max_date:
                    max_date = pub_date
        if max_date:
            normal_data = [
                item for item in normal_data
                if isinstance(item, dict)
                and str(item.get("publicDate") or item.get("报告日期") or "") == max_date
            ]

    merged = {"上市公告股东": ipo_data, "工商登记股东": normal_data}
    return {
        "status": "success",
        "data": merged,
        "状态码": "查询成功",
        "摘要": "查询成功。",
        "数据": merged,
    }


@_enterprise_query_tool
async def get_enterprise_management(company_name: str, credit_code: str = "") -> dict:
    """获取企业主要人员/董监高：整合上市公告高管、工商登记高管，以及公司董事、
    监事、高级管理人员在其他企业的投资任职情况。

    Args:
        company_name: 企业工商登记全称。
        credit_code: 统一社会信用代码，可选核验入参。

    Returns:
        status 及 data（成功时，data.上市公告主要人员 / data.工商登记主要
        人员 / data.董监高投资任职）或 error_message。
    """
    params = {"name": company_name}
    if credit_code:
        params["creditCode"] = credit_code
    ipo_resp = await api_post("/cmp/employee/ipo/list", {}, params=params)
    normal_resp = await api_post("/cmp/employee/normal/list", {}, params=params)
    office_resp = await api_post("/cmp/officeinfo/list", {}, params=params)
    ipo = unwrap(ipo_resp)
    normal = unwrap(normal_resp)
    office = unwrap(office_resp)
    for part in (ipo, normal, office):
        if part["status"] != "success":
            return part

    # 上市公告主要人员：只保留最新变更日期的记录
    ipo_data = ipo.get("data")
    if isinstance(ipo_data, list):
        max_date = ""
        for item in ipo_data:
            if isinstance(item, dict):
                dt = str(item.get("dates") or item.get("变更日期") or "")
                if dt > max_date:
                    max_date = dt
        if max_date:
            ipo_data = [
                item for item in ipo_data
                if isinstance(item, dict)
                and str(item.get("dates") or item.get("变更日期") or "") == max_date
            ]

    merged = {
        "上市公告主要人员": ipo_data,
        "工商登记主要人员": normal.get("data"),
        "董监高投资任职": office.get("data"),
    }
    return {
        "status": "success",
        "data": merged,
        "状态码": "查询成功",
        "摘要": "查询成功。",
        "数据": merged,
    }


@_enterprise_query_tool
async def get_enterprise_VCPE_financing(
    company_name: str,
    filter_rounds: list[str] | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """获取企业创投融资信息：企业从风险投资机构、天使投资人、
    产业基金等获取的资金支持，记录融资轮次、融资金额、融资时间、投资机构等。

    Args:
        company_name: 企业工商登记全称。
        filter_rounds: 融资轮次筛选，如 ["天使轮","A轮","A+轮"]，不筛选不传。
        page: 页码，默认 1。
        page_size: 每页条数，默认 20。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    extra: dict = {}
    if filter_rounds:
        extra["filterType"] = filter_rounds
    body = _financing_events(company_name, _VCPE, extra, page, page_size)
    resp = await api_post(f"{_FINANCE_BASE}/query", body)
    return unwrap(resp)


@_enterprise_query_tool
async def get_enterprise_stock_financing(
    company_name: str,
    stock_types: list[str] | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """获取股票融资信息：企业通过发行股票、配股、增发等股权
    相关方式进行的融资，涉及发行日期、股票代码、发行价、发行数量、融资类型、
    融资金额及融资状态。

    Args:
        company_name: 企业工商登记全称。
        stock_types: 融资类型筛选，如 ["A股IPO"]，可选：A股IPO/A股增发/A股
            配股/港股IPO/港股增发/新三板发行；不筛选不传。
        page: 页码，默认 1。
        page_size: 每页条数，默认 20。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    extra: dict = {}
    if stock_types:
        child_types = []
        for item in stock_types:
            if isinstance(item, int) or str(item).isdigit():
                child_types.append(int(item))
            elif item in _STOCK_CHILD_TYPES:
                child_types.append(_STOCK_CHILD_TYPES[item])
        if child_types:
            extra["childType"] = child_types
    body = _financing_events(company_name, _STOCK, extra, page, page_size)
    resp = await api_post(f"{_FINANCE_BASE}/query", body)
    return unwrap(resp)


_RATING_FIELDS = ("bondRating", "creditLevel", "rating", "bondCreditRating", "creditRating")


def _match_rating(item: dict, rating: str) -> bool:
    for field in _RATING_FIELDS:
        value = item.get(field)
        if value and rating in str(value):
            return True
    return False


@_enterprise_query_tool
async def get_enterprise_bond_financing(
    company_name: str,
    bond_rating: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """获取债券融资信息：企业发行债券进行融资的情况，包括
    债券简称、代码、类型、评级、发行日期、规模、票面利率、期限、到期日期等。

    Args:
        company_name: 企业工商登记全称。
        bond_rating: 债券评级筛选，如 "AAA"，在返回结果内按评级字段过滤
        page: 页码，默认 1。
        page_size: 每页条数，默认 20。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    body = _financing_events(company_name, _BOND, {}, page, page_size)
    resp = await api_post(f"{_FINANCE_BASE}/query", body)
    result = unwrap(resp)
    if bond_rating and result["status"] == "success" and isinstance(result.get("data"), list):
        result["data"] = [item for item in result["data"] if _match_rating(item, bond_rating)]
    return result


@_enterprise_query_tool
async def get_enterprise_bondHolder(
    company_name: str, page: int = 1, page_size: int = 20
) -> dict:
    """获取债券持有人信息：企业债券在不同报告期的持有情况，呈现债券简称、
    代码、持有人名称、持仓市值、较上期变动、持仓数量及管理人等信息。

    Args:
        company_name: 企业工商登记全称。
        page: 页码，默认 1。
        page_size: 每页条数，默认 20。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    resp = await api_post(
        f"{_FINANCE_BASE}/finance/holder",
        {"companyName": company_name, "desc": True, "page": page, "pageSize": page_size},
    )
    return unwrap(resp)


@_enterprise_query_tool
async def get_enterprise_bank_financing(
    company_name: str, page: int = 1, page_size: int = 20
) -> dict:
    """获取银行借款信息：企业向银行等金融机构借入资金的信息，
    包含披露日期、银行名称、融资金额、利率、期限、起止日期、信息来源。

    Args:
        company_name: 企业工商登记全称。
        page: 页码，默认 1。
        page_size: 每页条数，默认 20。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    body = _financing_events(company_name, _BANK, {}, page, page_size)
    resp = await api_post(f"{_FINANCE_BASE}/query", body)
    return unwrap(resp)


@_enterprise_query_tool
async def get_enterprise_receivables_financing(
    company_name: str, page: int = 1, page_size: int = 20
) -> dict:
    """获取应收账款融资信息：企业以应收账款质押、应收账款
    转让为基础进行的融资活动，包含披露日期、质权人/受让人、融资金额、期限、
    起止日期、质让/转让财产价值、登记状态。

    Args:
        company_name: 企业工商登记全称。
        page: 页码，默认 1。
        page_size: 每页条数，默认 20。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    body = _financing_events(company_name, _RECEIVABLES, {}, page, page_size)
    resp = await api_post(f"{_FINANCE_BASE}/query", body)
    return unwrap(resp)


@_enterprise_query_tool
async def get_enterprise_leasing_financing(
    company_name: str, page: int = 1, page_size: int = 20
) -> dict:
    """获取租赁融资信息：企业通过租赁资产（如设备租赁等）
    实现的融资，包括披露日期、租赁类型、融资金额、利率、期限、起止日期、
    租赁资产价值、出租人等。

    Args:
        company_name: 企业工商登记全称。
        page: 页码，默认 1。
        page_size: 每页条数，默认 20。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    body = _financing_events(company_name, _LEASING, {}, page, page_size)
    resp = await api_post(f"{_FINANCE_BASE}/query", body)
    return unwrap(resp)


@_enterprise_query_tool
async def get_enterprise_trust_financing(
    company_name: str, page: int = 1, page_size: int = 20
) -> dict:
    """获取信托融资信息：企业通过信托机构进行融资的信息，
    如披露日期、信托公司、融资金额、利率、期限、起止日期、担保人等。

    Args:
        company_name: 企业工商登记全称。
        page: 页码，默认 1。
        page_size: 每页条数，默认 20。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    body = _financing_events(company_name, _TRUST, {}, page, page_size)
    resp = await api_post(f"{_FINANCE_BASE}/query", body)
    return unwrap(resp)


@_enterprise_query_tool
async def get_enterprise_credit_financing(
    company_name: str, page: int = 1, page_size: int = 20
) -> dict:
    """获取授信额度信息：银行等金融机构给予企业的授信额度情况，包括披露日期、
    截止日期、授信额度、已使用额度、未使用额度、授信家数等。

    数据源覆盖低（同组的 holder/outInvestment 均能正常出数据）。

    Args:
        company_name: 企业工商登记全称。
        page: 页码，默认 1。
        page_size: 每页条数，默认 20。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    resp = await api_post(
        f"{_FINANCE_BASE}/finance/creditLine",
        {"companyName": company_name, "desc": True, "page": page, "pageSize": page_size},
    )
    return unwrap(resp)


@_enterprise_query_tool
async def get_enterprise_outbound_investment(
    company_name: str,
    page: int = 1,
    page_size: int = 20,
    status_list: list[str] | None = None,
) -> dict:
    """获取企业对外投资信息：企业对外的投资布局，涉及投资对象、持股比例、
    企业状态。

    Args:
        company_name: 企业工商登记全称。
        page: 页码，默认 1。
        page_size: 每页条数，默认 20。
        status_list: 被投资企业状态筛选，如 ["存续"]，不筛选不传。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    body: dict = {
        "companyName": company_name, "desc": True, "page": page, "pageSize": page_size,
    }
    if status_list:
        body["statusList"] = status_list
    resp = await api_post(f"{_FINANCE_BASE}/finance/outInvestment", body)
    return unwrap(resp)


async def get_company_graphy(name: str = "", id: str = "", type: int = 0) -> dict:
    """查询企业关系网络：企业法定代表人/实控人/股东等投资任职关系网络，返回
     四层血缘关系。每个图节点可通过再次调用本工具进行迭代展开：
     - type=0（企业节点）：name=节点名称, id=节点id, type=0
     - type=1（人物节点）：name=节点名称, id=节点id, type=1

    Args:
        name: 节点名称（企业工商全称或人物姓名）。
        id: 节点唯一编号，已知时可直接传入。
        type: 节点类型，0=企业节点，1=人物节点。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    params = {}
    if type == 1:
        if id:
            params["personId"] = id
        elif name:
            params["name"] = name
    else:
        params["name"] = name or ""
    resp = await api_post("/cmp/companygraphy/companygraphy", params)
    result = unwrap(resp)
    if result.get("status") == "success" and result.get("data") is None:
        raise ToolError(f"未匹配到企业主体'{name}'，请调用主体识别服务的 search_enterprise_by_name 获取企业全称。")
    return result


@_enterprise_query_tool
async def get_businessFinance_graphy(company_name: str) -> dict:
    """查询融资关系网络：包含创投融资/股票融资/债券融资/银行借款/租赁融资/
    信托融资/应收账款融资等融资关系网。

    Args:
        company_name: 企业工商登记全称。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    resp = await api_post("/idis_industry/teis/businessFinance/atlas", {"companyName": company_name})
    return unwrap(resp)


@_enterprise_query_tool
async def get_query_winTenderer_tenderee(company_name: str) -> dict:
    """查询招投标信息：整合企业作为招标方（招标项目）和投标方（投标项目）的
    相关信息，全面呈现企业在招投标活动中的角色和行为。

    Args:
        company_name: 企业工商登记全称。

    Returns:
        status 及 data（成功时，data.招标项目 / data.投标项目）或
        error_message。
    """
    params = {"name": company_name}
    win_resp = await api_post("/cmp/detailOperation/winTenderer", {}, params=params)
    tenderee_resp = await api_post("/cmp/detailOperation/tenderee", {}, params=params)
    win = unwrap(win_resp)
    tenderee = unwrap(tenderee_resp)
    for part in (win, tenderee):
        if part["status"] != "success":
            return part
    merged = {"招标项目": win.get("data"), "投标项目": tenderee.get("data")}
    return {
        "status": "success",
        "data": merged,
        "状态码": "查询成功",
        "摘要": "查询成功。",
        "数据": merged,
    }
