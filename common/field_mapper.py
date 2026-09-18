"""中文映射：把网关出参的英文字段 key 翻译成中文名称。

翻译优先级：
1. `api文件/中文映射` 配置（《企业数据接口_0804.json》《产业全部接口_1105.json》，
   已复制到 data/field_mapping_*.json）：按 API_url 建索引，financeType/
   tabName 上下文消歧，子结构递归翻译；
2. 自动翻译表 data/field_mapping_auto.json（并镜像回 api文件/中文映射/
   自动翻译字段.json）：配置里没有的 key 先查内置字段词典（完整字段名优先，
   其次单词组合），命中即翻译并**保存到配置**，之后直接复用；
3. 都没有对应中文的 key 保留原名。

规则（与配置文件的组织方式一致）：
- 同一个 URL 挂多张翻译表时（如 finance/query 的 FinanceQuery_1~8），按请求
  上下文消歧：financeType 优先，其次 tabName，都没有就用第一张表；
- 无 URL 的组是子结构表（如 CmpDetailMain-ipoInfos），挂到父接口对应字段上
  做递归翻译；无 URL 且无分隔符的组（如 CmpControlList）按驼峰名推导 URL。
"""

import json
import re
import threading
from copy import deepcopy
from pathlib import Path

_PROJECT_DATA = Path(__file__).resolve().parent.parent / "data"
_REPO_MAPPING = Path(__file__).resolve().parents[3] / "api文件" / "中文映射"

_ENTERPRISE_FILE = "field_mapping_enterprise.json"
_ENTERPRISE_SOURCE = "企业数据接口_0804.json"
_INDUSTRY_FILE = "field_mapping_industry.json"
_INDUSTRY_SOURCE = "产业全部接口_1105.json"
_AUTO_FILE = "field_mapping_auto.json"
_AUTO_SOURCE = "自动翻译字段.json"

_META_KEYS = {"API_url", "API_description", "description"}


class _GroupMap:
    """一个接口的字段翻译表：fields 字段映射 + children 子结构表。"""

    __slots__ = ("name", "fields", "children", "description")

    def __init__(self, name: str = ""):
        self.name = name
        self.fields: dict[str, str] = {}
        self.children: dict[str, _GroupMap] = {}
        self.description = ""


def _norm_url(url: str) -> str:
    return url.strip("/").replace("//", "/")


def _separator_positions(name: str) -> list[int]:
    return [i for i, ch in enumerate(name) if ch in "-_"]


def _fields_of(mapping: dict) -> dict[str, str]:
    return {k: v for k, v in mapping.items() if k not in _META_KEYS}


def _build_groups(raw: dict) -> dict[str, _GroupMap]:
    """把单个配置文件里的组组织成 {组名: 翻译表}，子结构挂到父表 children。"""
    groups: dict[str, _GroupMap] = {}

    def ensure(name: str) -> _GroupMap:
        if name not in groups:
            groups[name] = _GroupMap(name)
        return groups[name]

    for name, mapping in raw.items():
        if mapping.get("API_url"):
            gm = ensure(name)
            gm.fields = _fields_of(mapping)
            gm.description = mapping.get("API_description") or ""

    sub_paths: dict[str, list[str]] = {}
    ordered = sorted(
        ((name, mapping) for name, mapping in raw.items() if not mapping.get("API_url")),
        key=lambda item: len(_separator_positions(item[0])),
    )
    for name, mapping in ordered:
        fields = _fields_of(mapping)
        description = mapping.get("API_description") or ""
        if not fields and not description:
            continue
        resolved = None
        for pos in reversed(_separator_positions(name)):
            prefix, suffix = name[:pos], name[pos + 1:]
            if prefix in groups or prefix in sub_paths:
                resolved = (prefix, suffix)
                break
        if resolved is None:
            tokens = re.findall(r"[A-Za-z][a-z]*", name)
            if len(tokens) >= 2:
                gm = ensure(name)
                gm.fields.update(fields)
                gm.description = description
        else:
            prefix, suffix = resolved
            path = [prefix] if prefix in groups else list(sub_paths[prefix])
            parent = groups[path[0]]
            node = parent
            for seg in path[1:]:
                child = node.children.get(seg)
                if child is None:
                    child = _GroupMap(seg)
                    node.children[seg] = child
                node = child
            leaf = node.children.get(suffix)
            if leaf is None:
                leaf = _GroupMap(suffix)
                node.children[suffix] = leaf
            leaf.fields.update(fields)
            if description:
                leaf.description = description
            sub_paths[name] = path + [suffix]
    return groups


