"""企业（单体企业）信息查询：司法/经营风险、工商登记信息、知识产权、图谱、
评分、舆情公告、资质认证、财务、经营明细、高级搜索、融资。

跟 industry.py 不是一回事：industry.py 是产业级聚合统计，这里是单个企业的
详情查询（对标 group.py 之于集团、person.py 之于人物）。

## 关于消歧 / name_or_id：这批接口根本没有消歧机制，也不需要
本文件所有工具的第一个参数都叫 `company_name`，不是其它文件常见的
`name_or_id`——这是本次调研最重要的结论，专门说明一下：

1. 105 个原始接口里，绝大多数请求参数字段就叫 `name`/`companyName`，
   类型是普通字符串，语义就是"企业名称"，不是一个可以传 ID 的字段。
2. 实测验证过 companyId 不能替代 name 用：`/cmp/detail/basic` 传
   `name=国家电网有限公司`（工商全称）能查到数据，返回体里带出
   `companyId=f61c1329809db546a05bf17008b41f26`；反过来拿这个
   companyId 当 name 传进去，接口返回 success=true 但 data=null——
   说明这批接口不认 companyId，只认名称字符串。
3. 实测验证过简称也不行：传"宁德时代"（简称）给 `/cmp/detail/basic`，
   success=true 但 data=null；必须传"宁德时代新能源科技股份有限公司"
   这样的工商登记全称才能查到数据。也就是说这批接口内部没有做任何模糊
   匹配/歧义消解。
4. `common/milvus_client.py` 里的 Milvus 库只有 `group_name_collection`
   （集团）和 `park_name_embedding`（园区）两张表，压根没有企业名称的
   向量库，没法照抄 group.py/park.py 那套消歧。person.py 的模糊搜索
   （/cmp/person/list）也是人物专属接口，查不了企业。
5. 结论：**这个领域目前没有可用的模糊名称消歧机制**，也没有 companyId
   查询通路。调用方必须直接提供准确的企业工商登记全称。如果只有简称或
   模糊名字，建议先从 group.group_companies 的成员列表（含 companyId 和
   企业全称两个字段）或其它渠道换取企业全称，再调用本文件的工具——
   本文件不会、也没法凭空编一个消歧器出来。

## 已知的后端坑（每条都是实测验证过的真实现象，不是猜测）

**方法与文档不符（这是本项目这次会话反复出现的坑，这里又踩了好几个）：**
- `/idis_industry/teis/landing/company/pro/advanceSearch`：reference JSON
  标 method=GET 且 request_params 是空的（提取失败）。实测 GET 一律
  "method error"；真实方法是 **POST**，真实的关键字段是 **`keyword`**
  （不是 `keyText`，那是另一个高级搜索接口 `company/search/go` 的参数名）。
  拿"宁德时代"当 keyword 测：返回 189 条，第一条就是"宁德时代新能源
  科技股份有限公司"，能对上；换成 companyName/name/keyName/searchKey/key
  当字段名，返回的都是 141894621 条（约等于整库无筛选），说明这几个候选
  字段名都不对，只有 keyword 是真的在生效筛选。
- `/cmp/detail/productInfo`、`/cmp/detailOperation/bondComCredit`、
  `/cmp/detailOperation/importExportCredit`、`/cmp/detailOperation/taxCredit`、
  `/cmp/detailOperation/recruit`：reference JSON 全标 method=POST，实测
  POST（不管是纯 query 参数还是纯 body）一律"method error"，换成
  **GET + query 参数**才成功。同一个 company_business_detail 分组里的
  customer/supplier/tenderee/winTenderer 这 4 个，文档同样标 POST，
  实测确实是 POST（+ query 参数）——同一个分组内部方法并不统一，
  必须逐个实测，不能按文档或按"看起来像同类接口"统一处理。
- `/idis_industry/teis/businessFinance/atlas`（融资图谱）：reference JSON
  标参数名是 `name`，实测传 `name` 直接"系统异常"；换成 `companyName`
  才成功。

**融资相关接口的三个成群坑，这次专门做了实测验证：**

1. `/finance/{creditLine,holder,journey,outInvestment,query}`（不带
   `idis_industry` 前缀的"裸"路径）vs `/idis_industry/teis/v2/
   businessFinance/finance/{creditLine,holder,journey,outInvestment}` +
   `/idis_industry/teis/v2/businessFinance/query`：reference JSON 里两组
   参数形状/输出字段几乎一模一样（同名字段），像是新旧两版 API 共存。
   实测结论：**裸路径版本已经不通**——POST 一律 405 Method Not Allowed，
   换 GET 拿到的不是 JSON（空响应体，解析直接报错），说明这几条裸路径
   在当前网关下根本没有路由，是废弃的旧版本。v2 版本（`/idis_industry/
   teis/v2/businessFinance/finance/*`）全部实测可正常调用，本文件只接
   v2 版本，不实现裸路径版本。
2. `/idis_industry/teis/v2/businessFinance/{amount,type}/finance`、
   `/idis_industry/teis/v2/businessFinance/{region/finance,trend,top}`、
   `/idis_industry/teis/patent/stat` 这 6 条虽然出现在这次给的 105 个
   "企业级"接口清单里，但实测它们的请求体/请求参数只认 `regionCode`/
   `industryType`/`industryCode`，压根没有 `companyName`/`name` 字段——
   传 regionCode（不传任何企业名）就能正常出数据。而且这 6 条路径
   **跟 region.py 里已经实现的工具用的是完全相同的 URL**：
     - amount/finance、type/finance ← region.region_finance_distribution
     - region/finance ← region.region_finance_by_subregion
     - trend ← region.region_finance_trend
     - top ← region.region_finance_top_companies
     - patent/stat ← region.region_patent_stats
   结论：这 6 条是提取阶段把同一批接口重复归到了"企业"和"区域"两个
   分类里，实际是区域/产业级接口，不是企业级的，本文件不重复实现，
   避免和 region.py 撞车。
3. `/idis_industry/teis/v2/businessFinance/finance/creditLine`（授信额度）：
   参数、路径都没问题（跟 holder/outInvestment 是同一组，参数形状完全
   一致），但实测对小米科技、百度、碧桂园、宁德时代等多家真实大企业
   （含理论上明确应该有授信记录的地产公司）全部返回
   `success=true, data=null`，而同一批公司查 holder/outInvestment/query
   都能正常出数据。这更像是这个环境里这张表本身数据源覆盖率低/是空的，
   不像是参数传错——因为参数形状跟能正常出数据的兄弟接口完全一致。
   本文件按接口契约正常实现，但把这个"目前测到的都是空"的现象记在这里，
   不代表接口写错了。

**知识产权分组内部并非同一形状（任务里提前预判到了，这次验证坐实）：**
`/cmp/detailIntellectual/*`（patentTrend/patentTypeDistribution/
softwareCopyright/workCopyright/trademark/websiteRecord/patent/findPage）
这 7 条确实是"企业名称 -> 该企业的专利/著作权/商标"，本文件 company_ip
覆盖了这 7 条。但同一个候选分组里另外 3 条
`/cmp/industryDetail/intellectual/{copyright,softwareCopyright,
trademark}/find` 实测请求体参数是 `industryType`/`regionCode`/
`industryCode`/`keyword`/分页排序，**完全没有企业名称字段**——传
industryCode="C39"（不传任何企业名）就能正常返回数据，证明这 3 条其实
是"某产业下的专利/著作权/商标列表"，是产业级接口，不是企业级的。
这 3 条跟 industry.py 的 `industry_innovation`（专利/研报）是同一类
（industryCode 维度），概念上更应该并入 industry.py，但本次任务不允许
改动已有的 5 个实体文件，所以这 3 条本次不实现，也不会硬凑进 company_ip
（不同参数形状硬套 name_or_id 会直接查不到东西）。

**企业评分（/cmp/company-asy/*）疑似数据源问题：**
main/detail/main-tech/detail-tech 这 4 条实测对贵州茅台、宁德时代、美的
集团都能正常返回结构（detail/detail-tech 的 groups 列表里 tp 分类字段
如 scale/growth/innovate/qualification 都是真实有值的，forbidden 字段
也是 false），但每一条的 scoreVal/scoreLevel/dt/rankRegionName/
rankRegionVal/rankIndustryName/rankIndustryVal/rankAllVal 这些真正的
评分/排名字段全部是 null——说明接口本身的结构/分类逻辑是通的，但具体
评分数值这批数据在当前环境里没有populate，不是参数错误。

**主营构成/财务报表这组（/cmp/aiplugin/*）疑似数据源问题：**
financeindex/balancesheet/profit/cashflow/project/industry/product/area
这 8 条，实测对贵州茅台（600519.SH）、宁德时代（300750.SZ）、比亚迪
（002594.SZ）、美的集团（000333.SZ）——四家确定无疑的 A 股上市公司——
全部返回 `success=true, msg="非A股上市企业无此数据", data=[]`（financeindex/
balancesheet 试了不传 date 和传 3 个不同 date 都一样）。这个提示信息本身
明显不准确（这几家都是真实的 A 股上市公司），更像是这批数据源在当前
环境下是空的，不是判断逻辑传参错误。同一个分组里的
`/cmp/detailOperation/mainIndicator`（企业财务概览）对同一批公司实测
正常返回数据——说明不是"这个环境查不到任何财务数据"，只是 aiplugin 这
8 条具体的数据源有问题。本文件按契约照常实现这 8 条，但这个现象值得
在真正用起来之前留意。

## 高级搜索：两个接口经实测证明不是重复的，形状也确实不同
`/idis_industry/teis/company/search/go`（关键词="宁德时代"，实测
171 条结果，首条即宁德时代本身）支持一整套结构化筛选条件（产业代码/
产业类型/地区/企业类型/性质/规模/状态/成立年限/员工数/参保人数/注册
资本/PE轮次/IPO轮次/IPO板块/发债），返回的是原始字段风格的公司列表
（regcapcur_name/esdate/patent_count/relevanceProductInfos 这类字段）。
`/idis_industry/teis/landing/company/pro/advanceSearch`（关键词参数是
`keyword`，见上面方法坑）只做关键词全文检索，不支持这些结构化筛选，
但返回的是精修过的"企业卡片"结构（basicInfo/scoreInfo/tagInfo/
monitorInfo/favoriteInfo 嵌套对象），明显是两套不同的搜索底层
（很可能一个是产业标签匹配引擎，一个是通用企业目录全文检索）。
两者都实现，用 view 区分，不强行合并成一个。
"""

