"""产业信息查询：产业评分、地区/产业节点对比、产业集中度、企业画像、财务
趋势、企业财务明细与排行、专利研报。

原始 34 个 `industryZs`/`unifyIndustry` 接口按"一个真实用户问题对应一个
工具"收敛成下面 7 个，不是照抄 34 个（那样模型没法可靠选）：

- industry_score：综合评估结果 / 指标分析（单一 产业+地区 的评分画像）
- industry_score_comparison：地区对比 / 产业节点对比（评分类横向比较）
- industry_concentration：产业集中度 / 区域对比 / 节点对比（集中度类横向比较，
  跟 industry_score_comparison 名字很像但是完全不同的底层指标，参数形状
  也不一样——集中度这组要 year，评分对比那组要 regionLevel/contrastRange）
- industry_company_portrait：企业性质规模分布 / 类型信息 / 区域分布 /
  节点分布 / 区域类型分布 / 规模趋势（6 个 companyPortrait/* 接口，形状完全
  一致，纯 view 参数收敛）
- industry_financial_trend：产业整体财务历年趋势（上市公司 4 个能力维度 +
  全部企业 4 个水平指数维度）
- industry_company_financial：企业财务明细（分页+排序）与企业排行（预排序
  Top榜）合并成一个工具，用 top_only 切换——这两组接口维度完全对应
  （成长/盈利/运营/偿债/现金流 5×2=10 个原始接口收成 1 个工具）
- industry_innovation：产业专利列表 / 产业研报列表（形状一致，纯 view 收敛）

industryType 是硬约束，不是可以随便留默认值的参数：SELECTED/CSF/NSEI/GB/DE
五套产业分类体系互相独立，industryCode 在不同体系下完全不是一回事，实测
拿一个体系查出来的 code 去另一个体系下用会直接 400（"系统异常"）——
比如 SELECTED 下"新能源汽车"的 code 是"XHICC004002"这种 xh_/XHICC 前缀，
CSF 下是"3705-001"这种横杠分层编号，NSEI 下是"5.3.1.4.2"这种点分层号，
GB/DE 是国标统计局行业代码（C36/I651/DE0301）。GB/DE 对"新能源汽车"这个
产业研究口径的关键词实测直接搜不到任何结果（GB/DE 节点名称是官方统计
口径如"汽车制造业"，不是研究口径的产业名），换成"汽车制造业"当关键词
在 GB 下就能搜到（code=C36）。参数里 reference JSON 给的 industryCode 示例
（如"tree_450"）经实测是失效的旧示例——用它查 evaluateResult 直接
"系统异常"，说明产业树后台已经换过一版编码，千万不能相信 demo 里的
industryCode 示例，必须走 _resolve_industry 实时查。

产业消歧（_resolve_industry）没有走 Milvus——跟 common/milvus_client.py
文档描述一致（那个库目前只有 group_name_collection/park_name_embedding
两张表，没有产业的）。真正的搜索接口是
`/idis_industry/teis/industryZs/unifyIndustry/selectorSearch`，这是本次
开发里最大的一个坑：

1. reference JSON 里这条的 request_params/request_body 全是空的，
   material 原始源文件里也一样是空的——提取阶段就没拿到参数信息。
2. reference JSON 把它标成 method=POST；实测清一色錯——不管 body 传什么
   （包括空 body），POST 一律 400 "method error"。换成 **GET**，参数放
   query string，立刻成功。这是这次任务发现的后端真实坑，不是我猜的。
3. 参数只有两个：industryType + keyword（都是 query string）。返回
   `data.matchList`：该 industryType 树下所有名称包含 keyword 的节点，
   不分页、不带相关度分数、keyword 传空字符串会把整棵树倒出来（SELECTED
   体系下实测 17308 条）——绝对不能允许调用方传空关键词。
4. 每条节点自带 children/childrenTree（完整子树）和 parentList（祖先链），
   子树体积很大（30 个匹配节点能撑到 185KB），_resolve_industry 内部
   只取 code/name/level/rootCode + 用 parentList 拼的面包屑路径，
   children/childrenTree 直接丢弃不往外传。

消歧策略参考 person.py（同样是纯 REST 模糊搜索，没有 Milvus，也没有
person.py 那种 companyAmount 断层置信度信号可用，selectorSearch 压根不
返回任何打分/排序字段）：
- 关键词精确等于某节点 name 且唯一 -> 直接采用；
- 不论是否精确匹配，matchList 只有唯一一条 -> 直接采用；
- 否则 -> 返回候选列表（code/name/path 面包屑）交给上层确认，不瞎猜。
    实测"新能源汽车"在 SELECTED 体系下就有两个不同节点精确同名（分别挂在
    rootCode=XHICC010003 和 rootCode=XHICC004002 两个不同产业根类目下），
    这种同名不唯一是真实存在的情况。

已知不那么理想但暂不深挖的点：
- industry_score（evaluateResult/indicatorAnalysis）实测不传 regionCode
  时 success=true 但 data=null，等于隐性必填，所以这个工具把
  region_name_or_code 设计成必填参数，不像其它工具那样地区可选=全国口径。
- industry_concentration 这组接口 year 是必填（不传直接 success=false），
  且当年（如 2026）数据经常还没跑出来（字段全 null，success 仍是 true），
  处理方式跟 region.py 的 region_score 一样：先试当年，没数据自动退一年。
- score/regionContrast、score/industryContrast 两个接口 reference JSON
  里的 URL 是"/idis_industry/teis//industryZs/..."（teis 后面两个斜杠），
  实测这个双斜杠版本和修正后的单斜杠版本都能正常返回数据（httpx/网关自己
  把重复斜杠归一化了），本文件统一用单斜杠的干净写法。
- contrastRange=IN_CITY 在部分地区实测返回空 itemList（比如直接查上海市
  本身，或查浦东新区）；NATION/IN_PROVINCE 都能正常返回数据。这更像是该
  地区在"市内对比"维度本来就没有可比的同级数据，不是参数用错了，调用方
  自己根据业务需要选 contrast_range。
"""

