"""区域信息查询：评分排名、企业统计、融资分析、十四五重点产业、企业搜索、
园区列表、宏观经济指标（GDP/财政/债务/CPI-PPI/社会融资规模）。

`/macro/macroZs/...` 这批也接了——虽然概念上属于"宏观经济"，但走的是跟
`/idis_industry/...` 同一个共享网关、同一套鉴权，技术上就是这个 MCP 能直接
调的接口，不需要等宏观经济那个独立 MCP（ES+MySQL）才能用。

消歧用的是 get_address（本地行政区划表，不依赖 Milvus），它现在会返回完整
的 province_name/city_name/district_name 三级 breadcrumb，不只是最底层那个
代码——这批接口里有一半都要求 province（有时还要 city/county）跟 regionCode
一起传，缺这个 breadcrumb 就做不了。
"""

from datetime import datetime

from common.address import get_address
from common.api_client import api_get, api_post, unwrap
from common.business_protocol import 唯一匹配, 多候选, 未匹配, 调用失败
from models.entity_refs import RegionRef

_STAT_ENDPOINTS = {
    "分类数量": ("/idis_industry/teis/city/tabcompany", {}),
    "存量规模": ("/idis_industry/teis/city/companycount", {"companyType": "全部企业"}),
    "成立年限": ("/idis_industry/teis/city/comageper", {"companyType": "全部企业"}),
    "注册资本": ("/idis_industry/teis/city/comregcapper", {"companyType": "全部企业"}),
    "新增数量": ("/idis_industry/teis/city/companyadd", {"companyType": "全部企业"}),
    "注销吊销数量": ("/idis_industry/teis/city/companycanrev", {"companyType": "全部企业"}),
    "Top10行业": (
        "/idis_industry/teis/city/top10industry",
        {"companyType": "全部企业", "industryType": "GB"},
    ),
    "高新技术企业": ("/idis_industry/teis/city/hightech", {}),
    "科创板上市": ("/idis_industry/teis/city/ipo", {}),
    "荣誉榜单": ("/idis_industry/teis/city/awardlist", {}),
}


async def resolve_region(query: str) -> dict:
    """识别行政区域名称或代码，返回区域查询所需的标准字段。"""
    region, result = await _resolve_region(query)
    if result:
        if result.get("status") == "ambiguous":
            candidates = result.get("candidates", [])
            return 多候选("区域", query, candidates) if candidates else 未匹配("区域", query)
        return 调用失败(result.get("error_message", "区域消歧调用失败。"))
    return 唯一匹配("区域", query, {
        "region_code": region["region_code"],
        "region_name": region["region_name"],
        "province_name": region.get("province_name", ""),
        "city_name": region.get("city_name", ""),
        "district_name": region.get("district_name", ""),
    })


async def _resolve_region(region_name_or_code: str) -> tuple[dict | None, dict | None]:
    """消歧落脚点：本质是套壳 get_address，统一在这里做一次，region.py 里所有
    工具都从这一个函数拿 region_code/province_name/city_name/district_name。

    Returns:
        (fields, None) —— fields = {"region_code","region_name","province_name","city_name","district_name"}
        (None, ambiguous_dict)
    """
    result = get_address(address=region_name_or_code)
    if result["status"] != "success":
        return None, {
            "status": "ambiguous",
            "message": f"没能识别地区'{region_name_or_code}'。",
            "error_detail": result.get("error_message"),
        }
    return result, None


async def region_score(region_ref: RegionRef, year: str = "") -> dict:
    """查询区域各维度评分（经济实力/资源配置/产业状况/发展动力/政策环境/创新
    能力/债务负担/财政实力/舆情）及综合评分全国排名。

    Args:
        region_name_or_code: 区域名称（如"上海市""浦东新区"）或行政区划代码。
        year: 查询年份，不传默认当前年份。实测评分数据有滞后（截至目前
            2025/2026 年还没有数据），当年查不到时自动往前退一年再试一次。

    Returns:
        status 及 data（含 scores 各维度评分、rank 排名信息）或 error_message。
    """
    region = region_ref

    start_year = int(year) if year else datetime.now().year
    for y in (start_year, start_year - 1):
        params = {"city": region["city_name"], "year": str(y), "regionCode": region["region_code"]}
        scores_resp = await api_get("/idis_industry/teis/cityScore/cityScores", params)
        info_resp = await api_get("/idis_industry/teis/cityScore/cityInfo", params)
        scores = unwrap(scores_resp)
        info = unwrap(info_resp)
        if scores["status"] != "success":
            return scores
        if scores["data"]:
            return {
                "status": "success",
                "data": {"year": y, "scores": scores["data"], "rank": info.get("data")},
            }
    return {"status": "success", "data": {"year": start_year, "scores": [], "rank": None}}