from functools import wraps

from common.api_client import api_get, api_post, unwrap
from common.business_protocol import 唯一匹配, 多候选, 未匹配, 调用失败


def _企业查询工具(tool):
    """将后端的“成功但 data=null”统一解释为企业主体未匹配。"""
    @wraps(tool)
    async def wrapper(company_name: str, *args, **kwargs):
        result = await tool(company_name, *args, **kwargs)
        if result.get("status") == "success" and result.get("data") is None:
            return {
                "状态码": "实体未匹配",
                "摘要": "未匹配到企业主体，请调用 resolve_company 获取候选。",
                "原始输入": company_name,
            }
        return result
    return wrapper


async def resolve_company(query: str) -> dict:
    """按企业简称、品牌或名称搜索候选；用户确认后再调用企业查询工具。"""
    result = await company_advanced_search(view="关键词", keyword=query)
    if result.get("status") != "success":
        return 调用失败(result.get("error_message", "企业消歧调用失败。"))
    data = result.get("data")
    if not data:
        return 未匹配("企业", query)
    if isinstance(data, list):
        candidates = data
    elif isinstance(data, dict):
        candidates = (
            data.get("list") or data.get("records") or data.get("datas")
            or data.get("data") or []
        )
    else:
        candidates = []
    if not candidates:
        return 未匹配("企业", query)
    exact = [item for item in candidates if item.get("companyName") == query or item.get("name") == query]
    if len(exact) == 1:
        company_name = exact[0].get("companyName") or exact[0].get("name")
        return 唯一匹配("企业", query, {"company_name": company_name})
    return 多候选("企业", query, candidates[:20])

# ---------------------------------------------------------------------------
# 1. 司法风险
# ---------------------------------------------------------------------------