from datetime import datetime

from entity_mcp.common.address import get_address
from entity_mcp.common.api_client import api_get, api_post, unwrap
from entity_mcp.common.business_protocol import 唯一匹配, 多候选, 未匹配, 调用失败
from entity_mcp.models.entity_refs import IndustryRef, RegionRef

_INDUSTRY_TYPES = ("SELECTED", "CSF", "NSEI", "GB", "DE")

_BASE = "/idis_industry/teis/industryZs/detail"


async def resolve_industry(query: str, industry_type: str) -> dict:
    """识别产业名称或代码，返回产业代码和分类体系。"""
    industry_code, result = await _resolve_industry(query, industry_type)
    if result:
        if result.get("status") == "ambiguous":
            candidates = result.get("candidates", [])
            return 多候选("产业", query, candidates) if candidates else 未匹配("产业", query)
        return 调用失败(result.get("error_message", "产业消歧调用失败。"))
    return 唯一匹配("产业", query, {"industry_code": industry_code, "industry_type": industry_type})


def _has_cjk(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in text)


async def _search_industry(keyword: str, industry_type: str) -> list[dict] | None:
    """直接调 selectorSearch（实测是 GET，不是 reference JSON 标的 POST，
    见模块 docstring）。返回精简候选列表，None 表示接口调用失败。"""
    resp = await api_get(
        "/idis_industry/teis/industryZs/unifyIndustry/selectorSearch",
        {"industryType": industry_type, "keyword": keyword},
    )
    result = unwrap(resp)
    if result["status"] != "success" or not result["data"]:
        return None
    match_list = result["data"].get("matchList") or []
    candidates = []
    for node in match_list:
        parent_names = [p.get("name", "") for p in (node.get("parentList") or []) if p.get("name")]
        name = node.get("name", "")
        path = " > ".join([*parent_names, name]) if parent_names else name
        candidates.append(
            {
                "code": node.get("code"),
                "name": name,
                "level": node.get("level"),
                "root_code": node.get("rootCode"),
                "path": path,
            }
        )
    return candidates