async def region_company_stats(region_ref: RegionRef, view: str) -> dict:
    """查询区域企业统计数据，按 view 参数选择具体维度。

    Args:
        region_name_or_code: 区域名称或行政区划代码。
        view: 查询维度，可选：分类数量（各类企业标签数量统计）/存量规模（按
            规模的月度存量）/成立年限（存续年限分布）/注册资本（注册资本区间
            分布）/新增数量（月度新增，按规模）/注销吊销数量（月度注销吊销，
            按规模）/Top10行业（企业数量最多的10个行业）/高新技术企业（按年
            认定数量）/科创板上市（按年累计数量）/荣誉榜单（获得的荣誉奖项）。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    if view not in _STAT_ENDPOINTS:
        return {
            "status": "error",
            "error_message": f"view 参数不认识：{view}，可选：{list(_STAT_ENDPOINTS)}",
        }
    region = region_ref
    path, extra_params = _STAT_ENDPOINTS[view]
    params = {"region": region["city_name"], "regionCode": region["region_code"], **extra_params}
    resp = await api_get(path, params)
    return unwrap(resp)


async def region_patent_stats(region_ref: RegionRef) -> dict:
    """查询区域专利数量统计（按年份和专利类型：发明申请/实用新型/外观设计/发明授权）。

    Args:
        region_name_or_code: 区域名称或行政区划代码。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    region = region_ref
    resp = await api_get(
        "/idis_industry/teis/patent/stat",
        {"regionCode": region["region_code"], "aggDt": "ady", "aggTp": "pt"},
    )
    return unwrap(resp)


async def region_fourteenth_five_year_industries(region_ref: RegionRef) -> dict:
    """查询区域"十四五"规划确定的重点产业列表（产业评分、本市企业数量、景气指数）。

    Args:
        region_name_or_code: 区域名称或行政区划代码。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    region = region_ref
    resp = await api_post(
        "/idis_industry/teis/city/planof14thfiveyear",
        {"regorgProvince": region["province_name"], "regionCode": region["region_code"]},
    )
    return unwrap(resp)


async def region_finance_summary(region_ref: RegionRef) -> dict:
    """查询区域企业融资总额和笔数的历年统计（营商环境视角）。

    Args:
        region_name_or_code: 区域名称或行政区划代码。

    Returns:
        status 及 data（每条含 date 年份、amount 融资金额、num 融资笔数）或 error_message。
    """
    region = region_ref
    resp = await api_post(
        "/idis_industry/teis/v2/businessFinance/summary",
        {
            "province": region["province_name"],
            "regionCode": region["region_code"],
            "cycleType": "year",
        },
    )
    return unwrap(resp)


async def region_finance_distribution(
    region_ref: RegionRef,
    start_date: str,
    end_date: str,
    view: str = "类型",
) -> dict:
    """查询区域企业融资分布（按类型或按金额区间）。

    Args:
        region_name_or_code: 区域名称或行政区划代码。
        start_date: 起始日期，格式 yyyy-MM-dd。
        end_date: 截止日期，格式 yyyy-MM-dd。
        view: "类型"（创投/股票/债券/银行借款等类型分布）或"金额区间"
            （按融资金额区间分布），默认"类型"。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    region = region_ref
    path = (
        "/idis_industry/teis/v2/businessFinance/type/finance"
        if view == "类型"
        else "/idis_industry/teis/v2/businessFinance/amount/finance"
    )
    resp = await api_post(
        path,
        {
            "province": region["province_name"],
            "city": region["city_name"],
            "county": region["district_name"],
            "startDate": start_date,
            "endDate": end_date,
            "regionCode": region["region_code"],
            "industryCodeRecursive": False,
        },
    )
    return unwrap(resp)