_JUDICIAL_RISK_ENDPOINTS = {
    "失信被执行": "/cmp/judicialrisk/shixin",
    "被执行人": "/cmp/judicialrisk/zhixing",
    "限制高消费": "/cmp/judicialrisk/limithighconsume",
    "终本案件": "/cmp/judicialrisk/finalcase",
    "立案信息": "/cmp/judicialrisk/register",
    "法院公告": "/cmp/judicialrisk/court",
    "开庭公告": "/cmp/judicialrisk/courtnotice",
    "裁判文书": "/cmp/judicialrisk/judgement",
    "司法拍卖": "/cmp/judicialrisk/auction",
    "股权冻结": "/cmp/judicialrisk/freeze",
    "破产重整": "/cmp/judicialrisk/reorg",
}


@_企业查询工具
async def company_judicial_risk(
    company_name: str,
    risk_type: str,
    lian_date_list: list[str] | None = None,
    page_now: int = 1,
    page_size: int = 20,
    order_column: str = "",
    order_type: str = "desc",
) -> dict:
    """查询企业司法风险信息，按 risk_type 参数选择具体类型。

    Args:
        company_name: 企业工商登记全称（必须准确，不支持模糊匹配，见模块
            docstring）。
        risk_type: 风险类型，可选：失信被执行/被执行人/限制高消费/终本
            案件/立案信息/法院公告/开庭公告/裁判文书/司法拍卖/股权冻结/
            破产重整。
        lian_date_list: 立案年份筛选，如 ["2023","2024"]；不筛选不传。
        page_now: 页码，默认 1。
        page_size: 每页条数，默认 20。
        order_column: 排序字段，不传用接口默认排序。
        order_type: 排序方向，默认 desc。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    path = _JUDICIAL_RISK_ENDPOINTS.get(risk_type)
    if not path:
        return {
            "status": "error",
            "error_message": f"risk_type 不认识：{risk_type}，可选：{list(_JUDICIAL_RISK_ENDPOINTS)}",
        }
    body = {
        "name": company_name,
        "pageNow": page_now,
        "pageSize": page_size,
        "orderColumn": order_column,
        "orderType": order_type,
    }
    if lian_date_list:
        body["lianDateList"] = lian_date_list
    resp = await api_post(path, body)
    return unwrap(resp)


# ---------------------------------------------------------------------------
# 2. 经营风险
# ---------------------------------------------------------------------------

# risk_type -> (path, name放在body里(True)/query里(False), 起始日期字段,
#               截止日期字段, 移出起始日期字段, 移出截止日期字段)
_OPERATING_RISK_ENDPOINTS = {
    "行政处罚": ("/cmp/risk/penalty/list", False, "startDate", "endDate", None, None),
    "经营异常": ("/cmp/risk/operateException/list", False, "addStartDate", "addEndDate", "removeStartDate", "removeEndDate"),
    "严重违法": ("/cmp/risk/seriousViolation/list", False, "startDate", "endDate", None, None),
    "欠税公告": ("/cmp/risk/taxOwe/list", False, "startDate", "endDate", None, None),
    "税收违法": ("/cmp/risk/taxIllegal/list", False, "startDate", "endDate", None, None),
    "环保处罚": ("/cmp/risk/envPunishment/list", False, "startDate", "endDate", None, None),
    "债券违约": ("/cmp/risk/bondDefault", True, "startDate", "endDate", None, None),
    "股权出质": ("/cmp/risk/stockSledge/list", False, "startDate", "endDate", None, None),
    "动产抵押": ("/cmp/risk/movePledge/list", False, "addStartDate", "addEndDate", None, None),
    "土地抵押": ("/cmp/risk/landMortgage/list", False, "addStartDate", "addEndDate", "removeStartDate", "removeEndDate"),
    "简易注销": ("/cmp/risk/simpleCancellation/list", False, "startDate", "endDate", None, None),
    "清算信息": ("/cmp/risk/liquidation/list", False, None, None, None, None),
}


@_企业查询工具
async def company_operating_risk(
    company_name: str,
    risk_type: str,
    start_date: str = "",
    end_date: str = "",
    remove_start_date: str = "",
    remove_end_date: str = "",
) -> dict:
    """查询企业经营风险信息，按 risk_type 参数选择具体类型。

    Args:
        company_name: 企业工商登记全称，见模块 docstring。
        risk_type: 风险类型，可选：行政处罚/经营异常/严重违法/欠税公告/
            税收违法/环保处罚/债券违约/股权出质/动产抵押/土地抵押/简易
            注销/清算信息。
        start_date: 起始日期筛选，格式 yyyy-MM-dd；对经营异常/动产抵押/
            土地抵押这几个语义上是"列入/抵押登记起始日期"，对其它是
            "发布/处罚日期"，不筛选传空字符串。清算信息不支持日期筛选。
        end_date: 截止日期筛选，含义对应 start_date。
        remove_start_date: 移出/抵押结束起始日期，仅经营异常、土地抵押
            两个 risk_type 支持，不筛选传空字符串。
        remove_end_date: 移出/抵押结束截止日期，含义对应 remove_start_date。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    cfg = _OPERATING_RISK_ENDPOINTS.get(risk_type)
    if cfg is None:
        return {
            "status": "error",
            "error_message": f"risk_type 不认识：{risk_type}，可选：{list(_OPERATING_RISK_ENDPOINTS)}",
        }
    path, name_in_body, start_field, end_field, remove_start_field, remove_end_field = cfg
    body: dict = {}
    if start_field and start_date:
        body[start_field] = start_date
    if end_field and end_date:
        body[end_field] = end_date
    if remove_start_field and remove_start_date:
        body[remove_start_field] = remove_start_date
    if remove_end_field and remove_end_date:
        body[remove_end_field] = remove_end_date

    if name_in_body:
        # 债券违约（bondDefault）：companyName 是 JSON body 字段，不是 query 参数。
        body["companyName"] = company_name
        resp = await api_post(path, body)
    else:
        resp = await api_post(path, body, params={"name": company_name})
    return unwrap(resp)


# ---------------------------------------------------------------------------
# 3. 工商登记信息
# ---------------------------------------------------------------------------