def _derived_url(group_name: str) -> str | None:
    """无 URL 独立组的 URL 推导：CmpControlList -> /cmp/control/list。"""
    tokens = re.findall(r"[A-Za-z][a-z]*", group_name)
    if len(tokens) < 2:
        return None
    return "/" + "/".join(token.lower() for token in tokens)


# ---------------------------------------------------------------------------
# 自动翻译：完整字段名词典（优先）+ 单词组合词典（兜底）
# ---------------------------------------------------------------------------

_AUTO_FULL_KEYS = {
    # 分页/信封通用
    "pageNow": "页码", "pageNum": "页码", "pageSize": "每页条数", "totalPage": "总页数",
    "totalCount": "数据总量", "total": "总数", "pages": "总页数", "startIndex": "起始索引",
    "endIndex": "结束索引", "orderColumn": "排序字段", "orderType": "排序方式", "order": "排序",
    "list": "列表", "datas": "数据", "fieldDictionary": "筛选项", "serialNo": "序号",
    "keyword": "关键词", "keywordHint": "关键词提示", "keywordHintType": "关键词提示类型",
    "children": "子项", "path": "路径", "root_code": "根代码", "matchList": "匹配列表",
    "tree": "树", "label": "名称", "value": "数值", "key": "类型", "val": "数量",
    # 企业通用
    "companyName": "企业名称", "entname": "企业名称", "name": "名称",
    "creditCode": "统一社会信用代码", "province": "省", "city": "市",
    "county": "区县", "district": "区县", "statusName": "经营状态", "typeName": "企业类型",
    "regNo": "工商注册号", "regorgName": "登记机关", "regcap": "注册资本",
    "regcapName": "注册资本单位", "recCap": "实缴资本", "opscope": "经营范围",
    "dom": "注册地址", "legalPerson": "法人", "opfrom": "经营期限自", "opto": "经营期限至",
    "esdate": "成立日期", "apprdate": "核准日期", "candate": "注销日期", "revdate": "吊销日期",
    "revcanRea": "注吊销原因", "telphone": "联系电话", "email": "公司邮箱",
    "website": "公司网站", "address": "经营地址", "companyProfile": "企业简介",
    "endoInsNum": "养老保险参保人数", "industrycoName": "行业代码中文",
    "industrycoCode": "行业代码", "employeeCount": "人员规模", "model": "企业规模",
    "productClsNames": "标准产业名称", "nseiClsNames": "国战新产业名称",
    "featureClsNames": "特色产业名称", "officeinfos": "高管信息", "enName": "企业英文名",
    "originalName": "企业曾用名", "parkNames": "所属园区名称", "taxpayerQualifi": "纳税人资格",
    "parkInfos": "所属园区", "industrycoChainName": "产业链名称",
    "registeredCapital": "注册资本", "paidCapital": "实缴资本",
    "establishmentDate": "成立日期", "companyStatus": "企业状态", "companyType": "企业类型",
    "companyNature": "企业性质", "companyScale": "企业规模", "legalPersonList": "法人列表",
    "legalPersonName": "法人姓名", "contactPhoneList": "联系电话列表", "emailList": "邮箱列表",
    "companyAddress": "经营地址", "registeredAddress": "注册地址", "regionInfo": "地址信息",
    "provinceName": "省", "cityName": "市", "regionName": "区县", "scoreInfo": "企业评分",
    "basicInfo": "企业基本信息", "tagInfo": "标签信息", "monitorInfo": "监控信息",
    "favoriteInfo": "收藏信息", "logoUrl": "logo图片地址", "productInfo": "产品信息",
    "competeProductInfo": "竞品信息", "entPortrait": "主营业务", "entValue": "企业综合价值评分",
    "rankPercent": "评级", "rankCode": "评级代码", "rankRegion": "评级区域",
    "industryPark": "所属园区", "point": "注册地址经纬度", "addressPoint": "经营地址经纬度",
    "ipoSuccess": "上市成功标志", "ipoInfos": "上市信息", "bondInfos": "发债信息",
    "roundInfos": "融资信息", "techZzInfos": "科技资质", "greenZzInfos": "绿色资质",
    "topZzInfos": "荣誉榜单", "stdInfos": "标准制定", "groupInfo": "集团信息",
    "comScore": "价值评分", "biddingInfo": "招投标数量信息", "techComScore": "科创评分",
    "comEvent": "企业监控信息", "rzPeRound": "融资轮次", "typeNameChar": "企业类型中文名称",
    "rzPeIpo": "上市进程", "regCapital": "注册资本(带单位)", "registCapiUnit": "注册资本单位",
    "registCapiValue": "注册资本", "regorgCity": "登记机关所在市", "regorgCounty": "登记机关所在县",
    "regorgName": "登记机关中文", "regorgProvince": "登记机关所在省", "extTag": "特色企业补充字段",
    "entValue": "企业综合价值评分", "selectedClsCodes": "精选产业分类字段",
    # 融资事件
    "amount": "金额", "amountCny": "融资金额（万元 人民币）", "unit": "单位",
    "currency": "币种", "financeDate": "融资日期", "rate": "利率", "endDate": "截止日期",
    "maturity": "期限", "secuAbbr": "证券简称", "secuCode": "证券代码",
    "bondNature": "债券类型", "creditRating": "债券评级", "issuePrice": "发行价格",
    "issueVol": "发行量", "shareRatio": "持股比例", "recordType": "登记状态",
    "propertyValue": "财产价值", "propertyValueCny": "财产价值（万元 人民币）",
    "publishDate": "披露日期", "startDate": "起始日期", "financierItems": "融资方",
    "investorItems": "投资方", "guarantorItems": "担保人", "type1": "融资类型",
    "type2": "融资类型细分", "childType": "子类型", "originalType": "融资轮次",
    "investmentDate": "投资日期", "investeeAge": "被投年限", "roundName": "轮次名称",
    "investingFundList": "参投基金列表", "industryInfo": "产业信息",
    "companyStartDate": "企业成立日期", "investMoney": "投资金额", "exitMoney": "退出金额",
    "exitDate": "退出日期", "exitType": "退出方式", "returnMultiple": "账面回报倍数",
    "returnRate": "内部收益率", "market": "交易场所", "beforeIpoStock": "上市前持股",
    "beforeIpoScale": "上市前规模", "afterIpoStock": "上市后持股", "afterIpoScale": "上市后规模",
    "investmentMode": "投资方式", "investorName": "出资人名称", "investorType": "出资人类型",
    "stateOwned": "是否国企", "stockPercent": "持股比例", "subscribedCapital": "认缴出资额",
    "reportDate": "报告期", "bondAbbr": "债券简称", "bondCode": "债券代码", "holder": "持有人",
    "amountChange": "较上期变化", "amountChangeType": "变化类型", "holdVolume": "持仓数量",
    "fundComName": "管理人", "totalCreditLine": "授信额度", "usedQuota": "已使用额度",
    "unusedQuota": "未使用额度", "signCreditBankNum": "授信家数", "creditLine": "授信额度",
    "companyPortrait": "主营业务", "stockPercentNum": "持股比例", "registCapi": "注册资本",
    "registCapiStr": "注册资本字符串", "operName": "法定代表人", "status": "状态",
    # 股东/人员
    "holderName": "股东名称", "holderType": "股东类型", "publicDate": "报告日期",
    "count": "持股数", "changeCount": "较上期变动数", "proportion": "持股比例",
    "imageUrl": "图片地址", "stockName": "股东名称", "stockType": "股东类型",
    "shouldCapi": "认缴出资额", "shouldCapiUnit": "认缴出资额单位", "shouldDate": "认缴出资日期",
    "position": "职务", "job": "职务", "jobNum": "职务代码", "dates": "变更日期",
    "sex": "性别", "stock": "持股数", "education": "学历", "reward": "报酬",
    "oldPosition": "原职务", "gender": "性别", "degree": "学历", "bithyear": "出生年份",
    "background": "背景", "groups": "所属集团", "companyAmount": "关联企业数",
    "partnerAmount": "合作伙伴数", "personNo": "人物编号", "no": "编号",
    "personCompanyCount": "关联企业数", "percent": "持股比例", "shortestLevel": "最短层级",
    "pathDetail": "股权路径详情", "paths": "路径", "graphsList": "股权链路",
    "startCompanyName": "起始企业", "endCompanyName": "目标企业",
    # 基金
    "fundName": "基金名称", "fundNo": "基金编号", "fundOrgName": "基金机构名称",
    "establishDate": "成立日期", "managerName": "管理人名称", "managerType": "管理人类型",
    "mandatorName": "委托人名称", "putOnRecordDate": "备案日期", "capitalType": "资本类型",
    "targetScale": "目标规模", "raiseStatus": "募集状态", "workingState": "运作状态",
    "stateOwnedShareRatio": "国企持股比例", "isGuideFund": "是否引导基金",
    "guideFundLevel": "引导基金级别", "isFofFund": "是否母基金", "fundType": "基金类型",
    "formKind": "组织形式", "associationUrl": "协会链接", "guideFund": "引导基金",
    "fofFund": "母基金", "fundIntro": "基金简介",
    # 招投标/经营明细
    "tendereePageTime": "招标公告日期", "winTendererPageTime": "中标公告日期",
    "noticeType": "公告类型", "projectArea": "项目地区", "projectName": "项目名称",
    "projectType": "项目类型", "tendereeCompanyName": "招标方企业名称",
    "tendereeCreditCode": "招标方统一社会信用代码", "winTendererCompanyName": "中标方企业名称",
    "winTendererCreditCode": "中标方统一社会信用代码", "biddingBudget": "招标金额",
    "winBidPrice": "中标金额", "product": "采购产品", "region": "区域",
    "supplierName": "供应商名称", "supplierCreditCode": "供应商统一社会信用代码",
    "supplierStatus": "供应商状态", "customerName": "客户名称",
    "customerCreditCode": "客户统一社会信用代码", "customerStatus": "客户状态",
    "tradeAmount": "采购金额", "reportTime": "报告期", "source": "数据来源",
    "title": "标题", "salary": "月薪", "experience": "经验", "area": "办公地点",
    "description": "描述", "publishTime": "发布日期", "stockCode": "证券代码",
    "shareAbbr": "证券简称", "infoTitle": "公告标题", "infoPublDate": "发布日期",
    "infoPublTime": "发布时间", "media": "来源", "announcementLink": "原文链接",
    "rpTitle": "研报标题", "emratingName": "评级", "columnName": "研报类型",
    "pubCompanyName": "分析机构", "allPerson": "分析师", "sourceURL": "原文链接",
    "sourceName": "来源", "eventName": "事件类型", "emotionDirection": "情绪类型",
    "emotionImportance": "情感重要度", "linkAddress": "原文链接",
    # 图谱
    "nodeType": "节点类型", "ratio": "持股比例", "stockType": "股份类型",
    "minPositionNum": "最小任职数", "tradeAmount": "交易金额", "isControl": "是否实际控制",
    "reportDate": "报告期", "l": "左侧", "r": "右侧",
    # 风险类
    "lianDate": "立案日期", "anNo": "案号", "orgNo": "企业统一社会信用代码",
    "executeGov": "执行法院", "executeUnite": "做出执行依据单位", "yiwu": "生效法律文书确定的义务",
    "executeStatus": "履行情况", "actionRemark": "被执行人行为具体情形", "executeNo": "执行依据文号",
    "biaodi": "执行标的", "peopleEnforced": "限制人员", "caseNumber": "案号",
    "courtName": "执行法院", "filingTime": "立案日期", "executeApplyName": "申请执行人",
    "subjectMatter": "案由", "content": "内容", "regDate": "立案日期", "finalDate": "终本日期",
    "caseNo": "案号", "execMoney": "执行标的", "unperfMoney": "未履行金额",
    "registDate": "立案日期", "partyType": "案件身份", "caseType": "案件类型",
    "reason": "案由", "prosecutor": "原告", "appellee": "被告", "court": "法院",
    "caseStatus": "案件状态", "category": "公告类型", "partyName": "当事人",
    "publishPage": "刊登版面", "caseReason": "案由", "scheduleTime": "排期日期",
    "undertakeDepartment": "承办部门", "chiefJudge": "审判长/主审人", "submitDate": "发布日期",
    "caseName": "文书名称", "caseRole": "案件身份", "courtLevel": "法院级别",
    "defendant": "被告", "wenshuType": "文书类型", "trialRound": "审理程序",
    "judgeDate": "裁判日期", "contentClear": "判决结果", "auctionNotice": "拍卖公告标题",
    "auctionStartTime": "拍卖开始日期", "auctionEndTime": "拍卖结束日期",
    "auctionItemName": "拍品名称", "markType": "做出执行依据单位", "salePrice": "起拍价额",
    "appraisalPrice": "评估价", "auctionStatus": "拍卖状态", "turnoverPrice": "成交价格",
    "tradingDate": "成交日期", "executionNoticeNum": "执行通知书文号", "executedBy": "被执行人",
    "equityAmount": "股权数额", "enforcementCourt": "执行法院", "freezeStartDate": "冻结期限自",
    "freezeEndDate": "冻结期限至", "applicant": "申请人", "penaltyDate": "处罚日期",
    "docNo": "决定文书号", "penaltyType": "违法行为分类", "penaltyAmount": "处罚金额",
    "penaltyAmountStr": "处罚金额中文", "officeName": "处罚决定机关", "addDate": "列入日期",
    "removeDate": "移出日期", "addReason": "列入原因", "decisionOffice": "决定机关",
    "removeReason": "移出原因", "removeDecisionOffice": "移出决定机关",
    "taxpayerNum": "纳税人识别号", "taxCategory": "欠税税种", "newAmount": "新发生欠税",
    "issuedBy": "税务机关", "caseNature": "案件性质", "illegalContent": "违法事实",
    "taxGov": "税务机关", "punishReason": "处罚事由", "punishBasis": "处罚依据",
    "punishmentResult": "处罚结果", "punishGov": "处罚机关", "implementation": "执行情况",
    "bondNatureStr": "债券类型", "firstDefaultDate": "首次违约日期", "defaultTypeStr": "违约类型",
    "totalDefaultPrice": "违约金额", "totalRepaidPrice": "偿还金额", "repayRate": "偿还比例",
    "czPer": "出质人", "bdPer": "质押标的企业", "zqPer": "质权人", "czAmt": "出质股权数额",
    "writeOffDate": "注销时间", "res": "注销原因", "registerDate": "登记日期",
    "kind": "类型", "assuranceScope": "抵押期限", "registOffice": "登记机关",
    "names": "抵押权人", "landNo": "宗地编号", "mortgagePurpose": "抵押土地用途",
    "obligeeNo": "土地他项权利人证号", "usufructNo": "土地使用权证号", "acreage": "土地面积",
    "mortgageAcreage": "抵押面积", "assessmentPrice": "评估金额", "onBoardStartTime": "抵押起始日期",
    "onBoardEndTime": "抵押结束日期", "mortgagePrice": "抵押金额", "mortgagorName": "土地抵押人",
    "mortgageName": "土地抵押权人", "publicApplyDate": "公告申请日期", "registration": "登记机关",
    "result_content": "简易注销结果", "leader": "清算组负责人", "member": "清算组成员",
    # 资质/知识产权
    "qualificationType": "资质类别", "qualificationName": "资质名称", "identifyYear": "认定年度",
    "identifyLevel": "认定级别", "identifyUnit": "认定单位", "effectiveDate": "生效日期",
    "expiryDate": "资质有效期", "productName": "产品名称", "standardName": "标准名称",
    "standardNumber": "标准号", "standardNature": "标准性质", "standardStatus": "标准状态",
    "draftUnitList": "起草单位", "executeUnit": "执行单位", "industry": "所属行业",
    "approvalDepartment": "批准发布部门", "nationalIndustry": "国民经济行业分类",
    "groupName": "团体名称", "certificateType": "证书类别", "certificateName": "证书名称",
    "issuingAuthority": "发证机构", "certificateStatus": "证书状态", "fullName": "软件全称",
    "shortName": "软件简称", "version": "版本号", "registerNo": "登记号",
    "finishDate": "创作完成日期", "applyDate": "申请日期", "categoryDescription": "分类描述",
    "flowStatus": "商标状态", "domain": "域名", "licenseNo": "许可证号", "url": "网址",
    "applicationDate": "申请日期", "legalStatus": "法律状态", "applicationNumber": "申请号",
    "publicationNumber": "公开号", "publicationDate": "公告日期", "inventor": "发明人",
    "grade": "评级", "gradeType": "评级类型", "gradeDate": "评级日期", "gradeAgency": "评级机构",
    "gradeProspect": "展望", "customsCreditLevel": "海关信用等级",
    "customsRegisterDate": "海关注册日期", "customsRegisterName": "注册海关名称",
    "economicZone": "经济区划", "businessCategory": "经营类别",
    "publicIndustryCategory": "公示行业种类", "customsCancellationStatus": "海关注销标志",
    "taxNo": "纳税人识别号", "level": "等级", "year": "年份", "brief": "产品服务",
    "intro": "介绍", "logo": "商标图片地址", "applicant": "申请人",
    "tagType": "标签类型", "tagName": "标签名称", "aggName": "标签名称",
    "detail": "详情", "code": "代码", "valueScore": "综合评分", "innovationScore": "科创评分",
    "scoreValue": "得分", "scoreGrade": "评级", "marketScore": "市场评分",
    "stabilityScore": "稳定性评分", "advancedScore": "先进性评分", "protectionScore": "保护范围评分",
    "valueScore": "评分", "tagList": "标签列表", "companyName": "企业名称",
    "orgName": "研究机构", "analystList": "分析师列表", "pdfUrl": "研报链接",
    "pageCount": "页数", "summary": "摘要", "analystName": "分析师名",
    # 产业
    "industryName": "产业名称", "industryCode": "产业代码", "industryType": "产业分类体系",
    "regionCode": "区域代码", "regionName": "区域名称", "relevance": "相关度",
    "relevanceGrade": "相关度等级", "industryRootCode": "产业根代码", "csfIndustryList": "产业链分类",
    "selectedIndustryList": "精选产业分类", "nseiIndustryList": "战新产业分类",
    "gbIndustryList": "国标行业分类", "deIndustryList": "数字经济产业分类",
    "itemList": "列表", "timeItemList": "时间条目", "indicatorItemList": "指标条目",
    "indicator": "指标名称", "stockItemList": "规模趋势", "scaleItemList": "企业规模",
    "natureItemList": "企业性质", "ageItemList": "企业经营年限", "capitalItemList": "企业注册资本",
    "concentrationRate": "集中度", "compositeScore": "评分", "companyCount": "企业数量",
    "time": "时间", "scale": "企业规模", "items": "条目",
    # 人物任职公司
    "registCapiStr": "注册资本", "registeredCapital": "注册资本",
    "startDate": "成立日期",
}

