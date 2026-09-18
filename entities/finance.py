"""创投融资 Sever（行业洞察 MCP 清单 - 创投融资sever.csv）工具实现。

9 个需求工具全部实现：早期获投企业列表（多维筛选 + 工商画像补全）、产业
基金列表、基金投资/退出事件批量查询、基金明细（基本信息/出资人/投资事件/
退出事件）、竞品融资差异对比。

基金名称消歧：基金明细按基金机构编号定位，工具内部先拿基金名称检索基金
列表解析编号；名称精确同名且唯一才自动采用，多个候选时返回「多候选」列表
请用户确认。基金批量列表的轮次/产业/退出方式筛选在工具内部按返回字段二次
过滤；融资金额区间（万元）在事件金额字段上过滤，金额未披露的事件在设置
区间时剔除。search_financing_companies 对首页前 10 家获投企业补全工商画像
（法人/注册资本/成立日期/省市区/所属产业/官网）与所属产业标签。
"""

import asyncio
from datetime import date, datetime, timedelta

from common.address import get_address
from common.api_client import api_get, api_post, unwrap
from common.business_protocol import multiple_candidates, no_data

_FINANCE_BASE = "/idis_industry/teis/v2/businessFinance"
_FUND_BASE = "/idis_industry/teis/fund"

_FILTER_SCAN_SIZE = 50  # 批量列表客户端过滤时最多扫描的条数


async def _resolve_region_fields(region_name: str) -> dict:
    """中文区域名 -> regionCode/province/city/county 字段；解析失败返回空 dict。

    注意：get_address 对省级区域会把 city 兜底成省名（address.py 的直辖市
    兜底逻辑），直接传 city=省名 会让 v2 businessFinance/query 查不到数据，
    所以 city 与 province 同名时不下发 city。
    """
    if not region_name:
        return {}
    result = get_address(address=region_name)
    if result["status"] != "success":
        return {}
    fields = {
        "regionCode": result.get("region_code", ""),
        "province": result.get("province_name", ""),
    }
    city = result.get("city_name", "")
    if city and city != fields["province"]:
        fields["city"] = city
    county = result.get("district_name", "")
    if county:
        fields["county"] = county
    return fields


async def _resolve_industry_fields(industry_name: str) -> dict:
    """中文产业名 -> industryCode/industryType；解析失败返回空 dict。"""
    if not industry_name:
        return {}
    from entities.entity_resolve import resolve_industry_code

    code, result = await resolve_industry_code(industry_name, "SELECTED")
    if code is None:
        return {}
    return {"industryCode": code, "industryType": "SELECTED"}


def _event_amount(item: dict) -> float | None:
    """从融资事件里取金额（统一折算为万元），取不到返回 None。"""
    for field in ("amount", "amountCny"):
        value = item.get(field)
        if value in (None, ""):
            continue
        if isinstance(value, (int, float)):
            amount = float(value)
        else:
            try:
                amount = float(str(value).replace(",", "").replace("，", ""))
            except ValueError:
                continue
        unit = str(item.get("unit") or "")
        if "亿" in unit:
            amount *= 10000
        return amount
    return None


def _filter_by_amount(items: list[dict], amount_min: float | None, amount_max: float | None) -> list[dict]:
    if amount_min is None and amount_max is None:
        return items
    kept = []
    for item in items:
        amount = _event_amount(item)
        if amount is None:
            continue  # 金额未披露的事件：设了金额区间时不保留
        if amount_min is not None and amount < amount_min:
            continue
        if amount_max is not None and amount > amount_max:
            continue
        kept.append(item)
    return kept


def _default_week_window() -> tuple[str, str]:
    end = date.today()
    start = end - timedelta(days=7)
    return start.isoformat(), end.isoformat()