async def _resolve_industry(name_or_code: str, industry_type: str) -> tuple[str | None, dict | None]:
    """消歧落脚点：不含中文字符的直接当 industryCode 用；否则调
    selectorSearch 模糊搜索，精确同名且唯一，或候选只有一条时自动采用。

    Returns:
        (industry_code, None) —— 解析成功；
        (None, ambiguous_dict) —— 解析失败/候选不唯一。
    """
    if industry_type not in _INDUSTRY_TYPES:
        return None, {
            "status": "error",
            "error_message": f"industry_type 不认识：{industry_type}，可选：{list(_INDUSTRY_TYPES)}",
        }
    if not name_or_code:
        return None, {"status": "error", "error_message": "industry_name_or_code 不能为空"}
    if not _has_cjk(name_or_code):
        return name_or_code, None  # 已经是产业代码，直接用

    candidates = await _search_industry(name_or_code, industry_type)
    if candidates is None:
        return None, {
            "status": "error",
            "error_message": f"产业搜索接口调用失败（industryType={industry_type}, keyword={name_or_code}）。",
        }
    if not candidates:
        return None, {
            "status": "ambiguous",
            "message": (
                f"在 industryType={industry_type} 体系下没搜到名为'{name_or_code}'的产业节点。"
                f"注意不同 industryType 是完全独立的分类体系，换个 industry_type 或换个关键词再试。"
            ),
            "candidates": [],
        }

    exact = [c for c in candidates if c["name"] == name_or_code]
    if len(exact) == 1:
        return exact[0]["code"], None
    if len(candidates) == 1:
        return candidates[0]["code"], None

    pool = exact if exact else candidates
    return None, {
        "status": "ambiguous",
        "message": (
            f"'{name_or_code}'在 industryType={industry_type} 体系下匹配到 {len(candidates)} 个产业节点，"
            f"无法自动确定，请从候选里选一个 code 再传进来（传入 industry_name_or_code 参数即可）。"
        ),
        "candidates": pool[:20],
    }


async def _resolve_region_code(region_name_or_code: str) -> tuple[str, dict | None]:
    """地区可选：不传时代表全国口径，直接返回空字符串给 regionCode。"""
    if not region_name_or_code:
        return "", None
    result = get_address(address=region_name_or_code)
    if result["status"] != "success":
        return "", {
            "status": "ambiguous",
            "message": f"没能识别地区'{region_name_or_code}'。",
            "error_detail": result.get("error_message"),
        }
    return result["region_code"], None


_SCORE_ENDPOINTS = {
    "综合评估": f"{_BASE}/score/evaluateResult",
    "指标分析": f"{_BASE}/score/indicatorAnalysis",
}


async def industry_score(
    industry_ref: IndustryRef,
    region_ref: RegionRef,
    view: str = "综合评估",
) -> dict:
    """查询某地区某产业的评分画像，按 view 选择具体维度。

    地区是必填参数——实测不传地区这两个接口 success=true 但 data=null，
    等于隐性必填，跟本模块其它工具"地区可选=全国口径"的规则不一样。

    Args:
        industry_name_or_code: 产业名称（如"人工智能"）或产业代码。传名称
            时按 industry_type 在对应体系下做模糊消歧；消歧结果不唯一时返回
            status=ambiguous 和候选列表，不会瞎猜。
        region_name_or_code: 地区名称（如"上海市"）或行政区划代码，必填。
        industry_type: 产业分类体系，可选 SELECTED（精选产业树，默认）/
            CSF（产业链图谱）/NSEI（战新产业）/GB（国标行业分类）/DE（数字
            经济产业分类）。五套体系互相独立，同一个产业名称在不同体系下
            对应完全不同的 industryCode，不可混用。
        view: 查询维度，可选：综合评估（各维度评级评分及在全国/所在地域/
            所在省份的排名，含优势短板类目）/指标分析（具体指标层面的优势
            劣势项，含指标值和评级）。

    Returns:
        status 及 data（成功时）或 error_message；产业名歧义时返回
        status=ambiguous 和候选列表。
    """
    if view not in _SCORE_ENDPOINTS:
        return {"status": "error", "error_message": f"view 不认识：{view}，可选：{list(_SCORE_ENDPOINTS)}"}
    industry_code = industry_ref["industry_code"]
    industry_type = industry_ref["industry_type"]
    region_code = region_ref["region_code"]
    if not region_code:
        return {
            "status": "error",
            "error_message": "region_name_or_code 必须能解析出具体地区代码，该接口不支持全国口径。",
        }
    resp = await api_get(
        _SCORE_ENDPOINTS[view],
        {"industryType": industry_type, "regionCode": region_code, "industryCode": industry_code},
    )
    return unwrap(resp)