@_企业查询工具
async def company_registration_info(
    company_name: str,
    view: str = "工商信息",
    public_date: str = "",
    position: str = "",
    office_name: str = "",
    branch_status: str = "",
    change_type: str = "",
    page_now: int = 1,
    page_size: int = 20,
    order_column: str = "",
    order_type: str = "desc",
) -> dict:
    """查询企业工商登记相关信息，按 view 参数选择具体维度。

    这 12 个原始接口的调用方式（企业名放 query 还是 body、要不要分页）
    彼此并不一致，已经在内部逐个适配好，调用方只需要传 view。

    Args:
        company_name: 企业工商登记全称，见模块 docstring。
        view: 查询维度，可选：标签资质信息（企业标签/经营范围/简介/规模）/
            工商信息（统一社会信用代码/注册资本/法人/经营范围等）/上市
            股东信息（上市公告口径股东名单）/工商股东信息（工商登记口径
            股东名单）/上市主要人员（上市公告口径高管）/工商主要人员
            （工商登记口径高管）/董监高投资任职（该企业高管在其它企业的
            任职情况）/分支机构/工商变更（历史工商变更记录）/实际控制人/
            受益所有人/持股企业（该企业对外持股的企业列表）。
        public_date: 变更/报告截止日期筛选，仅"上市股东信息""上市主要
            人员""工商主要人员"支持，格式 yyyy-MM-dd，不筛选传空字符串。
        position: 职务筛选，仅"上市主要人员""工商主要人员"支持（如
            "法定代表人"），不筛选传空字符串。
        office_name: 姓名筛选，仅"董监高投资任职"支持，不筛选传空字符串。
        branch_status: 分支机构状态筛选，仅"分支机构"支持，不筛选传空
            字符串。
        change_type: 变更类型筛选，仅"工商变更"支持，不筛选传空字符串。
        page_now: 页码，默认 1，仅"分支机构""工商变更""持股企业"支持
            分页。
        page_size: 每页条数，默认 20。
        order_column: 排序字段，仅"分支机构""工商变更"支持，不传用默认。
        order_type: 排序方向，默认 desc。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    if view == "标签资质信息":
        resp = await api_post("/cmp/detail/main", {}, params={"name": company_name})
    elif view == "工商信息":
        resp = await api_post("/cmp/detail/basic", {}, params={"name": company_name})
    elif view == "上市股东信息":
        params = {"name": company_name}
        if public_date:
            params["publicDate"] = public_date
        resp = await api_post("/cmp/holder/ipo/partner", {}, params=params)
    elif view == "工商股东信息":
        resp = await api_post("/cmp/holder/normal/partner", {}, params={"name": company_name})
    elif view == "上市主要人员":
        params = {"name": company_name}
        if public_date:
            params["publicDate"] = public_date
        if position:
            params["position"] = position
        resp = await api_post("/cmp/employee/ipo/list", {}, params=params)
    elif view == "工商主要人员":
        params = {"name": company_name}
        if public_date:
            params["publicDate"] = public_date
        if position:
            params["position"] = position
        resp = await api_post("/cmp/employee/normal/list", {}, params=params)
    elif view == "董监高投资任职":
        params = {"name": company_name}
        if office_name:
            params["officeName"] = office_name
        resp = await api_post("/cmp/officeinfo/list", {}, params=params)
    elif view == "分支机构":
        body = {
            "pageNum": page_now,
            "pageSize": page_size,
            "orderColumn": order_column,
            "orderType": order_type,
        }
        if branch_status:
            body["status"] = branch_status
        resp = await api_post("/cmp/branch/list", body, params={"name": company_name})
    elif view == "工商变更":
        body = {
            "pageNum": page_now,
            "pageSize": page_size,
            "orderColumn": order_column,
            "orderType": order_type,
        }
        if change_type:
            body["changeType"] = change_type
        resp = await api_post("/cmp/companychange/list", body, params={"name": company_name})
    elif view == "实际控制人":
        resp = await api_post("/cmp/control/list", {}, params={"companyName": company_name})
    elif view == "受益所有人":
        resp = await api_post("/cmp/beneficial/list", {}, params={"companyName": company_name})
    elif view == "持股企业":
        resp = await api_post(
            "/cmp/graph-trace/holder/p",
            {"companyName": company_name, "pageNow": page_now, "pageSize": page_size},
        )
    else:
        return {
            "status": "error",
            "error_message": (
                f"view 不认识：{view}，可选：标签资质信息/工商信息/上市股东信息/"
                "工商股东信息/上市主要人员/工商主要人员/董监高投资任职/分支机构/"
                "工商变更/实际控制人/受益所有人/持股企业"
            ),
        }
    return unwrap(resp)


# ---------------------------------------------------------------------------
# 4. 知识产权（不含 industryDetail/intellectual/*/find，见模块 docstring）
# ---------------------------------------------------------------------------

_IP_ENDPOINTS = {
    "专利趋势": "/cmp/detailIntellectual/patentTrend",
    "专利类型分布": "/cmp/detailIntellectual/patentTypeDistribution",
    "软件著作权": "/cmp/detailIntellectual/softwareCopyright",
    "作品著作权": "/cmp/detailIntellectual/workCopyright",
    "商标信息": "/cmp/detailIntellectual/trademark",
    "网站备案": "/cmp/detailIntellectual/websiteRecord",
}


@_企业查询工具
async def company_ip(
    company_name: str,
    view: str = "专利趋势",
    year: str = "",
    status: str = "",
    start_date: str = "",
    end_date: str = "",
    page_now: int = 1,
    page_size: int = 20,
) -> dict:
    """查询企业知识产权信息，按 view 参数选择具体维度。

    "专利列表"（patent/findPage）跟其它几个 view 形状不同——是分页明细
    列表，其它几个是汇总/分布/清单类数据，不支持分页，这里都保留，用
    view 区分，不强行统一成同一种返回形状。

    Args:
        company_name: 企业工商登记全称，见模块 docstring。
        view: 查询维度，可选：专利趋势（历年专利申请存量/增量）/专利类型
            分布（某年各类型专利数量占比）/软件著作权/作品著作权/商标
            信息/网站备案/专利列表（分页明细，含申请号/公开号/法律状态/
            发明人）。
        year: 统计年份，仅"专利类型分布"支持，不传按接口默认处理。
        status: 商标是否有效筛选，仅"商标信息"支持（如"有效"/"无效"），
            不筛选传空字符串。
        start_date: 起始日期筛选。对"软件著作权""作品著作权"是登记日期
            起始；对"专利列表"是专利申请日期起始。不筛选传空字符串。
        end_date: 截止日期筛选，含义对应 start_date。
        page_now: 页码，默认 1，仅"专利列表"支持分页。
        page_size: 每页条数，默认 20。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    if view == "专利列表":
        body = {"companyName": company_name, "pageNow": page_now, "pageSize": page_size}
        if start_date:
            body["applicationDateFrom"] = start_date
        if end_date:
            body["applicationDateTo"] = end_date
        resp = await api_post("/cmp/detailIntellectual/patent/findPage", body)
        return unwrap(resp)

    path = _IP_ENDPOINTS.get(view)
    if not path:
        return {
            "status": "error",
            "error_message": f"view 不认识：{view}，可选：{list(_IP_ENDPOINTS) + ['专利列表']}",
        }
    params = {"companyName": company_name}
    if view == "专利类型分布" and year:
        params["year"] = year
    if view == "商标信息" and status:
        params["status"] = status
    if view in ("软件著作权", "作品著作权"):
        if start_date:
            params["startDate"] = start_date
        if end_date:
            params["endDate"] = end_date
    resp = await api_get(path, params)
    return unwrap(resp)