_WORD_GLOSSARY = {
    "company": "企业", "name": "名称", "date": "日期", "time": "时间", "count": "数量",
    "total": "总计", "list": "列表", "item": "条目", "info": "信息", "amount": "金额",
    "unit": "单位", "year": "年份", "month": "月份", "quarter": "季度", "report": "报告",
    "income": "收入", "profit": "利润", "revenue": "营收", "cost": "成本", "expense": "费用",
    "asset": "资产", "liability": "负债", "equity": "权益", "cash": "现金", "flow": "流量",
    "price": "价格", "volume": "数量", "number": "编号", "code": "代码", "status": "状态",
    "type": "类型", "nature": "性质", "scale": "规模", "level": "级别", "grade": "评级",
    "rating": "评级", "rate": "比率", "address": "地址", "province": "省", "city": "市",
    "county": "区县", "district": "区县", "region": "区域", "area": "区域", "industry": "产业",
    "fund": "基金", "investor": "投资方", "financier": "融资方", "holder": "持有人",
    "bond": "债券", "stock": "股票", "share": "股份", "bank": "银行", "trust": "信托",
    "lease": "租赁", "financing": "融资", "finance": "融资", "investment": "投资",
    "round": "轮次", "market": "市场", "currency": "币种", "maturity": "期限",
    "issue": "发行", "publish": "发布", "public": "公开", "register": "登记",
    "registered": "注册", "registration": "登记", "capital": "资本", "paid": "实缴",
    "credit": "授信", "loan": "借款", "receivable": "应收", "payable": "应付",
    "tax": "税务", "employee": "员工", "person": "人员", "legal": "法人",
    "description": "描述", "brief": "简介", "website": "官网", "email": "邮箱",
    "phone": "电话", "scope": "范围", "business": "经营", "operating": "经营",
    "operation": "运营", "product": "产品", "service": "服务", "project": "项目",
    "supplier": "供应商", "customer": "客户", "patent": "专利", "trademark": "商标",
    "copyright": "著作权", "software": "软件", "standard": "标准",
    "qualification": "资质", "honor": "荣誉", "risk": "风险", "event": "事件",
    "court": "法院", "case": "案件", "party": "当事人", "applicant": "申请人",
    "ratio": "比例", "percent": "比例", "proportion": "比例", "change": "变动",
    "current": "本期", "latest": "最新", "first": "首次", "last": "最近", "new": "新增",
    "old": "原", "start": "开始", "end": "截止", "begin": "开始", "establish": "成立",
    "detail": "详情", "summary": "摘要", "cny": "人民币", "rmb": "人民币",
    "usd": "美元", "hkd": "港币", "value": "数值", "score": "评分", "tag": "标签",
    "path": "路径", "root": "根", "child": "子", "manager": "管理人", "org": "机构",
    "state": "国有", "owned": "持股", "guide": "引导", "target": "目标",
    "raise": "募集", "work": "运作", "form": "形式", "kind": "类型", "serial": "序号",
    "page": "页", "now": "当前", "size": "条数", "column": "字段", "order": "排序",
    "index": "索引", "dictionary": "字典", "field": "字段", "keyword": "关键词",
    "hint": "提示", "exit": "退出", "return": "回报", "multiple": "倍数",
    "invest": "投资", "money": "金额", "before": "之前", "after": "之后",
    "ipo": "上市", "mode": "方式", "owned": "持有", "abbr": "简称",
    "quota": "额度", "used": "已使用", "unused": "未使用", "sign": "签约",
    "bank": "银行", "report": "报告", "change": "变动", "volume": "数量",
    "nature": "性质", "portrait": "画像", "profile": "简介", "major": "主营",
    "constituent": "构成", "turnover": "周转", "growth": "成长", "ability": "能力",
    "debt": "偿债", "trend": "趋势", "top": "排行", "quarter": "季度",
}