async def industry_score_comparison(
    industry_ref: IndustryRef,
    region_ref: RegionRef | None = None,
    view: str = "地区对比",
    region_level: str = "2",
    contrast_range: str = "NATION",
) -> dict:
    """查询产业综合评分的横向对比（地区间对比，或产业节点间对比）。

    Args:
        industry_name_or_code: 产业名称或产业代码，见 industry_score 的说明。
        region_name_or_code: 地区名称或行政区划代码。view=地区对比时作为
            对比范围的锚点地区（比如查"上海市"的省内对比，就是拿上海市跟
            同省其它城市比）；view=产业节点对比时作为该产业要落地对比的
            地区。不传按全国口径处理。
        industry_type: 产业分类体系，见 industry_score 的说明。
        view: 查询维度，可选：地区对比（同一产业在不同地区间的综合评分及
            细分项——产业规模/优质企业/创新能力/融资能力/产业效益/成长
            能力——对比排名）/产业节点对比（同一地区下，该产业与其同级/
            子级产业节点的综合评分对比）。
        region_level: 参与对比的地区行政级别，1=省级 2=地市级（默认）
            3=区县级。
        contrast_range: 地区对比的范围，仅 view=地区对比 时生效，可选
            NATION（全国范围，默认）/IN_PROVINCE（省内）/IN_CITY（市内）。
            实测部分地区传 IN_CITY 会返回空列表（该地区在市内维度本来就
            没有可比的同级数据），不是参数错误，可以换 NATION 再试。
            view=产业节点对比时固定用产业树内部对比，不受此参数影响。

    Returns:
        status 及 data（data.itemList 为对比结果列表）或 error_message。
    """
    industry_code = industry_ref["industry_code"]
    industry_type = industry_ref["industry_type"]
    region_code = (region_ref or {}).get("region_code", "")

    if view == "地区对比":
        path = f"{_BASE}/score/regionContrast"
        params = {
            "industryType": industry_type,
            "regionCode": region_code,
            "industryCode": industry_code,
            "regionLevel": region_level,
            "contrastType": "CITY_CONTRAST",
            "contrastRange": contrast_range,
        }
    elif view == "产业节点对比":
        path = f"{_BASE}/score/industryContrast"
        params = {
            "industryType": industry_type,
            "regionCode": region_code,
            "industryCode": industry_code,
            "regionLevel": region_level,
            "contrastRange": "TREE",
        }
    else:
        return {
            "status": "error",
            "error_message": f"view 不认识：{view}，可选：['地区对比', '产业节点对比']",
        }
    resp = await api_get(path, params)
    return unwrap(resp)


_CONCENTRATION_ENDPOINTS = {
    "产业集中度": f"{_BASE}/concentration/intro",
    "区域对比": f"{_BASE}/concentration/regionContrast",
    "节点对比": f"{_BASE}/concentration/industryContrast",
}


async def industry_concentration(
    industry_ref: IndustryRef,
    region_ref: RegionRef | None = None,
    view: str = "产业集中度",
    year: str = "",
) -> dict:
    """查询产业集中度相关指标（跟 industry_score_comparison 是完全不同的
    指标体系：这组是产值集中度 CR 类指标，不是综合评分）。

    Args:
        industry_name_or_code: 产业名称或产业代码，见 industry_score 的说明。
        region_name_or_code: 地区名称或行政区划代码，不传按全国口径处理。
        industry_type: 产业分类体系，见 industry_score 的说明。
        view: 查询维度，可选：产业集中度（该地区该产业的集中度/空间集中度
            两个指标值）/区域对比（该产业在各地区间的产值规模、集中度对比
            列表）/节点对比（该地区下，该产业各子节点间的产值规模、集中度
            对比列表）。
        year: 查询年份，不传默认当前年份。实测集中度数据有滞后（当年常常
            还没跑出来），当年查不到时自动往前退一年再试一次。

    Returns:
        status 及 data（成功时，含 year 标注实际取到数据的年份）或 error_message。
    """
    if view not in _CONCENTRATION_ENDPOINTS:
        return {
            "status": "error",
            "error_message": f"view 不认识：{view}，可选：{list(_CONCENTRATION_ENDPOINTS)}",
        }
    industry_code = industry_ref["industry_code"]
    industry_type = industry_ref["industry_type"]
    region_code = (region_ref or {}).get("region_code", "")

    path = _CONCENTRATION_ENDPOINTS[view]
    start_year = int(year) if year else datetime.now().year
    last_result = None
    for y in (start_year, start_year - 1):
        resp = await api_get(
            path,
            {
                "industryType": industry_type,
                "regionCode": region_code,
                "industryCode": industry_code,
                "year": str(y),
            },
        )
        result = unwrap(resp)
        if result["status"] != "success":
            return result
        data = result["data"] or {}
        meaningful = {k: v for k, v in data.items() if k not in ("industryType", "industryCode", "regionCode", "year")}
        has_data = any(v not in (None, [], {}, "") for v in meaningful.values())
        last_result = result
        if has_data:
            return result
    return last_result or {"status": "success", "data": {"year": start_year}}