# ---------------------------------------------------------------------------
# 5. 图谱
# ---------------------------------------------------------------------------

# view -> (path, 企业名参数字段名)
_GRAPH_ENDPOINTS = {
    "企业图谱": ("/cmp/companygraphy/companygraphy", "name"),
    "股权穿透图": ("/cmp/companygraphy/equitypenetration", "name"),
    # reference JSON 标的参数名是 "name"，实测传 name 直接系统异常，
    # 换成 companyName 才成功，见模块 docstring。
    "融资图谱": ("/idis_industry/teis/businessFinance/atlas", "companyName"),
}


@_企业查询工具
async def company_graph(company_name: str, view: str = "企业图谱") -> dict:
    """查询企业关系图谱，按 view 参数选择具体类型。

    Args:
        company_name: 企业工商登记全称，见模块 docstring。
        view: 图谱类型，可选：企业图谱（股东/对外投资/分支机构等关系
            全景）/股权穿透图（穿透后的实际控制链路）/融资图谱（创投/
            股票/债券等融资全景，图结构跟 group.py 的
            group_finance_graphy 类似但企业级）。

    Returns:
        status 及 data（成功时，原始图结构，未做精简）或 error_message。
    """
    cfg = _GRAPH_ENDPOINTS.get(view)
    if not cfg:
        return {
            "status": "error",
            "error_message": f"view 不认识：{view}，可选：{list(_GRAPH_ENDPOINTS)}",
        }
    path, name_key = cfg
    resp = await api_post(path, {name_key: company_name})
    return unwrap(resp)


# ---------------------------------------------------------------------------
# 6. 评分
# ---------------------------------------------------------------------------

_SCORE_ENDPOINTS = {
    "总分": "/cmp/company-asy/main",
    "价值评分细项": "/cmp/company-asy/detail",
    "科创总分": "/cmp/company-asy/main-tech",
    "科创总分细项": "/cmp/company-asy/detail-tech",
}


@_企业查询工具
async def company_score(company_name: str, view: str = "总分") -> dict:
    """查询企业评分，按 view 参数选择具体维度。

    实测对贵州茅台、宁德时代、美的集团这几家大企业，4 个 view 返回的
    结构本身都是对的（detail/科创总分细项 的 groups 分类字段有真实值），
    但具体的 scoreVal/scoreLevel/dt/排名字段全部是 null——像是评分数值
    这批数据当前环境暂缺，不是调用方式错了，见模块 docstring。

    Args:
        company_name: 企业工商登记全称，见模块 docstring。
        view: 查询维度，可选：总分（价值评分及区域/行业/全国排名）/价值
            评分细项（各细分维度评分明细）/科创总分（科创评分及排名）/
            科创总分细项（科创各细分维度评分明细）。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    path = _SCORE_ENDPOINTS.get(view)
    if not path:
        return {
            "status": "error",
            "error_message": f"view 不认识：{view}，可选：{list(_SCORE_ENDPOINTS)}",
        }
    resp = await api_post(path, {}, params={"name": company_name})
    return unwrap(resp)


# ---------------------------------------------------------------------------
# 7. 舆情公告研报
# ---------------------------------------------------------------------------

_NEWS_ENDPOINTS = {
    "舆情": "/cmp/companynews/opinionevent",
    "A股公告": "/cmp/companynews/aannouncement",
    "H股公告": "/cmp/companynews/hannouncement",
    "新三板公告": "/cmp/companynews/nqannouncement",
    "研报": "/cmp/companynews/companyreport",
}


@_企业查询工具
async def company_news(
    company_name: str,
    view: str = "舆情",
    start_date: str = "",
    end_date: str = "",
    emotion_direction_list: list[str] | None = None,
    page_num: int = 1,
    page_size: int = 20,
    order_column: str = "",
    order_type: str = "desc",
) -> dict:
    """分页查询企业舆情/公告/研报，按 view 参数选择具体类型。

    Args:
        company_name: 企业工商登记全称，见模块 docstring。
        view: 查询维度，可选：舆情（新闻舆情事件，含情绪方向）/A股公告/
            H股公告/新三板公告/研报（券商研究报告）。
        start_date: 发布日期起始筛选，格式 yyyy-MM-dd，不筛选传空字符串。
        end_date: 发布日期截止筛选。
        emotion_direction_list: 情绪类型筛选，仅"舆情"支持，不筛选不传。
        page_num: 页码，默认 1。
        page_size: 每页条数，默认 20。
        order_column: 排序字段，不传用默认。
        order_type: 排序方向，默认 desc。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    path = _NEWS_ENDPOINTS.get(view)
    if not path:
        return {
            "status": "error",
            "error_message": f"view 不认识：{view}，可选：{list(_NEWS_ENDPOINTS)}",
        }
    body = {
        "companyName": company_name,
        "pageNum": page_num,
        "pageSize": page_size,
        "orderColumn": order_column,
        "orderType": order_type,
        "startDate": start_date,
        "endDate": end_date,
    }
    if view == "舆情" and emotion_direction_list:
        body["emotionDirectionList"] = emotion_direction_list
    resp = await api_post(path, body)
    return unwrap(resp)