async def region_finance_trend(
    region_ref: RegionRef,
    start_year: str,
    end_year: str,
    finance_type: int,
) -> dict:
    """查询区域企业融资笔数和金额的历年趋势。

    Args:
        region_name_or_code: 区域名称或行政区划代码。
        start_year: 起始年份，如 "2015"。
        end_year: 截止年份，如 "2026"。
        finance_type: 融资类型，1=创投融资 2=股票融资 3=债券融资 4=应收账款
            5=租赁融资 6=信托融资 7=银行借款 8=其他融资。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    region = region_ref
    resp = await api_post(
        "/idis_industry/teis/v2/businessFinance/trend",
        {
            "province": region["province_name"],
            "city": region["city_name"],
            "county": region["district_name"],
            "start": start_year,
            "end": end_year,
            "regionCode": region["region_code"],
            "financeType": finance_type,
            "industryCodeRecursive": False,
        },
    )
    return unwrap(resp)


async def region_finance_by_subregion(
    region_ref: RegionRef, start_date: str, end_date: str
) -> dict:
    """查询省级区域内各下属城市的企业融资金额和笔数排行榜。

    Args:
        region_name_or_code: 省级区域名称或行政区划代码。
        start_date: 起始日期，格式 yyyy-MM-dd。
        end_date: 截止日期，格式 yyyy-MM-dd。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    region = region_ref
    resp = await api_post(
        "/idis_industry/teis/v2/businessFinance/region/finance",
        {
            "province": region["province_name"],
            "startDate": start_date,
            "endDate": end_date,
            "regionCode": region["region_code"],
            "industryCodeRecursive": False,
        },
    )
    return unwrap(resp)


async def region_finance_top_companies(
    region_ref: RegionRef,
    start_date: str,
    end_date: str,
    top_type: int = 2,
    finance_type: int | None = None,
    month_num: int | None = None,
) -> dict:
    """查询区域内融资金额最大或笔数最多的 TOP 企业榜单。

    Args:
        region_name_or_code: 区域名称或行政区划代码。
        start_date: 起始日期，格式 yyyy-MM-dd。
        end_date: 截止日期，格式 yyyy-MM-dd。
        top_type: 排行类型，2=累计融资（默认），1=单次融资。
        finance_type: 融资类型筛选，1=创投融资 2=股票融资 3=债券融资 4=应收
            账款 5=租赁融资 6=信托融资 7=银行借款 8=其他融资；不筛选不传。
        month_num: 统计近 N 个月，不传则不限时间窗口。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    region = region_ref
    body = {
        "province": region["province_name"],
        "startDate": start_date,
        "endDate": end_date,
        "regionCode": region["region_code"],
        "topType": top_type,
        "industryCodeRecursive": False,
    }
    if finance_type is not None:
        body["financeType"] = finance_type
    if month_num is not None:
        body["monthNum"] = month_num
    resp = await api_post("/idis_industry/teis/v2/businessFinance/top", body)
    return unwrap(resp)


async def region_finance_events(
    region_ref: RegionRef,
    start_date: str,
    end_date: str,
    finance_type: int = 1,
    financier: str = "",
    investor: str = "",
    original_type: list[str] | None = None,
    child_type: list[int] | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """分页查询区域内企业融资明细事件。

    Args:
        region_name_or_code: 区域名称或行政区划代码。
        start_date: 起始日期，格式 yyyy-MM-dd。
        end_date: 截止日期，格式 yyyy-MM-dd。
        finance_type: 融资类型，默认1=创投融资，1-8同 region_finance_trend 的说明。
        financier: 融资方企业名称关键字，不筛选传空字符串。
        investor: 投资方名称关键字，不筛选传空字符串。
        original_type: 融资轮次筛选（如 ["天使轮","A轮"]），不筛选不传。
        child_type: 仅当 finance_type=2（股票融资）时有效，20=A股IPO 21=A股
            增发 22=A股配股 23=港股IPO 24=港股增发 25=新三板发行；不筛选不传。
        page: 页码，从1开始，默认1。
        page_size: 每页条数，默认20。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    region = region_ref
    body = {
        "page": page,
        "pageSize": page_size,
        "province": region["province_name"],
        "startDate": start_date,
        "endDate": end_date,
        "industryCodeRecursive": False,
        "financier": financier,
        "investor": investor,
        "regionCode": region["region_code"],
        "financeType": finance_type,
    }
    if original_type:
        body["originalType"] = original_type
    if child_type:
        body["childType"] = child_type
    resp = await api_post("/idis_industry/teis/v2/businessFinance/query", body)
    return unwrap(resp)