async def search_financing_companies(
    start_date: str = "",
    end_date: str = "",
    industry: str = "",
    region: str = "",
    finance_rounds: list[str] | None = None,
    amount_min: float | None = None,
    amount_max: float | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """获取近期早期获投企业列表，支持融资时间/产业/区域/融资轮次/融资金额
    多维筛选（需求 p0 工具）。

    出参已按需求补全获投企业的所属产业、实控人、法人、注册资本、成立年限、
    所属省/市/区、企业简介、官网。

    Args:
        start_date: 融资开始日期，格式 yyyy-MM-dd（如 2026-08-10），不传
            默认最近 7 天。
        end_date: 融资结束日期，格式 yyyy-MM-dd，不传默认今天。
        industry: 产业名称（如"人工智能"），内部解析为产业代码后筛选，
            不筛选传空字符串。
        region: 区域名称（如"江苏省"），不筛选传空字符串。
        finance_rounds: 融资轮次筛选，如 ["种子轮", "天使轮", "Pre-A轮", "A轮", "A+轮"]，不筛选不传。
        amount_min: 融资金额区间下限（单位：万元），仅传该值代表筛选金额
            >= 该值的企业。
        amount_max: 融资金额区间上限（单位：万元），仅传该值代表筛选金额
            <= 该值的企业。金额未披露的事件在设了区间时会被过滤。
        page: 页码，默认 1。
        page_size: 每页条数，默认 20。

    Returns:
        status 及 data（成功时，事件列表已带工商信息/所属产业补全字段）或
        error_message。
    """
    if not start_date and not end_date:
        start_date, end_date = _default_week_window()
    body: dict = {
        "page": page,
        "pageSize": page_size,
        "startDate": start_date,
        "endDate": end_date,
        "industryCodeRecursive": False,
        "financeType": 1,
        "tp": 2,
    }
    region_fields = await _resolve_region_fields(region)
    if region_fields:
        body.update(region_fields)
    industry_fields = await _resolve_industry_fields(industry)
    if industry_fields:
        body.update(industry_fields)
    if finance_rounds:
        body["originalType"] = finance_rounds

    resp = await api_post(f"{_FINANCE_BASE}/query", body)
    if not resp.get("success"):
        return unwrap(resp)
    data = resp.get("data")
    if isinstance(data, list):
        events = data
    elif isinstance(data, dict):
        events = data.get("list") or data.get("records") or data.get("datas") or data.get("data") or []
    else:
        events = []
    if not isinstance(events, list):
        events = []

    events = _filter_by_amount(events, amount_min, amount_max)

    # 从 financierDetailItems 中提取企业信息，替代额外的 API 查询
    enriched = []
    for item in events:
        fdi = item.get("financierDetailItems")
        if isinstance(fdi, list) and fdi:
            detail = fdi[0]
            bi = detail.get("basicInfo") or {}
            ci = detail.get("controlInfo") or []
            ii = detail.get("industryInfo") or {}
            # 法人
            lp = bi.get("legalPersonList")
            if isinstance(lp, list) and lp and isinstance(lp[0], dict):
                item["法人"] = lp[0].get("legalPersonName")
            # 注册资本
            if bi.get("registeredCapital"):
                item["注册资本"] = bi["registeredCapital"]
            # 成立日期 + 成立年限
            if bi.get("establishmentDate"):
                item["成立日期"] = bi["establishmentDate"]
                try:
                    dt = datetime.strptime(bi["establishmentDate"][:10], "%Y-%m-%d")
                    now = datetime.now()
                    years = now.year - dt.year - ((now.month, now.day) < (dt.month, dt.day))
                    item["成立年限"] = f"{years}年"
                except (ValueError, IndexError):
                    pass
            # 企业简介
            if bi.get("companyProfile"):
                item["企业简介"] = bi["companyProfile"]
            # 官网
            if bi.get("website"):
                item["官网"] = bi["website"]
            # 实控人
            if isinstance(ci, list) and ci and isinstance(ci[0], dict):
                pkey = ci[0].get("pkeyName")
                if pkey:
                    item["实控人"] = pkey
            # 新华产业
            sil = ii.get("selectedIndustryList")
            if isinstance(sil, list):
                names = [s.get("industryName") for s in sil if isinstance(s, dict) and s.get("industryName")]
                if names:
                    item["新华产业"] = names
            # 国标产业
            gil = ii.get("gbIndustryList")
            if isinstance(gil, list):
                names = [s.get("industryName") for s in gil if isinstance(s, dict) and s.get("industryName")]
                if names:
                    item["国标产业"] = names
            # 国战新产业
            nil = ii.get("nseiIndustryList")
            if isinstance(nil, list):
                names = [s.get("industryName") for s in nil if isinstance(s, dict) and s.get("industryName")]
                if names:
                    item["国战新产业"] = names
        enriched.append(item)
    events = enriched

    # 出参按中文映射配置翻译字段名（financeType=1 -> FinanceQuery_1 翻译表）
    from common.field_mapper import translate

    result = unwrap(resp)
    events_out = translate(events, f"{_FINANCE_BASE}/query", finance_type=1)
    result["data"] = events_out
    result["数据"] = events_out
    result["摘要"] = f"查询成功，共返回 {len(events_out)} 条早期获投企业事件。"
    return result


async def get_industryFund_list(
    region: str = "",
    keyword: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """查询产业基金列表：获取所有产业基金（如私募股权基金、创投基金等），
    包含基金名称、运作状态、基金类型、注册资本、实缴资本、国企持股比例、
    基金管理人、所属区域、成立日期等。

    province 区域筛选与 keyword 名称检索生效，fundName 参数不生效）。

    Args:
        region: 区域名称（如"江苏省"），不筛选传空字符串。
        keyword: 基金名称关键词（如"毅达"），不筛选传空字符串。
        page: 页码，默认 1。
        page_size: 每页条数，默认 20。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    body: dict = {"pageNow": page, "pageSize": page_size}
    region_fields = await _resolve_region_fields(region)
    if region_fields:
        body.update(region_fields)
    if keyword:
        body["keyword"] = keyword
    resp = await api_post(f"{_FUND_BASE}/industry/list", body)
    return unwrap(resp)


async def _resolve_fund_org_id(fund_name: str) -> tuple[str | None, str | None, dict | None]:
    """基金名称 -> fundOrgId：纯数字直接当 fundOrgId；否则 keyword 检索基金
    列表，精确同名唯一命中才自动采用，多候选时返回候选列表交上层确认。

    Returns:
        (fund_org_id, resolved_name, None) —— 解析成功
        (None, None, error_dict) —— 失败/多候选（error_dict.status 为
        error 或 ambiguous）
    """
    if not fund_name:
        return None, None, {"status": "error", "error_message": "基金名称不能为空"}
    if fund_name.isdigit():
        return fund_name, fund_name, None
    resp = await api_post(
        f"{_FUND_BASE}/industry/list",
        {"keyword": fund_name, "pageNow": 1, "pageSize": 10},
    )
    # 内部读原始响应（英文字段），出参翻译统一在 MCP 边界做
    if not resp.get("success"):
        return None, None, {"status": "error", "error_message": str(resp.get("msg") or "基金列表查询失败。")}
    data = resp.get("data") or {}
    items = data.get("list") or []
    if not items:
        return None, None, {
            "status": "error",
            "error_message": f"没检索到名称包含'{fund_name}'的基金，请确认基金名称。",
        }
    exact = [item for item in items if item.get("fundName") == fund_name]
    if len(exact) == 1:
        first = exact[0]
        return str(first.get("fundOrgId")), str(first.get("fundName")), None
    if len(items) == 1:
        first = items[0]
        return str(first.get("fundOrgId")), str(first.get("fundName")), None
    return None, None, {
        "status": "ambiguous",
        "message": f"'{fund_name}'匹配到 {len(items)} 只基金，无法自动确定，请从候选里确认后再查。",
        "candidates": [
            {"fundOrgId": str(i.get("fundOrgId")), "fundName": str(i.get("fundName"))}
            for i in items[:10]
        ],
    }


_ROUND_ALIASES = {
    "未披露": {"未披露", "NOT_FINANCED"},
    "天使轮": {"种子/天使", "天使", "种子", "ANGEL"},
    "A轮": {"A", "A_ROUND"},
    "A+轮": {"A+"},
    "B轮": {"B", "B_ROUND"},
    "B+轮": {"B+"},
    "C轮": {"C", "C_ROUND"},
    "C+轮": {"C+"},
    "D轮及以上": {"D", "D_ROUND_AND_ABOVE"},
    "战略投资": {"战略投资", "STRATEGIC_INVESTMENT"},
    "基石投资": {"基石投资", "STONE_INVESTMENT"},
    "Pre-A": {"Pre-A"},
    "Pre-IPO": {"Pre-IPO"},
    "其他": {"其他", "OTHER", "中投多轮"},
}


def _round_core(text: str) -> str:
    return str(text or "").strip().rstrip("轮")


def _round_matches(round_name: str, round_filter: str) -> bool:
    """轮次匹配：把中文轮次名（A轮/A+轮/天使轮）与 API 短代码（A/A+/种子/
    天使轮）归一化后精确匹配，避免"A轮"与"A+"误匹配。"""
    name = _round_core(round_name)
    f = _round_core(round_filter)
    if not name or not f:
        return False
    targets = _ROUND_ALIASES.get(f)
    if targets is None:
        for key, values in _ROUND_ALIASES.items():
            if f in values:
                targets = values
                break
    if targets is None:
        targets = {f}
    return name in targets


def _item_matches_investment(item: dict, rounds, industry, region, status) -> bool:
    if rounds:
        round_name = str(item.get("roundName") or "")
        if not any(_round_matches(round_name, r) for r in rounds):
            return False
    if status and status not in str(item.get("companyStatus") or ""):
        return False
    if region:
        where = "".join(
            str(item.get(k) or "") for k in ("province", "city", "county")
        )
        region_norm = region.replace("省", "").replace("市", "").replace("区", "").replace("县", "")
        if region_norm and region_norm not in where:
            return False
    if industry:
        industry_info = item.get("industryInfo") or {}
        names, codes = [], []
        if isinstance(industry_info, dict):
            for key, values in industry_info.items():
                if isinstance(values, list):
                    for value in values:
                        if isinstance(value, dict):
                            names.append(str(value.get("industryName") or ""))
                            codes.append(str(value.get("industryCode") or ""))
        if not any(industry in name for name in names) and not any(industry in code for code in codes):
            return False
    return True


_ROUND_ENUM_MAP = {
    "未披露": "NOT_FINANCED",
    "种子/天使轮": "ANGEL",
    "A轮": "A_ROUND",
    "B轮": "B_ROUND",
    "C轮": "C_ROUND",
    "D轮及以上": "D_ROUND_AND_ABOVE",
    "战略投资": "STRATEGIC_INVESTMENT",
    "基石投资": "STONE_INVESTMENT",
    "其他": "OTHER",
}


def _parse_rounds(finance_rounds: str) -> list[str] | None:
    """把汉字枚举（；分隔）解析并映射为 API 的 roundIn 枚举值列表。"""
    if not finance_rounds:
        return None
    codes = []
    for part in str(finance_rounds).replace("；", ";").split(";"):
        part = part.strip()
        if not part:
            continue
        code = _ROUND_ENUM_MAP.get(part)
        if code is None:
            return None
        codes.append(code)
    return codes or None


async def search_industryFund_investmen_list(
    start_date: str = "",
    end_date: str = "",
    finance_rounds: str = "",
    industry: str = "",
    region: str = "",
    status: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """批量查询多只基金投资事件列表：识别基金直接投资偏好、产业热点和资金
    流向，包括投资日期、被投企业、参投产业基金、投资轮次、被投年限、所属
    地区、所属产业。

    Args:
        start_date: 投资开始日期，格式 yyyy-MM-dd，不筛选传空字符串。
        end_date: 投资结束日期，格式 yyyy-MM-dd。
        finance_rounds: 投资轮次筛选，仅可输入以下汉字枚举值，多个以"；"
            或";"分隔：未披露/种子/天使轮/A轮/B轮/C轮/D轮及以上/战略投资/
            基石投资/其他；不筛选传空字符串。
        industry: 产业 code（需先调用 get_industry_tree 获取），多个以"；"
            或";"分隔（如 "XHICC005002；XHICC005001"），不筛选传空字符串。
        region: 区域名称（如"江苏省"），不筛选传空字符串。
        status: 被投企业经营状态筛选（如"存续"），不筛选传空字符串。
        page: 页码，默认 1。
        page_size: 每页条数，默认 20。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    body: dict = {"startDate": start_date, "endDate": end_date, "pageNow": 1, "pageSize": _FILTER_SCAN_SIZE}
    round_codes = _parse_rounds(finance_rounds)
    if round_codes:
        body["roundIn"] = round_codes
    resp = await api_post(f"{_FUND_BASE}/investment/list", body)
    # 内部读原始响应（英文字段），出参翻译统一在 MCP 边界做
    if not resp.get("success"):
        return unwrap(resp)
    items = ((resp.get("data") or {}).get("list")) or []
    if industry or region or status:
        items = [i for i in items if _item_matches_investment(i, None, industry, region, status)]
    start = (page - 1) * page_size
    result = unwrap(resp)
    result["data"] = items[start:start + page_size]
    result["数据"] = result["data"]
    result["摘要"] = f"查询成功，过滤后共 {len(items)} 条投资事件，返回第 {page} 页 {len(result['data'])} 条。"
    return result


async def get_industryFund_exit_list(
    start_date: str = "",
    end_date: str = "",
    exit_types: list[str] | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """批量查询多只基金退出事件列表：评估从被投项目中退出基金的情况与收益，
    包含退出基金、被投企业、退出日期、退出方式、交易场所、账面回报倍数、
    内部收益率、总投资、退出金额、持股变动。

    100 条事件。

    Args:
        start_date: 退出开始日期，格式 yyyy-MM-dd，不筛选传空字符串。
        end_date: 退出结束日期，格式 yyyy-MM-dd。
        exit_types: 退出方式筛选，如 ["IPO","股权转让"]，不筛选不传。
        page: 页码，默认 1。
        page_size: 每页条数，默认 20。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    body: dict = {"startDate": start_date, "endDate": end_date, "pageNow": 1, "pageSize": _FILTER_SCAN_SIZE}
    resp = await api_post(f"{_FUND_BASE}/exit/list", body)
    # 内部读原始响应（英文字段），出参翻译统一在 MCP 边界做
    if not resp.get("success"):
        return unwrap(resp)
    items = ((resp.get("data") or {}).get("list")) or []
    if exit_types:
        items = [i for i in items if any(t in str(i.get("exitType") or "") for t in exit_types)]

    # 基金明细补全：为每个退出事件补全基金的简介和注册地址
    fund_ids = set()
    for item in items:
        fund_id = item.get("fundOrgId")
        if fund_id:
            fund_ids.add(str(fund_id))
    fund_details = {}
    if fund_ids:

        async def _fetch_fund_detail(fund_id):
            resp = await api_post(f"{_FUND_BASE}/detail/basic", {"fundOrgId": fund_id})
            if resp.get("success") and isinstance(resp.get("data"), dict):
                detail = resp["data"]
                return fund_id, {
                    "简介": detail.get("fundIntro") or "",
                    "注册地址": detail.get("registeredAddress") or "",
                }
            return fund_id, {}

        results = await asyncio.gather(*(_fetch_fund_detail(fid) for fid in fund_ids))
        for fid, detail in results:
            if detail:
                fund_details[fid] = detail
    for item in items:
        fund_id = str(item.get("fundOrgId") or "")
        if fund_id in fund_details:
            item["简介"] = fund_details[fund_id]["简介"]
            item["注册地址"] = fund_details[fund_id]["注册地址"]

    start = (page - 1) * page_size
    result = unwrap(resp)
    result["data"] = items[start:start + page_size]
    result["数据"] = result["data"]
    result["摘要"] = f"查询成功，过滤后共 {len(items)} 条退出事件，返回第 {page} 页 {len(result['data'])} 条。"
    return result


async def get_fund_detail_basic(fund_name: str) -> dict:
    """查询基金基本信息：基金类型、基金管理人、管理类型、成立日期、资本类型、
    目标规模、募集状态、简介等。

    定位基金（fundName/fundNo 都不生效），工具内部先用基金名称关键词检索
    基金列表解析 fundOrgId（纯数字入参视为 fundOrgId 直接使用；名称匹配到
    多只基金时返回候选列表请用户确认）。

    Args:
        fund_name: 基金名称（如"国家制造业转型升级基金股份有限公司"）或
            fundOrgId。

    Returns:
        status 及 data（成功时）或 error_message；多候选时返回候选列表。
    """
    fund_org_id, resolved_name, error = await _resolve_fund_org_id(fund_name)
    if error:
        if error.get("status") == "ambiguous":
            return multiple_candidates("基金", fund_name, error.get("candidates", []))
        return error
    resp = await api_post(f"{_FUND_BASE}/detail/basic", {"fundOrgId": fund_org_id})
    result = unwrap(resp)
    if result["status"] == "success":
        result["基金名称"] = resolved_name
    return result


async def get_fund_detail_investor_list(
    fund_name: str, page: int = 1, page_size: int = 20
) -> dict:
    """查询基金出资人：基金背后的关键出资方，包括出资人名称、出资人类型、
    所属地区、是否国企、持股比例、认缴出资额。

    定位，见 get_fund_detail_basic 说明）。

    Args:
        fund_name: 基金名称或 fundOrgId。
        page: 页码，默认 1。
        page_size: 每页条数，默认 20。

    Returns:
        status 及 data（成功时）或 error_message；多候选时返回候选列表。
    """
    fund_org_id, resolved_name, error = await _resolve_fund_org_id(fund_name)
    if error:
        if error.get("status") == "ambiguous":
            return multiple_candidates("基金", fund_name, error.get("candidates", []))
        return error
    resp = await api_post(
        f"{_FUND_BASE}/detail/investor/list",
        {"fundOrgId": fund_org_id, "pageNow": page, "pageSize": page_size},
    )
    result = unwrap(resp)
    if result["status"] == "success":
        result["基金名称"] = resolved_name
    return result


async def get_fund_detail_investment_list(
    fund_name: str,
    start_date: str = "",
    end_date: str = "",
    finance_rounds: str = "",
    industry: str = "",
    region: str = "",
    status: str = "",
) -> dict:
    """查询基金投资事件：该基金通过直接或间接投资的全部项目明细，反映资金
    流向与布局偏好，包含投资日期、被投企业、参投产业基金、投资轮次、被投
    年限、投资方式、所属地区、所属产业。返回接口获取到的全部数据。

    Args:
        fund_name: 基金名称或 fundOrgId。
        start_date: 投资开始日期，格式 yyyy-MM-dd，不筛选传空字符串。
        end_date: 投资结束日期，格式 yyyy-MM-dd。
        finance_rounds: 融资轮次筛选，仅可输入以下汉字枚举值，多个以"；"
            或";"分隔：未披露/种子/天使轮/A轮/B轮/C轮/D轮及以上/战略投资/
            基石投资/其他；不筛选传空字符串。
        industry: 产业 code（需先调用 get_industry_tree 获取），多个以"；"
            或";"分隔（如 "XHICC005002；XHICC005001"），不筛选传空字符串。
        region: 区域名称（如"江苏省"），不筛选传空字符串。
        status: 被投企业经营状态筛选（如"存续"），不筛选传空字符串。

    Returns:
        status 及 data（成功时）或 error_message；多候选时返回候选列表。
    """
    fund_org_id, resolved_name, error = await _resolve_fund_org_id(fund_name)
    if error:
        if error.get("status") == "ambiguous":
            return multiple_candidates("基金", fund_name, error.get("candidates", []))
        return error
    body: dict = {
        "fundOrgId": fund_org_id,
        "pageNow": 1,
        "pageSize": 1000,
        "startDate": start_date,
        "endDate": end_date,
    }
    round_codes = _parse_rounds(finance_rounds)
    if round_codes:
        body["roundIn"] = round_codes
    if industry:
        industry_codes = [
            c.strip() for c in industry.replace("；", ";").split(";") if c.strip()
        ]
        if industry_codes:
            body["industryIn"] = [{
                "industryType": "SELECTED",
                "industryCodeIn": industry_codes,
                "industryCodeRecursive": True,
            }]
    resp = await api_post(f"{_FUND_BASE}/detail/investment/list", body)
    if not resp.get("success"):
        return unwrap(resp)
    items = ((resp.get("data") or {}).get("list")) or []

    # 投资明细补全：逐条查询投资明细接口获取投资金额、持股比例
    async def _fetch_investment_detail(item):
        invest_id = item.get("investId") or item.get("id") or item.get("investmentId")
        if not invest_id:
            return
        resp = await api_post("/idis_industry/teis/fund/investment/detail", {"investId": invest_id})
        if resp.get("success") and isinstance(resp.get("data"), dict):
            detail = resp["data"]
            if detail.get("investmentAmount") and not item.get("investmentAmount"):
                item["investmentAmount"] = detail["investmentAmount"]
            if detail.get("stake") is not None and not item.get("shareRatio"):
                item["shareRatio"] = detail["stake"]
            if detail.get("investmentMode") and not item.get("investmentMode"):
                item["investmentMode"] = detail["investmentMode"]

    await asyncio.gather(*(_fetch_investment_detail(item) for item in items))

    result = unwrap(resp)
    result["基金名称"] = resolved_name
    result["data"] = items
    result["数据"] = items
    result["摘要"] = f"查询成功，共返回 {len(items)} 条投资事件。"
    return result


async def get_fund_detail_exit_list(
    fund_name: str,
    start_date: str = "",
    end_date: str = "",
    exit_types: list[str] | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """查询退出事件：该基金通过直接或间接投资方式从已投项目中退出的方式、
    收益表现，包含退出基金、被投企业、退出日期、投资方式、退出方式、交易
    场所、账面回报倍数、内部收益率、总投资、退出金额、持股变动。

    Args:
        fund_name: 基金名称或 fundOrgId。
        start_date: 退出开始日期，格式 yyyy-MM-dd，不筛选传空字符串。
        end_date: 退出结束日期，格式 yyyy-MM-dd。
        exit_types: 退出方式筛选，如 ["IPO","股权转让"]，不筛选不传。
        page: 页码，默认 1。
        page_size: 每页条数，默认 20。

    Returns:
        status 及 data（成功时）或 error_message；多候选时返回候选列表。
    """
    fund_org_id, resolved_name, error = await _resolve_fund_org_id(fund_name)
    if error:
        if error.get("status") == "ambiguous":
            return multiple_candidates("基金", fund_name, error.get("candidates", []))
        return error
    resp = await api_post(
        f"{_FUND_BASE}/detail/exit/list",
        {"fundOrgId": fund_org_id, "pageNow": 1, "pageSize": _FILTER_SCAN_SIZE},
    )
    # 内部读原始响应（英文字段），出参翻译统一在 MCP 边界做
    if not resp.get("success"):
        return unwrap(resp)
    items = ((resp.get("data") or {}).get("list")) or []
    if start_date:
        items = [i for i in items if str(i.get("exitDate") or "") >= start_date]
    if end_date:
        items = [i for i in items if str(i.get("exitDate") or "") <= end_date]
    if exit_types:
        items = [i for i in items if any(t in str(i.get("exitType") or "") for t in exit_types)]
    start = (page - 1) * page_size
    result = unwrap(resp)
    result["基金名称"] = resolved_name
    result["data"] = items[start:start + page_size]
    result["数据"] = result["data"]
    result["摘要"] = f"查询成功，过滤后共 {len(items)} 条退出事件，返回第 {page} 页 {len(result['data'])} 条。"
    return result


# ---------------------------------------------------------------------------
# 竞品融资差异（需求标注为新接口开发：通过相似公司检索 + 融资事件对比实现）
# ---------------------------------------------------------------------------

_TOP_VC_INSTITUTIONS = {
    "红杉", "高瓴", "经纬", "启明", "毅达资本", "IDG", "深创投", "君联资本",
    "达晨财智", "高榕创投", "五源资本", "纪源资本", "源码资本", "中金资本",
    "元禾控股", "哈勃投资", "中芯聚源",
}

# 轮次先后顺序（用于融资阶段比较；不在表内的轮次按事件时间顺序兜底）
_ROUND_ORDER = [
    "种子轮", "天使轮", "Pre-A", "A轮", "A+轮", "Pre-B", "B轮", "B+轮",
    "C轮", "C+轮", "D轮", "E轮", "F轮", "增资", "战略投资", "并购", "IPO",
]


def _round_index(round_name: str) -> int:
    for idx, name in enumerate(_ROUND_ORDER):
        if name in (round_name or ""):
            return idx
    return -1


def _latest_round_name(rounds: list) -> str:
    best, best_idx = "", -1
    for item in rounds:
        name = item if isinstance(item, str) else str(item.get("originalType") or item.get("round") or item.get("financeRound") or "")
        idx = _round_index(name)
        if idx > best_idx:
            best, best_idx = name, idx
    if not best:
        # 轮次名不在已知顺序表里时，按事件倒序取最近一条的轮次名
        best = next((r for r in reversed(rounds) if r), "")
    return best


async def _company_finance_snapshot(company_name: str) -> dict:
    """取企业创投融资快照：最新轮次、累计投资方、投资年份区间、累计金额。
    内部读原始英文字段（finance/query 出参在工具边界才会被翻译成中文）。"""
    resp = await api_post(
        f"{_FINANCE_BASE}/query",
        {"companyName": company_name, "financeType": 1, "desc": True, "page": 1, "pageSize": 20},
    )
    if not resp.get("success"):
        return {"企业名称": company_name, "融资事件": []}
    data = resp.get("data")
    events = data if isinstance(data, list) else (data or {}).get("list") or []
    if not isinstance(events, list):
        events = []
    rounds = [
        str(e.get("type2") or e.get("originalType") or "")
        for e in events if isinstance(e, dict)
    ]
    investors: list[str] = []
    years: list[int] = []
    total_amount = 0.0
    has_amount = False
    for e in events:
        if not isinstance(e, dict):
            continue
        investor_items = e.get("investorItems") or []
        if isinstance(investor_items, list):
            for inv in investor_items:
                if isinstance(inv, dict) and inv.get("company"):
                    investors.append(str(inv["company"]))
        date_text = str(e.get("financeDate") or e.get("investDate") or e.get("date") or "")
        if date_text and len(date_text) >= 4:
            try:
                years.append(int(date_text[:4]))
            except ValueError:
                pass
        amount = _event_amount(e)
        if amount is not None and amount > 0:
            total_amount += amount
            has_amount = True
    head_investors = [i for i in investors if any(vc in i for vc in _TOP_VC_INSTITUTIONS)]
    return {
        "企业名称": company_name,
        "最新轮次": _latest_round_name(rounds) if rounds else "无公开融资",
        "投资方": sorted(set(investors))[:10],
        "头部机构参与": sorted(set(head_investors)) or "无",
        "首次融资年份": min(years) if years else None,
        "最新融资年份": max(years) if years else None,
        "累计融资金额(万元)": total_amount if has_amount else "未披露",
        "融资事件数": len(events),
    }


def _regcap_to_wan(text: str) -> float | None:
    try:
        value = float(str(text).replace(",", "").replace("，", ""))
    except ValueError:
        return None
    if "亿" in text:
        value *= 10000
    return value


async def get_query_competitive_Finance(
    company_name: str,
    similar_types: list[str] | None = None,
    page_size: int = 8,
) -> dict:
    """查询竞品公司融资差异：查询竞品与本公司融资阶段差异（需求标注的新接口）。

    实现方式（按需求给出的相似度维度做组合）：
    1. 取目标企业工商信息与标签，得到所属产业代码、区域、企业性质、注册资本；
    2. 按相似类型（相同产业/相同区域/相同企业性质/相似融资经历等）搜索同业
       公司；相似注册规模在候选里按注册资本接近度排序；
    3. 逐家取创投融资快照（最新轮次、投资方组合、投资年份区间、累计金额），
       与本公司的快照对比，输出融资阶段差异表。

    Args:
        company_name: 企业工商登记全称（如"比亚迪股份有限公司"）。
        similar_types: 相似类型，可选：相同产业/相同区域/相似注册规模/
            相似融资经历/相同科技资质/相同荣誉榜单/相同组织类型/相同企业
            性质；不传默认按"相同产业"检索竞品。其中相同科技资质/相同荣誉
            榜单在搜索接口无对应筛选参数，归入相同产业维度处理。
        page_size: 参与对比的竞品数量上限，默认 8。

    Returns:
        status 及 data（成功时，data.本公司 / data.竞品对比列表）或
        error_message。
    """
    # 内部统一读原始响应（英文字段），不做中文翻译
    basic_resp = await api_post("/cmp/detail/basic", {}, params={"name": company_name})
    if not basic_resp.get("success") or not basic_resp.get("data"):
        return {"status": "error", "error_message": f"未找到企业'{company_name}'的工商信息，无法检索竞品。"}
    basic_data = basic_resp["data"]

    tags_resp = await api_get("/idis_industry/teis/landing/company/get", {"companyName": company_name})
    nature = ""
    if tags_resp.get("success") and isinstance(tags_resp.get("data"), dict):
        basic_info = tags_resp["data"].get("basicInfo") or {}
        nature = str(basic_info.get("companyNature") or "")

    industry_code = basic_data.get("industrycoCode") or ""
    industry_name = basic_data.get("industrycoName") or ""
    province = basic_data.get("province") or ""
    regcap_text = str(basic_data.get("regcapName") or basic_data.get("registeredCapital") or "")

    selected = set(similar_types or ["相同产业"])
    search_body: dict = {"pageNow": 1, "pageSize": page_size + 10, "sortCol": 1, "sortType": 1}
    if ("相同产业" in selected or "相同科技资质" in selected or "相同荣誉榜单" in selected) and industry_code:
        search_body["industryCodeIn"] = [industry_code]
        search_body["industryType"] = "CSF"
    if "相同区域" in selected and province:
        fields = await _resolve_region_fields(province)
        if fields:
            search_body["regionInfo"] = [{"name": province, "code": fields["regionCode"]}]
    if "相同企业性质" in selected and nature:
        search_body["natures"] = [nature]
    if "相同组织类型" in selected:
        type_name = str(basic_data.get("typeName") or "")
        if type_name:
            base_type = type_name.split("(")[0]
            if base_type:
                search_body["types"] = [base_type]
    if "相似融资经历" in selected:
        search_body["peNested"] = "TRUE"

    search_resp = await api_post("/idis_industry/teis/company/search/go", search_body)
    if not search_resp.get("success"):
        return unwrap(search_resp)
    search_data = search_resp.get("data") or {}
    peers = search_data.get("list") or search_data.get("records") or search_data.get("datas") or []
    if not isinstance(peers, list):
        peers = []
    peer_names = [
        str(p.get("companyName") or p.get("name") or p.get("entname") or "")
        for p in peers if isinstance(p, dict)
    ]
    peer_names = [n for n in peer_names if n and n != company_name][: page_size + 10]

    if "相似注册规模" in selected and peer_names:
        target_cap = _regcap_to_wan(regcap_text)
        if target_cap:
            caps: dict[str, float | None] = {}

            async def fetch_cap(name: str):
                resp = await api_post("/cmp/detail/basic", {}, params={"name": name})
                if resp.get("success") and isinstance(resp.get("data"), dict):
                    caps[name] = _regcap_to_wan(
                        str(resp["data"].get("regcapName") or resp["data"].get("registeredCapital") or "")
                    )

            await asyncio.gather(*(fetch_cap(name) for name in peer_names[:20]))
            peer_names = sorted(
                peer_names,
                key=lambda n: abs((caps.get(n) or 0) - target_cap),
            )

    peer_names = peer_names[:page_size]
    if not peer_names:
        return no_data("未检索到符合条件的竞品公司。")

    mine = await _company_finance_snapshot(company_name)
    snapshots = await asyncio.gather(*(_company_finance_snapshot(name) for name in peer_names))
    return {
        "status": "success",
        "data": {
            "本公司": {**mine, "所属产业": industry_name},
            "竞品对比列表": list(snapshots),
            "相似类型": sorted(selected),
        },
        "状态码": "查询成功",
        "摘要": f"查询成功，完成本公司与 {len(snapshots)} 家竞品的融资阶段对比。",
    }