# ---------------------------------------------------------------------------
# 8. 资质认证
# ---------------------------------------------------------------------------

# view -> (path, 可选筛选字段名)
_QUALIFICATION_ENDPOINTS = {
    "科技资质": ("/cmp/detailQualification/techQualification", "level"),
    "绿色资质": ("/cmp/detailQualification/greenQualification", None),
    "荣誉榜单": ("/cmp/detailQualification/rankHonor", "level"),
    "国家标准": ("/cmp/detailQualification/nationalStandard", "status"),
    "国家标准计划": ("/cmp/detailQualification/nationalStandardPlan", "status"),
    "行业标准": ("/cmp/detailQualification/industryStandard", "status"),
    "地方标准": ("/cmp/detailQualification/localStandard", "status"),
    "团体标准": ("/cmp/detailQualification/groupStandard", "status"),
    "管理体系认证": ("/cmp/detailQualification/managementQualification", "status"),
}


@_企业查询工具
async def company_qualification(
    company_name: str, view: str = "科技资质", filter_value: str = ""
) -> dict:
    """查询企业资质认证信息，按 view 参数选择具体类型。

    Args:
        company_name: 企业工商登记全称，见模块 docstring。
        view: 查询维度，可选：科技资质/绿色资质/荣誉榜单/国家标准/国家
            标准计划/行业标准/地方标准/团体标准/管理体系认证。
        filter_value: 筛选值，含义随 view 而变——科技资质/荣誉榜单是
            认证级别（如"市级"/"国际级"），国家标准及以下 6 个标准类
            view 是标准/证书状态（如"现行"/"即将实施"）；绿色资质不
            支持筛选。不筛选传空字符串。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    cfg = _QUALIFICATION_ENDPOINTS.get(view)
    if not cfg:
        return {
            "status": "error",
            "error_message": f"view 不认识：{view}，可选：{list(_QUALIFICATION_ENDPOINTS)}",
        }
    path, filter_key = cfg
    params = {"companyName": company_name}
    if filter_key and filter_value:
        params[filter_key] = filter_value
    resp = await api_get(path, params)
    return unwrap(resp)


# ---------------------------------------------------------------------------
# 9. 财务
# ---------------------------------------------------------------------------

# view -> (path, kind)：kind 决定内部怎么拼参数，见函数实现。
_FINANCIALS_ENDPOINTS = {
    "财务指标": ("/cmp/aiplugin/financeindex", "aiplugin"),
    "资产负债表": ("/cmp/aiplugin/balancesheet", "aiplugin"),
    "利润表": ("/cmp/aiplugin/profit", "aiplugin"),
    "现金流量表": ("/cmp/aiplugin/cashflow", "aiplugin"),
    "主营构成-按项目": ("/cmp/aiplugin/project", "aiplugin"),
    "主营构成-按行业": ("/cmp/aiplugin/industry", "aiplugin"),
    "主营构成-按产品": ("/cmp/aiplugin/product", "aiplugin"),
    "主营构成-按地区": ("/cmp/aiplugin/area", "aiplugin"),
    "财务概览": ("/cmp/detailOperation/mainIndicator", "op_simple"),
    "主营构成历年": ("/cmp/detailOperation/majorBusinessLineChart", "op_classification"),
    "主营构成当年占比": ("/cmp/detailOperation/majorBusinessPieChart", "op_pie"),
}


@_企业查询工具
async def company_financials(
    company_name: str,
    view: str = "财务概览",
    date: str = "",
    classification: str = "",
    indicator: str = "",
    year: str = "",
) -> dict:
    """查询企业财务报表与主营构成，按 view 参数选择具体维度。

    "财务指标""资产负债表""利润表""现金流量表""主营构成-按{项目/行业/
    产品/地区}"这 8 个 view（对应 /cmp/aiplugin/* 接口组）实测对贵州
    茅台、宁德时代、比亚迪、美的集团这几家确定无疑的 A 股上市公司全部
    返回 success=true 但 data 为空、msg="非A股上市企业无此数据"——这个
    提示文案本身就不准确，更像是这批数据源在当前环境暂时是空的，不是
    参数传错了（同组的"财务概览"用不同数据源，对同一批公司正常出数据）。
    调用方遇到这几个 view 查不到数据不代表企业真的没有财务数据，可能
    只是这个数据源当前环境暂缺，见模块 docstring 的详细记录。

    Args:
        company_name: 企业工商登记全称，见模块 docstring。
        view: 查询维度，可选：财务指标（每股收益等）/资产负债表/利润表/
            现金流量表/主营构成-按项目/主营构成-按行业/主营构成-按产品/
            主营构成-按地区（以上 8 个来自 aiplugin 数据源，见上方
            数据源提示）/财务概览（营收/净利润/资产负债率等核心指标，
            默认 view，数据源可靠）/主营构成历年（历年趋势）/主营构成
            当年占比（某年占比分布）。
        date: 报表查询时间，仅 aiplugin 那 8 个 view 支持，格式
            yyyy-MM-dd，不传按接口默认（通常最新报告期）处理。
        classification: 主营构成分类维度，仅"主营构成历年""主营构成
            当年占比"支持，如"行业"/"产品"/"地区"，不传用接口默认。
        indicator: 主营构成看的指标，仅"主营构成当年占比"支持，如
            "收入"/"成本"，不传用接口默认。
        year: 主营构成占比查询年份，仅"主营构成当年占比"支持，如
            "2023"，不传用接口默认（通常最新年份）。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    cfg = _FINANCIALS_ENDPOINTS.get(view)
    if not cfg:
        return {
            "status": "error",
            "error_message": f"view 不认识：{view}，可选：{list(_FINANCIALS_ENDPOINTS)}",
        }
    path, kind = cfg
    if kind == "aiplugin":
        params = {"name": company_name}
        if date:
            params["date"] = date
        resp = await api_get(path, params)
    elif kind == "op_simple":
        resp = await api_get(path, {"companyName": company_name})
    elif kind == "op_classification":
        params = {"companyName": company_name}
        if classification:
            params["classification"] = classification
        resp = await api_get(path, params)
    else:  # op_pie
        params = {"companyName": company_name}
        if classification:
            params["classification"] = classification
        if indicator:
            params["indicator"] = indicator
        if year:
            params["year"] = year
        resp = await api_get(path, params)
    return unwrap(resp)