async def region_company_search(
    region_ref: RegionRef,
    company_tab: str = "ALL",
    page_now: int = 1,
    page_size: int = 20,
    order_column: str = "VALUE_SCORE",
    order_type: str = "DESC",
    nature_in: list[str] | None = None,
    ipo_board_in: list[str] | None = None,
    pe_round_in: list[str] | None = None,
    age_in: list[str] | None = None,
    capital_in: list[str] | None = None,
) -> dict:
    """区域企业画像：分页搜索区域内的（在营）企业，支持多维度筛选排序。

    Args:
        region_name_or_code: 区域名称或行政区划代码。
        company_tab: 企业标签筛选，默认 ALL（全部）；可选 a_stock_listed（A股
            上市）/new_over_the_counter（新三板）/bond_issuing_company（发债）/
            high_tech_company（高新技术）/specialized_and_innovative_company
            （专精特新小巨人）/specialized_and_innovative_smes（专精特新中小
            企业）/manufacturing_single_champion（制造业单项冠军）/
            private_equity_vc_company（私募创投）。
        page_now: 页码，默认1。
        page_size: 每页条数，默认20。
        order_column: 排序字段，默认 VALUE_SCORE，可选 INNOVATION_SCORE/
            MARKET_SCORE/REGISTERED_CAPITAL/OPERATING_REVENUE。
        order_type: 排序方向，DESC（默认）或 ASC。
        nature_in: 企业性质筛选，如 ["国有企业","民营企业"]；不筛选不传。
        ipo_board_in: IPO上市板块筛选，如 ["科创板","创业板"]；不筛选不传。
        pe_round_in: 融资轮次筛选，如 ["天使轮","A轮"]；不筛选不传。
        age_in: 企业年龄段筛选，如 ["1年以下","1~3年"]；不筛选不传。
        capital_in: 注册资本区间筛选，如 ["100万以下"]；不筛选不传。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    region = region_ref
    body = {
        "scene": "REGION_COMPANY_PORTRAIT",
        "regionCodeIn": [region["region_code"]],
        "companyTab": company_tab,
        "statusIn": ["ACTIVE"],
        "pageNow": page_now,
        "pageSize": page_size,
        "orderColumn": order_column,
        "orderType": order_type,
    }
    if nature_in:
        body["natureIn"] = nature_in
    if ipo_board_in:
        body["ipoBoardIn"] = ipo_board_in
    if pe_round_in:
        body["peRoundIn"] = pe_round_in
    if age_in:
        body["ageIn"] = age_in
    if capital_in:
        body["capitalIn"] = capital_in
    resp = await api_post("/idis_industry/teis/landing/company/search", body)
    return unwrap(resp)


async def region_park_list(
    region_ref: RegionRef,
    page_now: int = 1,
    page_size: int = 10,
    order: str = "companyCount",
    order_type: str = "desc",
) -> dict:
    """分页查询区域内的产业园区列表。

    Args:
        region_name_or_code: 区域名称或行政区划代码。
        page_now: 页码，默认1。
        page_size: 每页条数，默认10。
        order: 排序字段，默认 companyCount（按企业数量），可选 sonParkCount/
            park_class/park_type/park_area。
        order_type: 排序方向，默认 desc。

    Returns:
        status 及 data（成功时，含 totalCount 和园区列表）或 error_message。
    """
    region = region_ref
    resp = await api_post(
        "/idis_industry/teis/park/parklist",
        {
            "pageNow": page_now,
            "pageSize": page_size,
            "province": region["province_name"],
            "order": order,
            "orderType": order_type,
            "regionCode": region["region_code"],
        },
    )
    return unwrap(resp)


async def region_park_distribution(region_ref: RegionRef) -> dict:
    """查询区域内各下级地区的园区数量分布。"""
    resp = await api_post(
        "/idis_industry/teis/park/regiondisplaypark",
        {
            "province": region_ref["province_name"],
            "city": region_ref["city_name"],
            "district": region_ref["district_name"],
            "regionCode": region_ref["region_code"],
        },
        params={"type": "park"},
    )
    return unwrap(resp)


async def region_park_statistics(
    region_ref: RegionRef,
    park_class: list[str] | None = None,
    park_type: str = "",
) -> dict:
    """查询区域园区总数及按级别、类型划分的统计分布。"""
    resp = await api_post(
        "/idis_industry/teis/park/statisticpark",
        {
            "parkClass": park_class or ["国家级", "省级", "市级", "其他"],
            "parkType": park_type,
            "province": region_ref["province_name"],
            "city": region_ref["city_name"],
            "district": region_ref["district_name"],
            "regionCode": region_ref["region_code"],
        },
        params={"type": "park"},
    )
    return unwrap(resp)


async def region_development_zone_list(
    region_ref: RegionRef,
    park_class: list[str] | None = None,
    park_type_list: list[str] | None = None,
    leading_indsy_list: list[str] | None = None,
    page_now: int = 1,
    page_size: int = 10,
    order: str = "companyCount",
    order_type: str = "desc",
) -> dict:
    """分页查询区域开发区，支持按级别、类型和主导产业筛选。"""
    resp = await api_post(
        "/idis_industry/teis/park/kaifaqulist",
        {
            "pageSize": page_size,
            "pageNow": page_now,
            "parkClass": park_class or [],
            "province": region_ref["province_name"],
            "city": region_ref["city_name"],
            "district": region_ref["district_name"],
            "regionCode": region_ref["region_code"],
            "parkTypeList": park_type_list or [],
            "leadingIndsyList": leading_indsy_list or [],
            "orderType": order_type,
            "order": order,
        },
    )
    return unwrap(resp)


_MACRO_PORTRAIT_ENDPOINTS = {
    "GDP与投资": "/macro/macroZs/regionPortrait/gdpAndInvestment",
    "财政收支": "/macro/macroZs/regionPortrait/finance",
    "政府债务": "/macro/macroZs/regionPortrait/debt",
}


async def region_macro_portrait(region_ref: RegionRef, view: str) -> dict:
    """查询区域宏观经济画像历年时序数据，按 view 参数选择具体维度。

    Args:
        region_name_or_code: 区域名称或行政区划代码。
        view: 查询维度，可选：GDP与投资（GDP及固定资产投资历年数据，含同比
            增速）/财政收支（一般公共预算收入、税收收入等历年数据）/政府债务
            （地方政府债务余额，含一般债、专项债历年数据）。

    Returns:
        status 及 data（data.indicatorLines，每条含 indicatorName/indicatorUnit/
        indicatorPoints 历年数据点）或 error_message。
    """
    if view not in _MACRO_PORTRAIT_ENDPOINTS:
        return {
            "status": "error",
            "error_message": f"view 参数不认识：{view}，可选：{list(_MACRO_PORTRAIT_ENDPOINTS)}",
        }
    region = region_ref
    resp = await api_post(
        _MACRO_PORTRAIT_ENDPOINTS[view],
        {"city": region["city_name"], "regionCode": region["region_code"]},
    )
    return unwrap(resp)


async def region_macro_key_indicators(region_ref: RegionRef) -> dict:
    """查询区域关键宏观经济指标（CPI、PPI、工业增加值等）。

    Args:
        region_name_or_code: 区域名称或行政区划代码。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    region = region_ref
    resp = await api_post(
        "/macro/macroZs/regionEconomic/keyIndicator",
        {"region": region["city_name"], "regionCode": region["region_code"]},
    )
    return unwrap(resp)


async def region_social_financing(region_ref: RegionRef, quarter: int) -> dict:
    """查询区域社会融资规模增量汇总数据（贷款、债券、股票、委托贷款等各分项时序）。

    Args:
        region_name_or_code: 区域名称或行政区划代码。
        quarter: 季度，1~4，表示查询对应季度的数据。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    region = region_ref
    resp = await api_post(
        "/macro/macroZs/socialFinancing/summary",
        {"city": region["city_name"], "quarter": quarter, "regionCode": region["region_code"]},
    )
    return unwrap(resp)