_PORTRAIT_ENDPOINTS = {
    "企业性质规模分布": f"{_BASE}/companyPortrait/pieChartBundle",
    "企业类型信息": f"{_BASE}/companyPortrait/typeDistribution",
    "企业区域分布": f"{_BASE}/companyPortrait/regionDistribution",
    "产业节点分布": f"{_BASE}/companyPortrait/industryDistribution",
    "区域类型分布": f"{_BASE}/companyPortrait/industryRegionDistribution",
    "企业规模趋势": f"{_BASE}/companyPortrait/scaleChartBundle",
}


async def industry_company_portrait(
    industry_ref: IndustryRef,
    region_ref: RegionRef | None = None,
    view: str = "企业性质规模分布",
) -> dict:
    """查询产业内企业画像统计（性质/年龄/资本/类型/区域分布/规模趋势等），
    按 view 参数选择具体维度。

    Args:
        industry_name_or_code: 产业名称或产业代码，见 industry_score 的说明。
        region_name_or_code: 地区名称或行政区划代码，不传按全国口径处理。
        industry_type: 产业分类体系，见 industry_score 的说明。
        view: 查询维度，可选：企业性质规模分布（企业性质/经营年限/注册资本
            三个维度的饼图数据）/企业类型信息（按企业标签类型，如高新技术、
            专精特新等，统计数量）/企业区域分布（按地区统计企业数量、集中
            度、评分）/产业节点分布（按产业子节点统计企业数量）/区域类型
            分布（产业节点与区域的交叉分布）/企业规模趋势（历年企业规模
            存量趋势）。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    if view not in _PORTRAIT_ENDPOINTS:
        return {
            "status": "error",
            "error_message": f"view 不认识：{view}，可选：{list(_PORTRAIT_ENDPOINTS)}",
        }
    industry_code = industry_ref["industry_code"]
    industry_type = industry_ref["industry_type"]
    region_code = (region_ref or {}).get("region_code", "")
    resp = await api_get(
        _PORTRAIT_ENDPOINTS[view],
        {"industryType": industry_type, "regionCode": region_code, "industryCode": industry_code},
    )
    return unwrap(resp)


# view -> (endpoint path, 是否支持 tabName)
_TREND_ENDPOINTS = {
    "上市公司-成长能力": (f"{_BASE}/financialAnalyze/ipoCompanyGrowthAbilityTrend", "营业总收入"),
    "上市公司-盈利能力": (f"{_BASE}/financialAnalyze/ipoCompanyProfitAbilityTrend", "利润率"),
    "上市公司-运营能力": (f"{_BASE}/financialAnalyze/ipoCompanyOperationAbilityTrend", "营业周期"),
    "上市公司-偿债能力": (f"{_BASE}/financialAnalyze/ipoCompanyDebtAbilityTrend", "资产负债率"),
    "全部企业-营收水平": (f"{_BASE}/financialAnalyze/allCompanyOperationTrend", None),
    "全部企业-资产规模": (f"{_BASE}/financialAnalyze/allCompanyAssetTrend", None),
    "全部企业-销售利润": (f"{_BASE}/financialAnalyze/allCompanyProfitTrend", None),
    "全部企业-所有者权益": (f"{_BASE}/financialAnalyze/allCompanyEquityTrend", None),
}


async def industry_financial_trend(
    industry_ref: IndustryRef,
    region_ref: RegionRef | None = None,
    view: str = "全部企业-营收水平",
    tab_name: str = "",
) -> dict:
    """查询产业整体财务历年趋势，按 view 参数选择具体维度。

    Args:
        industry_name_or_code: 产业名称或产业代码，见 industry_score 的说明。
        region_name_or_code: 地区名称或行政区划代码，不传按全国口径处理。
        industry_type: 产业分类体系，见 industry_score 的说明。
        view: 查询维度，可选：上市公司-成长能力（营业总收入/总资产/每股
            收益趋势）/上市公司-盈利能力（利润率/ROE/ROA趋势）/上市公司-
            运营能力（营业周期/资产周转率趋势）/上市公司-偿债能力（资产
            负债率/流动比率/速动比率趋势）/全部企业-营收水平（营收水平
            指数趋势）/全部企业-资产规模（资产规模指数趋势）/全部企业-
            销售利润（销售利润水平趋势）/全部企业-所有者权益（所有者权益
            水平指数趋势），前4个是仅上市公司口径，后4个是产业全部企业口径。
        tab_name: 仅"上市公司-*"这4个view有效，指定要看哪个具体指标的
            历年趋势（如成长能力下还可以传"总资产""每股收益"等），不传用
            该view的默认指标；"全部企业-*"这4个view不支持这个参数。

    Returns:
        status 及 data（成功时，data.timeItemList 为历年数据点）或 error_message。
    """
    if view not in _TREND_ENDPOINTS:
        return {"status": "error", "error_message": f"view 不认识：{view}，可选：{list(_TREND_ENDPOINTS)}"}
    industry_code = industry_ref["industry_code"]
    industry_type = industry_ref["industry_type"]
    region_code = (region_ref or {}).get("region_code", "")
    path, default_tab = _TREND_ENDPOINTS[view]
    params = {"industryType": industry_type, "regionCode": region_code, "industryCode": industry_code}
    if default_tab is not None:
        params["tabName"] = tab_name or default_tab
    resp = await api_get(path, params)
    return unwrap(resp)


# view -> (企业财务明细接口名, 企业排行接口名, 默认排序字段)
_FINANCIAL_ENDPOINTS = {
    "成长能力": ("ipoCompanyGrowthAbility", "ipoCompanyGrowthAbilityTop", "operatingRevenue"),
    "盈利能力": ("ipoCompanyProfitAbility", "ipoCompanyProfitAbilityTop", "grossIncomeRatio"),
    "运营能力": ("ipoCompanyOperationAbility", "ipoCompanyOperationAbilityTop", "operCycle"),
    "偿债能力": ("ipoCompanyDebtAbility", "ipoCompanyDebtAbilityTop", "debtAssetsRatio"),
    "现金流量": ("ipoCompanyCashFlow", "ipoCompanyCashFlowTop", "cashRateOfSales"),
}


async def industry_company_financial(
    industry_ref: IndustryRef,
    region_ref: RegionRef | None = None,
    view: str = "成长能力",
    year: str = "",
    quarter: str = "",
    top_only: bool = False,
    page_now: int = 1,
    page_size: int = 20,
    order_column: str = "",
    order_type: str = "desc",
) -> dict:
    """查询产业内上市公司的财务明细列表或排行榜，按 view 选择财务能力维度。

    企业财务明细（可翻页/自定义排序）和企业排行（预排序 Top 榜单）两组
    原本是不同的原始接口，这里用 top_only 合并成一个工具——业务上是同一个
    问题（"这个产业里谁财务表现最好"），只是想要完整分页列表还是想要现成
    的 Top 榜单的区别。

    Args:
        industry_name_or_code: 产业名称或产业代码，见 industry_score 的说明。
        region_name_or_code: 地区名称或行政区划代码，不传按全国口径处理。
        industry_type: 产业分类体系，见 industry_score 的说明。
        view: 财务能力维度，可选：成长能力（营业收入/总资产/利润总额/每股
            收益及其同比）/盈利能力（毛利率/净利率/净资产收益率/总资产
            报酬率）/运营能力（营业周期/总资产周转率/存货周转率/应收账款
            周转率/固定资产周转率）/偿债能力（资产负债率/流动比率/速动
            比率/现金比率）/现金流量（销售现金比率及相关现金流指标）。
        year: 财报年份，如"2024"，不传则由接口按默认最新年份处理。
        quarter: 财报季度，如"Q1"/"Q2"/"Q3"/"Q4"，不传则由接口按默认最新
            季度处理。
        top_only: False（默认）返回分页明细列表，支持 order_column 自定义
            排序；True 时改为返回该维度的预排序 Top 榜单（接口本身不分页、
            不支持自定义排序，忽略 page_now/page_size/order_column/order_type）。
        page_now: 页码，默认1，仅 top_only=False 时有效。
        page_size: 每页条数，默认20，仅 top_only=False 时有效。
        order_column: 排序字段，不传用该 view 的默认字段（如成长能力默认按
            operatingRevenue 营业收入排序），仅 top_only=False 时有效。
        order_type: 排序方向，默认 desc，仅 top_only=False 时有效。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    if view not in _FINANCIAL_ENDPOINTS:
        return {
            "status": "error",
            "error_message": f"view 不认识：{view}，可选：{list(_FINANCIAL_ENDPOINTS)}",
        }
    industry_code = industry_ref["industry_code"]
    industry_type = industry_ref["industry_type"]
    region_code = (region_ref or {}).get("region_code", "")

    detail_suffix, top_suffix, default_order_column = _FINANCIAL_ENDPOINTS[view]
    base_params = {
        "industryType": industry_type,
        "regionCode": region_code,
        "industryCode": industry_code,
        "year": year,
        "quarter": quarter,
    }
    if top_only:
        path = f"{_BASE}/financialAnalyze/{top_suffix}"
        params = base_params
    else:
        path = f"{_BASE}/financialAnalyze/{detail_suffix}"
        params = {
            **base_params,
            "pageNow": page_now,
            "pageSize": page_size,
            "orderColumn": order_column or default_order_column,
            "orderType": order_type,
        }
    resp = await api_get(path, params)
    return unwrap(resp)