# ---------------------------------------------------------------------------
# 10. 经营明细
# ---------------------------------------------------------------------------

# view -> (path, 真实 HTTP 方法)：文档统一标 POST，实测方法并不统一，见
# 模块 docstring。
_BUSINESS_DETAIL_ENDPOINTS = {
    "客户": ("/cmp/detailOperation/customer", "POST"),
    "供应商": ("/cmp/detailOperation/supplier", "POST"),
    "招聘信息": ("/cmp/detailOperation/recruit", "GET"),
    "投标项目": ("/cmp/detailOperation/tenderee", "POST"),
    "招标项目": ("/cmp/detailOperation/winTenderer", "POST"),
    "债券主体评级": ("/cmp/detailOperation/bondComCredit", "GET"),
    "进出口信用评级": ("/cmp/detailOperation/importExportCredit", "GET"),
    "税务评级": ("/cmp/detailOperation/taxCredit", "GET"),
    "产品服务": ("/cmp/detail/productInfo", "GET"),
}


@_企业查询工具
async def company_business_detail(company_name: str, view: str = "客户") -> dict:
    """查询企业经营明细信息，按 view 参数选择具体类型。

    Args:
        company_name: 企业工商登记全称，见模块 docstring。
        view: 查询维度，可选：客户/供应商（供应链关系）/招聘信息（在招
            职位）/投标项目（作为招标方）/招标项目（作为中标方）/债券
            主体评级/进出口信用评级（海关信用等级）/税务评级/产品服务
            （主营产品与服务简介）。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    cfg = _BUSINESS_DETAIL_ENDPOINTS.get(view)
    if not cfg:
        return {
            "status": "error",
            "error_message": f"view 不认识：{view}，可选：{list(_BUSINESS_DETAIL_ENDPOINTS)}",
        }
    path, method = cfg
    if method == "GET":
        resp = await api_get(path, {"name": company_name})
    else:
        resp = await api_post(path, {}, params={"name": company_name})
    return unwrap(resp)


# ---------------------------------------------------------------------------
# 11. 高级搜索（不传 company_name，返回匹配的企业列表，见模块 docstring）
# ---------------------------------------------------------------------------

async def company_advanced_search(
    view: str = "关键词",
    keyword: str = "",
    industry_code_in: list[str] | None = None,
    industry_type: str = "CSF",
    region_info: list[dict] | None = None,
    types: list[str] | None = None,
    natures: list[str] | None = None,
    models: list[str] | None = None,
    status: list[str] | None = None,
    ages: list[str] | None = None,
    employee_counts: list[str] | None = None,
    regcaps: list[str] | None = None,
    pe_rounds: list[str] | None = None,
    ipo_rounds: list[str] | None = None,
    ipo_boards: list[str] | None = None,
    page_now: int = 1,
    page_size: int = 10,
) -> dict:
    """多维度搜索匹配企业（发现型搜索，不是单一企业详情查询），按 view
    参数选择走哪条搜索通路。

    实测证明这两条搜索接口不是重复的：view=关键词 只做全文检索，不支持
    下面这些结构化筛选条件（传了也不生效）；view=多维度筛选 支持完整的
    结构化筛选，但返回的是更原始的字段（不含 view=关键词 那种整理过的
    scoreInfo/tagInfo 卡片结构）。按需选择，不确定就先用 view=关键词。

    Args:
        view: 搜索通路，可选：关键词（全文检索，只用 keyword 参数，
            返回值含 scoreInfo/tagInfo/monitorInfo 等整理过的企业卡片
            字段）/多维度筛选（支持下面全部结构化筛选条件，返回值是
            较原始的字段，含 relevanceProductInfos 产业匹配度等）。
        keyword: 关键词，两种 view 都支持（多维度筛选下对应 keyText
            语义，可选）。view=关键词时必填。
        industry_code_in: 产业代码筛选，仅多维度筛选支持，需先用
            industry.py 那套 industry_type 体系解析出代码；不筛选不传。
        industry_type: 产业分类体系，仅 industry_code_in 传值时生效，
            默认 CSF，可选 SELECTED/CSF/NSEI/GB/DE。
        region_info: 地区筛选，仅多维度筛选支持，格式如
            [{"name":"西城区","code":"110102","path":["北京市","西城区"]}]，
            不筛选不传。
        types: 企业类型筛选，如 ["有限责任公司","股份有限公司"]，仅多
            维度筛选支持，不筛选不传。
        natures: 企业性质筛选，如 ["国有企业","民营企业"]，仅多维度
            筛选支持，不筛选不传。
        models: 企业规模筛选，如 ["large","medium"]，仅多维度筛选支持，
            不筛选不传。
        status: 经营状态筛选，如 ["存续 (在营、开业、在册)"]，仅多维度
            筛选支持，不筛选不传。
        ages: 成立年限筛选，如 ["0-3","0-6"]，仅多维度筛选支持，不筛选
            不传。
        employee_counts: 员工数区间筛选，如 ["0-20","20-99"]，仅多维度
            筛选支持，不筛选不传。
        regcaps: 注册资本区间筛选，如 ["0-100","100-500"]，仅多维度
            筛选支持，不筛选不传。
        pe_rounds: PE/VC 融资轮次筛选，仅多维度筛选支持，不筛选不传。
        ipo_rounds: IPO 阶段筛选，仅多维度筛选支持，不筛选不传。
        ipo_boards: IPO 上市板块筛选，仅多维度筛选支持，不筛选不传。
        page_now: 页码，默认 1。
        page_size: 每页条数，默认 10。

    Returns:
        status 及 data（成功时，含匹配企业列表）或 error_message。
    """
    if view == "关键词":
        if not keyword:
            return {"status": "error", "error_message": "view=关键词 时 keyword 必填"}
        # reference JSON 把这条接口的方法标成 GET、参数也没提取到；实测
        # GET 一律 "method error"，真实方法是 POST，真实关键字段是
        # keyword（不是常见的 keyText/name/companyName），见模块 docstring。
        resp = await api_post(
            "/idis_industry/teis/landing/company/pro/advanceSearch",
            {"keyword": keyword, "pageNow": page_now, "pageSize": page_size},
        )
    elif view == "多维度筛选":
        body: dict = {
            "pageNow": page_now,
            "pageSize": page_size,
            "sortCol": 1,
            "sortType": 1,
        }
        if keyword:
            body["keyText"] = keyword
        if industry_code_in:
            body["industryCodeIn"] = industry_code_in
            body["industryType"] = industry_type
        if region_info:
            body["regionInfo"] = region_info
        if types:
            body["types"] = types
        if natures:
            body["natures"] = natures
        if models:
            body["models"] = models
        if status:
            body["status"] = status
        if ages:
            body["ages"] = ages
        if employee_counts:
            body["employeeCounts"] = employee_counts
        if regcaps:
            body["regcaps"] = regcaps
        if pe_rounds:
            body["peRounds"] = pe_rounds
        if ipo_rounds:
            body["ipoRounds"] = ipo_rounds
        if ipo_boards:
            body["ipoBoards"] = ipo_boards
        resp = await api_post("/idis_industry/teis/company/search/go", body)
    else:
        return {
            "status": "error",
            "error_message": f"view 不认识：{view}，可选：['关键词', '多维度筛选']",
        }
    return unwrap(resp)


# ---------------------------------------------------------------------------
# 12-14. 融资（这批是这次任务里专门要求实测澄清的模糊地带，见模块 docstring
# 三个坑的完整说明；只接 v2 版本，不接已确认失效的裸路径 /finance/* 版本，
# 也不重复实现 region.py 已经有的 amount/type/region/trend/top/patent-stat）
# ---------------------------------------------------------------------------

@_企业查询工具
async def company_finance_summary(
    company_name: str, view: str = "融资概览", start: str = "", end: str = ""
) -> dict:
    """查询企业融资概览或融资历程（都是汇总性数据，不分页）。

    Args:
        company_name: 企业工商登记全称，见模块 docstring。
        view: 查询维度，可选：融资概览（历年融资金额/事件数及各类型
            占比）/融资历程（各类型融资总额及具体融资事件时间线）。
        start: 起始日期筛选，仅"融资概览"支持，格式 yyyy-MM-dd，不筛选
            传空字符串。
        end: 截止日期筛选，仅"融资概览"支持。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    if view == "融资概览":
        body = {"companyName": company_name}
        if start:
            body["start"] = start
        if end:
            body["end"] = end
        resp = await api_post("/idis_industry/teis/v2/businessFinance/finance/overview", body)
    elif view == "融资历程":
        resp = await api_post(
            "/idis_industry/teis/v2/businessFinance/finance/journey",
            {"companyName": company_name},
        )
    else:
        return {
            "status": "error",
            "error_message": f"view 不认识：{view}，可选：['融资概览', '融资历程']",
        }
    return unwrap(resp)