def _tokenize(key: str) -> list[str]:
    text = key.replace("_", " ")
    tokens = re.findall(r"[A-Z][a-z]*|[a-z]+|\d+|[A-Z]+", text)
    return [token.lower() for token in tokens]


def _compose(key: str) -> str | None:
    """单词组合翻译：全部单词可识别才拼接，任何一个不认识就放弃（返回 None）。"""
    tokens = _tokenize(key)
    if not tokens:
        return None
    parts = []
    for token in tokens:
        if token.endswith("s") and len(token) > 2 and token[:-1] in _WORD_GLOSSARY:
            token = token[:-1]
        if token not in _WORD_GLOSSARY:
            return None
        parts.append(_WORD_GLOSSARY[token])
    return "".join(parts)


class FieldMapper:
    """按 URL + 请求上下文选择翻译表并递归翻译数据。"""

    def __init__(self) -> None:
        self._raw_enterprise, self._raw_industry = _load_config()
        self._enterprise = _build_groups(self._raw_enterprise)
        self._industry = _build_groups(self._raw_industry)
        self._url_index = self._make_url_index()
        self._auto_fields: dict[str, str] = {}
        self._load_auto()
        self._auto_lock = threading.Lock()

    # -- 自动翻译配置加载/保存 --

    def _load_auto(self) -> None:
        for path in (_AUTO_PATHS):
            try:
                if path.exists():
                    with open(path, encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        self._auto_fields.update({
                            k: str(v) for k, v in data.items() if isinstance(v, str)
                        })
            except (OSError, ValueError):
                continue

    def _persist_auto(self) -> None:
        with self._auto_lock:
            payload = json.dumps(self._auto_fields, ensure_ascii=False, indent=2)
            for path in _AUTO_PATHS:
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(payload, encoding="utf-8")
                except OSError:
                    continue

    def _auto_translate(self, key: str) -> str | None:
        """配置里没有的 key：先查词典/单词组合，命中即翻译并保存到自动翻译配置。"""
        if not isinstance(key, str) or not any(c.isalpha() for c in key):
            return None
        if not re.search(r"[a-zA-Z]", key):
            return None  # 已是中文等非英文字段
        text = _AUTO_FULL_KEYS.get(key)
        if text is None:
            text = _compose(key)
        if text is None:
            return None
        if key not in self._auto_fields:
            self._auto_fields[key] = text
            self._persist_auto()
        return text

    # -- URL 索引 --

    def _make_url_index(self) -> dict[str, list[_GroupMap]]:
        index: dict[str, list[_GroupMap]] = {}
        for raw, groups in (
            (self._raw_enterprise, self._enterprise),
            (self._raw_industry, self._industry),
        ):
            for name, gm in groups.items():
                mapping = raw.get(name) or {}
                url = mapping.get("API_url")
                if not url:
                    url = _derived_url(name)
                if not url:
                    continue
                index.setdefault(_norm_url(url).lower(), []).append(gm)
        return index

    def _lookup(self, url: str) -> list[_GroupMap]:
        """按 URL 找候选翻译表。配置里的 API_url 可能是实际路径的尾部缩写
        （如 finance/query 对应 /idis_industry/teis/v2/businessFinance/query），
        优先精确匹配，其次取最长的尾部匹配（不区分大小写）。"""
        key = _norm_url(url).lower()
        exact = self._url_index.get(key)
        if exact:
            return exact
        best: tuple[int, list[_GroupMap]] = (-1, [])
        for cfg_key, groups in self._url_index.items():
            if key.endswith(cfg_key):
                if len(cfg_key) > best[0]:
                    best = (len(cfg_key), groups)
        return best[1]

    def _select(
        self, candidates: list[_GroupMap], finance_type, tab_name: str
    ) -> _GroupMap | None:
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        if finance_type is not None:
            suffix = str(finance_type)
            for gm in candidates:
                lower = gm.name.lower()
                if lower.endswith(f"-type{suffix}") or lower.endswith(f"_{suffix}"):
                    return gm
        if tab_name:
            for gm in candidates:
                if gm.name.lower().endswith(tab_name.lower()):
                    return gm
                tail = (gm.description or "").split("-")[-1].strip()
                if tail and tail == tab_name:
                    return gm
        return candidates[0]

    def translate(self, data, url: str, finance_type=None, tab_name: str = ""):
        """按 URL 找到翻译表并递归翻译；无表时按自动翻译表全局兜底。"""
        group = self._select(self._lookup(url), finance_type, tab_name)
        return self._translate(data, group if group is not None else _GroupMap())

    def translate_keys(self, data):
        """仅按自动翻译表全局翻译（无 URL 上下文的自定义出参使用）。"""
        return self._translate(data, _GroupMap())

    def _translate(self, value, group: _GroupMap):
        if isinstance(value, dict):
            out = {}
            for key, item in value.items():
                new_key = group.fields.get(key) or self._auto_translate(key) or key
                if isinstance(item, (dict, list)):
                    sub = group.children.get(key)
                    out[new_key] = self._translate(item, sub if sub is not None else group)
                else:
                    out[new_key] = item
            return out
        if isinstance(value, list):
            return [self._translate(item, group) for item in value]
        return value


def _load_config() -> tuple[dict, dict]:
    def load(data_name: str, source_name: str) -> dict:
        for base in (_PROJECT_DATA, _REPO_MAPPING):
            for candidate in (data_name, source_name):
                path = base / candidate
                if path.exists():
                    with open(path, encoding="utf-8") as f:
                        return json.load(f)
        return {}

    return load(_ENTERPRISE_FILE, _ENTERPRISE_SOURCE), load(_INDUSTRY_FILE, _INDUSTRY_SOURCE)


_AUTO_PATHS = [
    _PROJECT_DATA / _AUTO_FILE,
    _REPO_MAPPING / _AUTO_SOURCE,
]

_mapper: FieldMapper | None = None


def translate(data, url: str, finance_type=None, tab_name: str = ""):
    """模块级入口：把网关出参 data 的 key 翻译成中文（配置/自动词典没有的 key 保留原名）。"""
    global _mapper
    if _mapper is None:
        _mapper = FieldMapper()
    return _mapper.translate(data, url, finance_type=finance_type, tab_name=tab_name)


def translate_keys(data):
    """模块级入口：仅按自动翻译表全局翻译（无 URL 上下文的自定义出参使用）。"""
    global _mapper
    if _mapper is None:
        _mapper = FieldMapper()
    return _mapper.translate_keys(data)