# view -> (接口路径, 默认排序字段)
_INNOVATION_ENDPOINTS = {
    "专利": (f"{_BASE}/industryCreative/patent/find", "applicationDate"),
    "研报": (f"{_BASE}/researchReport/findPage", "registerDate"),
}


async def industry_innovation(
    industry_ref: IndustryRef,
    region_ref: RegionRef | None = None,
    view: str = "专利",
    keyword: str = "",
    page_now: int = 1,
    page_size: int = 10,
    order_type: str = "desc",
) -> dict:
    """分页查询产业相关的专利列表或研究报告列表，按 view 参数选择。

    Args:
        industry_name_or_code: 产业名称或产业代码，见 industry_score 的说明。
        region_name_or_code: 地区名称或行政区划代码，不传按全国口径处理。
        industry_type: 产业分类体系，见 industry_score 的说明。
        view: 查询维度，可选：专利（该产业相关专利，含申请人/申请日期/
            价值度评分等）/研报（该产业相关行业研究报告，含机构/分析师/
            发布日期/PDF链接等）。
        keyword: 在专利名称/研报标题内再次关键字过滤，不筛选传空字符串。
        page_now: 页码，默认1。
        page_size: 每页条数，默认10。
        order_type: 排序方向，默认 desc（降序）。

    Returns:
        status 及 data（成功时，data.totalCount 总数、data.list 当页数据）或 error_message。
    """
    if view not in _INNOVATION_ENDPOINTS:
        return {
            "status": "error",
            "error_message": f"view 不认识：{view}，可选：{list(_INNOVATION_ENDPOINTS)}",
        }
    industry_code = industry_ref["industry_code"]
    industry_type = industry_ref["industry_type"]
    region_code = (region_ref or {}).get("region_code", "")

    path, default_order_column = _INNOVATION_ENDPOINTS[view]
    body = {
        "industryType": industry_type,
        "regionCode": region_code,
        "industryCode": industry_code,
        "pageNow": page_now,
        "pageSize": page_size,
        "keyword": keyword,
        "orderColumn": default_order_column,
        "orderType": order_type,
    }
    resp = await api_post(path, body)
    return unwrap(resp)