@_企业查询工具
async def company_finance_events(
    company_name: str,
    finance_type: int | None = None,
    filter_type: list[str] | None = None,
    record_status: list[str] | None = None,
    desc: bool = True,
    page: int = 1,
    page_size: int = 20,
    sort_type: str = "",
) -> dict:
    """分页查询企业各类融资事件明细（创投/股票/债券/银行借款等）。

    对应原始接口 `/idis_industry/teis/v2/businessFinance/query`（"各类
    融资"）。文档里还有一个裸路径 `/finance/query`（"创投融资"），参数
    形状接近但实测已经 405 不通（见模块 docstring），本工具只用 v2 版本。

    Args:
        company_name: 企业工商登记全称，见模块 docstring。
        finance_type: 融资类型标志筛选，不传查全部类型。
        filter_type: 融资轮次筛选，如 ["天使轮","A轮"]，不筛选不传。
        record_status: 登记状态筛选，不筛选不传。
        desc: 是否按时间倒序，默认 True。
        page: 页码，默认 1。
        page_size: 每页条数，默认 20。
        sort_type: 排序方式，不传用接口默认。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    body: dict = {
        "companyName": company_name,
        "desc": desc,
        "page": page,
        "pageSize": page_size,
    }
    if finance_type is not None:
        body["financeType"] = finance_type
    if filter_type:
        body["filterType"] = filter_type
    if record_status:
        body["recordStatus"] = record_status
    if sort_type:
        body["sortType"] = sort_type
    resp = await api_post("/idis_industry/teis/v2/businessFinance/query", body)
    return unwrap(resp)


_CREDIT_INVESTMENT_ENDPOINTS = {
    "授信额度": "/idis_industry/teis/v2/businessFinance/finance/creditLine",
    "债券持有人": "/idis_industry/teis/v2/businessFinance/finance/holder",
    "对外投资": "/idis_industry/teis/v2/businessFinance/finance/outInvestment",
}


@_企业查询工具
async def company_credit_and_investment(
    company_name: str,
    view: str = "授信额度",
    desc: bool = True,
    page: int = 1,
    page_size: int = 20,
    sort_type: str = "",
    status_list: list[str] | None = None,
) -> dict:
    """分页查询企业授信额度、债券持有人或对外投资信息，按 view 选择类型。

    view=授信额度 对应的接口实测对多家真实大企业（含地产公司）都返回
    success=true 但 data=null，跟同组 债券持有人/对外投资（参数形状完全
    一致）能正常出数据形成对比——更像是这张数据表在当前环境里覆盖率低/
    是空的，不代表参数传错了，见模块 docstring。

    Args:
        company_name: 企业工商登记全称，见模块 docstring。
        view: 查询维度，可选：授信额度（见上方数据源提示）/债券持有人/
            对外投资。
        desc: 是否按时间倒序，默认 True。
        page: 页码，默认 1。
        page_size: 每页条数，默认 20。
        sort_type: 排序方式，不传用接口默认。
        status_list: 被投资企业状态筛选，仅"对外投资"支持，不筛选不传。

    Returns:
        status 及 data（成功时）或 error_message。
    """
    path = _CREDIT_INVESTMENT_ENDPOINTS.get(view)
    if not path:
        return {
            "status": "error",
            "error_message": f"view 不认识：{view}，可选：{list(_CREDIT_INVESTMENT_ENDPOINTS)}",
        }
    body: dict = {"companyName": company_name, "desc": desc, "page": page, "pageSize": page_size}
    if sort_type:
        body["sortType"] = sort_type
    if view == "对外投资" and status_list:
        body["statusList"] = status_list
    resp = await api_post(path, body)
    return unwrap(resp)
