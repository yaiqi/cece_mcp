"""MCP 出参整形：信封清理、ID 剔除、键翻译与按工具功能筛选。

管线（register_tools 统一执行）：
1. 顶层去掉英文信封字段（status/data），递归剔除 ID 类字段；
2. 英文 key 翻译成中文（api文件/中文映射 配置 + 自动翻译词典）；
3. 按工具功能描述筛选字段（TOOL_SHAPERS 注册表），每个工具只返回其功能
   描述范围内的字段。
"""

import re

# ID 类字段模式：xxxId / xxxID / xxx_id（大小写敏感的 Id/ID 后缀，
# 避免误伤 valid/paid 这类普通单词，也保留 standalone id 字段供图节点使用）
_ID_KEY_PATTERN = re.compile(r"(Id$|ID$|_id$)")

_ENVELOPE_STRIP_KEYS = ("status", "data")


def _is_scalar(value) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _clean_output(result, _top: bool = True):
    """信封清理 + ID 字段递归剔除（顶层 status/data 移除，嵌套业务字段保留）。"""
    if isinstance(result, dict):
        out = {}
        for key, value in result.items():
            if _top and key in _ENVELOPE_STRIP_KEYS:
                continue
            if _ID_KEY_PATTERN.search(key):
                continue
            out[key] = _clean_output(value, _top=False)
        return out
    if isinstance(result, list):
        return [_clean_output(item, _top=False) for item in result]
    return result


def _pick(data: dict, pairs) -> dict:
    """按 (源键, 目标键) 列表挑选字段（源键存在才保留）。"""
    out = {}
    for source, target in pairs:
        if isinstance(source, (tuple, list)):
            for candidate in source:
                if data.get(candidate) is not None:
                    out[target] = data[candidate]
                    break
        elif data.get(source) is not None:
            out[target] = data[source]
    return out


def _list_items(data) -> tuple[list, dict]:
    """从已翻译的响应里取列表与总数（兼容多种包装键）。"""
    if isinstance(data, list):
        return data, {}
    if not isinstance(data, dict):
        return [], {}
    items = None
    for key in ("列表", "部分具体数据", "部分数据信息", "部分融资信息",
                "部分对外投资信息", "部分授信额度信息", "部分债券持有人信息",
                "部分数据详情", "数据", "部分记录"):
        if isinstance(data.get(key), list):
            items = data[key]
            break
    if items is None and isinstance(data.get("list"), list):
        items = data["list"]
    total = {}
    for key in ("数据总量", "总数", "总次数", "创投融资总次数", "债券融资总次数",
                "银行借款总次数", "应收账款融资总次数", "租赁融资总次数",
                "信托融资总次数", "股票融资总次数", "其他融资总次数",
                "对外投资总次数", "授信额度总次数", "债券持有人总数"):
        if data.get(key) is not None:
            total["总数"] = data[key]
            break
    return items or [], total


# ---------------------------------------------------------------------------
# 各工具字段筛选器（按工具功能描述挑选字段）
# ---------------------------------------------------------------------------

_TAG_CATEGORIES = {
    # 每个类目标签对应的 tagInfo 列表键（含原始英文键与自动翻译后的中文键）
    "资本市场标签": ("financeTagList", "融资标签列表"),
    "科技标签": ("technologyTagList", "greenTagList", "科技标签列表", "绿色标签列表"),
    "榜单荣誉标签": ("rankingTagList", "topTagList", "榜单标签列表", "荣誉标签列表"),
    "标准制定标签": ("standardTagList", "stdTagList", "标准标签列表"),
    "风险标签": ("riskTagList", "风险标签列表"),
}


def _extract_tag_names(value) -> list:
    names = []
    for item in value or []:
        if isinstance(item, dict):
            text = item.get("标签名称") or item.get("名称") or item.get("tagName")
            if text:
                names.append(text)
        elif item:
            names.append(item)
    return names


def _shape_enterprise_tags(data):
    if not isinstance(data, dict):
        return data
    tag_info = data.get("标签信息") or {}
    out = _pick(data, [("企业名称", "企业名称"), ("统一社会信用代码", "统一社会信用代码")])
    for category, keys in _TAG_CATEGORIES.items():
        names: list = []
        for key in keys:
            if isinstance(tag_info.get(key), list):
                names.extend(_extract_tag_names(tag_info[key]))
        out[category] = names
    # 产业分类（从 /cmp/detail/basic 获取，经 auto-translate 后为中文键）
    cls = data.get("标准产业名称") or data.get("productClsNames")
    if isinstance(cls, list) and cls:
        out["所属新华产业"] = [str(n) for n in cls if n]
    nsei = data.get("国战新产业名称") or data.get("nseiClsNames")
    if isinstance(nsei, list) and nsei:
        out["所属国战新产业"] = [str(n) for n in nsei if n]
    ind = data.get("行业代码中文") or data.get("industrycoName")
    if ind:
        out["所属国标产业"] = [str(ind) if isinstance(ind, str) else str(ind)]
    return out


_BASIC_FIELDS = [
    ("企业名称", "企业名称"), ("统一社会信用代码", "统一社会信用代码"),
    ("经营状态", "经营状态"), ("企业类型", "企业类型"), ("企业规模", "企业规模"),
    ("组织机构代码", "组织机构代码"), ("工商注册号", "工商注册号"),
    ("纳税人识别号", "纳税人识别号"), ("纳税人资格", "纳税人资格"),
    ("登记机关", "登记机关"), ("注册地址", "注册地址"), ("经营地址", "经营地址"),
    ("经营范围", "经营范围"), ("法人", "法人"), ("注册资本", "注册资本"),
    ("注册资本单位", "注册资本单位"), ("实缴资本", "实缴资本"),
    ("成立日期", "成立日期"), ("经营期限自", "经营期限自"), ("经营期限至", "经营期限至"),
    ("核准日期", "核准日期"), ("注销日期", "注销日期"), ("吊销日期", "吊销日期"),
    ("省", "所属省"), ("市", "所属市"), ("区县", "所属区县"),
    ("联系电话", "联系电话"), ("公司邮箱", "公司邮箱"), ("公司网站", "公司网站"),
    ("企业简介", "企业简介"), ("人员规模", "人员规模"), ("养老保险参保人数", "养老保险参保人数"),
    ("行业代码中文", "行业代码中文"), ("行业代码", "行业代码"),
    ("企业英文名", "企业英文名"), ("企业曾用名", "企业曾用名"),
    ("所属园区名称", "所属园区名称"),
]


def _shape_enterprise_basic(data):
    if not isinstance(data, dict):
        return data
    return _pick(data, _BASIC_FIELDS)


_SHAREHOLDER_FIELDS = [
    (("股东名称",), "股东名称"), ("股东类型", "股东类型"), ("持股类型", "持股类型"),
    ("持股比例", "持股比例"), (("持股数（万股）", "持股数"), "持股数（万股）"),
    (("较上期变动数（万股）", "较上期变动数"), "较上期变动数（万股）"),
    ("报告日期", "报告日期"), ("认缴出资额", "认缴出资额"),
    ("认缴出资额单位", "认缴出资额单位"), ("认缴出资日期", "认缴出资日期"),
    ("股东企业状态", "股东企业状态"),
]


def _shape_shareholders(data):
    if not isinstance(data, dict):
        return data
    out = {}
    for group in ("上市公告股东", "工商登记股东"):
        value = data.get(group)
        if isinstance(value, list):
            out[group] = [_pick(item, _SHAREHOLDER_FIELDS) for item in value if isinstance(item, dict)]
    return out or data


def _shape_management(data):
    if not isinstance(data, dict):
        return data
    fields = [
        ("姓名", "姓名"), ("性别", "性别"), ("学历", "学历"),
        (("职务", "position", "所在职务"), "所在职务"),
        ("原职务", "原职务"), ("持股比例", "持股比例"), ("报酬", "报酬"),
        ("变更日期", "变更日期"), ("任职企业名称", "任职企业"),
        (("任职企业注册资本", "注册资本", "registCapi", "registCapiUnit"), "注册资本"),
        ("任职企业成立时间", "任职企业成立时间"),
        (("任职企业法定代表人", "法定代表人", "operName"), "任职企业法定代表人"),
        ("任职企业状态", "任职企业状态"),
        ("关联企业", "关联企业"),
    ]
    out = {}
    for group in ("上市公告主要人员", "工商登记主要人员", "董监高投资任职"):
        value = data.get(group)
        if isinstance(value, list):
            out[group] = [_pick(item, fields) for item in value if isinstance(item, dict)]
    return out or data


def _names(value) -> list | None:
    """名单类字段压缩成名称列表（dict 元素取名称类字段，属于字段筛选的一部分）。"""
    if not isinstance(value, list):
        return None
    names = []
    for item in value:
        if isinstance(item, str):
            names.append(item)
            continue
        if isinstance(item, dict):
            text = None
            for key in ("投资企业名称", "融资企业名称", "企业名称", "名称", "姓名",
                        "银行名称", "担保人名称", "基金名称", "标签名称", "公司",
                        "company", "name", "companyName"):
                candidate = item.get(key)
                if isinstance(candidate, str) and candidate:
                    text = candidate
                    break
            names.append(text if text else str(item))
        else:
            names.append(str(item))
    return names


def _shape_finance_events(data):
    items, total = _list_items(data)
    if not items:
        return data
    fields = [
        ("融资方", "融资方"), ("投资方", "投资方"), ("担保人", "担保人"),
        ("融资轮次", "融资轮次"), ("融资类型", "融资类型"), ("融资类型细分", "融资类型细分"),
        ("融资金额（万元 人民币）", "融资金额（万元）"), ("金额", "金额"), ("单位", "单位"),
        ("融资日期", "融资日期"), ("发行日期", "发行日期"), ("披露日期", "披露日期"),
        ("起始日期", "起始日期"), ("截止日期", "截止日期"), ("到期日期", "到期日期"),
        ("股票简称", "股票简称"), ("股票代码", "股票代码"), ("发行价格（元）", "发行价格（元）"),
        ("发行量（万股）", "发行量（万股）"), ("债券简称", "债券简称"), ("债券代码", "债券代码"),
        ("票面利率（%）", "票面利率（%）"), ("债券期限（年）", "债券期限（年）"),
        ("债券类型", "债券类型"), ("债券评级", "债券评级"), ("持股比例", "持股比例"),
        ("登记状态", "登记状态"), ("质权人/受让人", "质权人/受让人"),
        ("质让/转让财产价值（万元 人民币）", "质让/转让财产价值（万元）"),
        ("租赁类型", "租赁类型"), ("出租人", "出租人"), ("信托公司", "信托公司"),
        ("银行", "银行"), ("利率（%）", "利率（%）"), ("利率", "利率"),
        ("消息来源", "消息来源"), ("省", "所属省"), ("市", "所属市"), ("区县", "所属区县"),
        ("状态", "状态"), ("企业名称", "企业名称"),
    ]
    shaped = [_pick(item, fields) for item in items if isinstance(item, dict)]
    for item in shaped:
        for key in ("融资方", "投资方", "担保人", "质权人/受让人", "出租人", "信托公司", "银行"):
            names = _names(item.get(key))
            if names is not None:
                item[key] = names
    result = {}
    if total:
        result.update(total)
    result["列表"] = shaped
    return result


def _shape_financing_companies(data):
    items, total = _list_items(data)
    if not items:
        return data
    fields = [
        ("融资方", "融资方"), ("投资方", "投资方"), ("融资轮次", "融资轮次"),
        ("融资金额（万元 人民币）", "融资金额（万元）"), ("融资日期", "融资日期"),
        ("投资持股比例（%）", "投资持股比例"),
        (("所属省", "省"), "所属省"), (("所属市", "市"), "所属市"),
        (("所属区县", "区县"), "所属区"),
        ("法人", "法人"), ("注册资本", "注册资本"), ("成立日期", "成立日期"),
        ("成立年限", "成立年限"), ("企业简介", "企业简介"), ("官网", "官网"),
        ("实控人", "实控人"),
    ]
    shaped = []
    for item in items:
        if not isinstance(item, dict):
            continue
        out = _pick(item, fields)
        for key in ("融资方", "投资方"):
            names = _names(out.get(key))
            if names is not None:
                out[key] = names
        for key in ("新华产业", "国战新产业", "国标产业"):
            if item.get(key) is not None:
                out[key] = item[key]
        shaped.append(out)
    result = {}
    if total:
        result.update(total)
    result["列表"] = shaped
    return result


def _shape_fund_list(data):
    items, total = _list_items(data)
    if not items:
        return data
    fields = [
        ("基金名称", "基金名称"), ("运作状态", "运作状态"), ("基金类型", "基金类型"),
        ("注册资本", "注册资本"), ("实缴资本", "实缴资本"), ("国企持股比例", "国企持股比例"),
        ("管理人名称", "基金管理人"), ("省", "所属省"), ("市", "所属市"), ("区县", "所属区县"),
        ("成立日期", "成立日期"),
    ]
    shaped = [_pick(item, fields) for item in items if isinstance(item, dict)]
    result = {"总数": total.get("总数")} if total else {}
    result["列表"] = shaped
    return result


def _shape_fund_investment(data):
    items, total = _list_items(data)
    if not items:
        return data
    fields = [
        ("投资日期", "投资日期"), ("企业名称", "被投企业"),
        ("参投基金列表", "参投产业基金"), ("轮次名称", "投资轮次"),
        ("被投年限", "被投年限"), ("省", "所属省"), ("市", "所属市"), ("区县", "所属区县"),
        ("企业状态", "经营状态"),
        (("投资方式", "investmentMode"), "投资方式"),
        (("投资金额", "investmentAmount"), "投资金额"),
        (("持股比例", "shareRatio"), "持股比例"),
        ("产业信息", "产业信息"),  # 保留用于提取产业分类，后续替换为嵌套结构
    ]
    shaped = [_pick(item, fields) for item in items if isinstance(item, dict)]
    for item in shaped:
        names = _names(item.get("参投产业基金"))
        if names is not None:
            item["参投产业基金"] = names
        industry_info = item.pop("产业信息", None)
        if isinstance(industry_info, dict):
            industry_out = {}
            for src_key, label in [
                ("精选产业分类", "新华产业链"),
                ("战新产业分类", "国战新产业链"),
                ("国标行业分类", "国标产业链"),
            ]:
                industry_list = industry_info.get(src_key)
                if isinstance(industry_list, list):
                    names = [
                        i.get("产业名称") or i.get("industryName") or ""
                        for i in industry_list if isinstance(i, dict)
                    ]
                    if names:
                        industry_out[label] = names
            if industry_out:
                item["所属产业"] = industry_out
    result = {"总数": total.get("总数")} if total else {}
    result["列表"] = shaped
    return result


def _shape_fund_exit(data):
    items, total = _list_items(data)
    if not items:
        return data
    fields = [
        ("退出日期", "退出日期"), ("企业名称", "被投企业"), ("基金名称", "退出基金"),
        ("退出方式", "退出方式"), ("交易场所", "交易场所"),
        ("账面回报倍数", "账面回报倍数"), (("内部收益率", "returnRate"), "内部收益率(%)"),
        (("投资金额", "investMoney"), "总投资金额"),
        (("退出金额", "exitMoney"), "退出金额"),
        (("上市前持股", "上市前持股数", "beforeIpoStock"), "上市前持股数"),
        (("上市后持股", "上市后持股数", "afterIpoStock"), "上市后持股数"),
        (("上市前持股比例(%)", "上市前持股比例", "上市前规模", "beforeIpoScale"), "上市前持股比例(%)"),
        (("上市后持股比例(%)", "上市后持股比例", "上市后规模", "afterIpoScale"), "上市后持股比例(%)"),
        (("投资方式", "investmentMode"), "投资方式"),
        (("基金编号", "fundNo"), "基金编号"),
        (("管理类型", "管理人类型", "managerType"), "管理类型"),
        (("备案日期", "putOnRecordDate"), "备案日期"),
        (("注册资本", "registeredCapital", "regcap"), "注册资本"),
        (("简介", "基金简介"), "简介"),
        (("注册地址", "registeredAddress"), "注册地址"),
    ]
    shaped = [_pick(item, fields) for item in items if isinstance(item, dict)]
    result = {"总数": total.get("总数")} if total else {}
    result["列表"] = shaped
    return result


def _shape_fund_detail_basic(data):
    if not isinstance(data, dict):
        return data
    return _pick(data, [
        ("基金名称", "基金名称"), ("基金类型", "基金类型"), ("组织形式", "组织形式"),
        ("管理人名称", "基金管理人"),
        (("管理类型", "管理人类型", "managerType"), "管理类型"),
        ("委托人名称", "委托人"), ("成立日期", "成立日期"), ("资本类型", "资本类型"),
        ("目标规模", "目标规模"), ("募集状态", "募集状态"), ("运作状态", "运作状态"),
        ("国企持股比例", "国企持股比例"), ("是否引导基金", "是否引导基金"),
        ("引导基金级别", "引导基金级别"), ("是否母基金", "是否母基金"),
        (("基金编号", "fundNo"), "基金编号"),
        (("备案日期", "putOnRecordDate"), "备案日期"),
        (("注册资本", "registeredCapital"), "注册资本"),
        (("基金简介", "fundIntro", "简介", "description", "描述"), "简介"),
        (("注册地址", "address", "registeredAddress", "fundAddress", "地址", "经营地址"), "注册地址"),
        ("协会链接", "协会链接"),
    ])


def _shape_fund_investor(data):
    items, total = _list_items(data)
    if not items:
        return data
    fields = [
        ("出资人名称", "出资人名称"), ("出资人类型", "出资人类型"),
        ("省", "所属省"), ("市", "所属市"), ("区县", "所属区县"),
        ("是否国企", "是否国企"), ("持股比例", "持股比例"), ("认缴出资额", "认缴出资额"),
    ]
    shaped = [_pick(item, fields) for item in items if isinstance(item, dict)]
    result = {"总数": total.get("总数")} if total else {}
    result["列表"] = shaped
    return result


def _shape_outbound_investment(data):
    items, total = _list_items(data)
    if not items:
        return data
    fields = [
        ("企业名称", "投资对象"), ("持股比例（%）", "持股比例"), ("注册资本", "注册资本"),
        ("法定代表人", "法定代表人"), ("成立日期", "成立日期"), ("企业状态", "企业状态"),
    ]
    shaped = [_pick(item, fields) for item in items if isinstance(item, dict)]
    result = {"总数": total.get("总数")} if total else {}
    result["列表"] = shaped
    return result


def _shape_bond_holder(data):
    items, total = _list_items(data)
    if not items:
        return data
    fields = [
        ("报告期", "报告期"), ("债券简称", "债券简称"), ("债券代码", "债券代码"),
        ("持有人", "持有人名称"), ("持仓市值（万元）", "持仓市值（万元）"),
        ("较上期变化（万元）", "较上期变动（万元）"), ("变化类型", "变化类型"),
        ("持仓数量（张）", "持仓数量（张）"), ("管理人", "管理人"),
    ]
    shaped = [_pick(item, fields) for item in items if isinstance(item, dict)]
    result = {"总数": total.get("总数")} if total else {}
    result["列表"] = shaped
    return result


def _shape_credit_line(data):
    items, total = _list_items(data)
    if not items:
        return data
    fields = [
        ("披露日期", "披露日期"), ("截止日期", "截止日期"),
        ("授信额度（万元 人民币）", "授信额度（万元）"), ("已使用额度（万元 人民币）", "已使用额度（万元）"),
        ("未使用额度（万元 人民币）", "未使用额度（万元）"), ("授信家数", "授信家数"),
        ("授信机构", "授信机构"),
    ]
    shaped = [_pick(item, fields) for item in items if isinstance(item, dict)]
    result = {"总数": total.get("总数")} if total else {}
    result["列表"] = shaped
    return result


def _shape_tender(data):
    if not isinstance(data, dict):
        return data
    fields = [
        ("招标公告日期", "公告日期"), ("公告类型", "公告类型"), ("项目地区", "项目地区"),
        ("项目名称", "项目名称"), ("项目类型", "项目类型"),
        ("招标方企业名称", "招标方企业名称"), ("招标方统一社会信用代码", "招标方统一社会信用代码"),
        ("中标方企业名称", "中标方企业名称"), ("中标方统一社会信用代码", "中标方统一社会信用代码"),
        ("招标金额", "招标金额"), ("中标金额", "中标金额"), ("采购产品", "采购产品"),
        ("区域", "区域"),
    ]
    out = {}
    for group in ("招标项目", "投标项目"):
        value = data.get(group)
        if isinstance(value, dict):
            items = _list_items(value)[0]
            if items:
                out[group] = [_pick(item, fields) for item in items if isinstance(item, dict)]
    return out or data


def _flatten_graph_nodes(nodes, level, max_level=4):
    if level > max_level:
        return []
    result = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        # 跳过第二层节点
        if level == 2:
            continue
        name = node.get("名称") or node.get("name") or ""
        child_nodes = node.get("子项") or node.get("children") or []
        related = []
        for c in child_nodes:
            if not isinstance(c, dict):
                continue
            obj = {}
            for k in ("类型", "type", "名称", "name", "id"):
                if c.get(k) is not None:
                    obj[k] = c[k]
            if obj:
                related.append(obj)
        entry = {
            "关系名称": name,
            "关联数量": len(child_nodes),
            "关联对象": related,
        }
        result.append(entry)
        if child_nodes:
            result.extend(_flatten_graph_nodes(child_nodes, level + 1, max_level))
    return result


def _shape_graph(data):
    if not isinstance(data, dict):
        return data
    merged = []
    for side_key, side_label in [("左侧", "左侧"), ("右侧", "右侧")]:
        side_data = data.get(side_key)
        if not isinstance(side_data, dict):
            continue
        children = side_data.get("子项") or side_data.get("children") or []
        if not isinstance(children, list):
            continue
        merged.extend(_flatten_graph_nodes(children, level=1))
    # 过滤掉第二层节点
    return {"关系列表": merged}


def _shape_person_list(data):
    items, total = _list_items(data)
    if not items:
        return data
    CAT_MAP = {"1": "法定代表人", "2": "实际控制人", "3": "受益所有人", "4": "股东", "5": "高管"}
    shaped = []
    for item in items:
        if not isinstance(item, dict):
            continue
        out = {}
        name = item.get("企业名称") or ""
        if name:
            out["企业名称"] = name
        pct = item.get("shareholdingRatioStr") or ""
        if pct:
            out["持股比例"] = pct
        cats = item.get("公告类型") or []
        if isinstance(cats, list):
            labels = [CAT_MAP.get(c, c) for c in cats if c]
            if labels:
                out["担任角色"] = "，".join(labels)
        reg = item.get("注册资本") or ""
        if reg:
            out["注册资本"] = reg
        area_parts = []
        for k in ("省", "市", "区县"):
            v = item.get(k)
            if v:
                area_parts.append(v)
        if area_parts:
            out["所属地区"] = "".join(area_parts)
        ind = item.get("行业代码中文") or ""
        if ind:
            out["国标行业"] = ind
        st = item.get("状态") or ""
        if st:
            out["经营状态"] = st
        shaped.append(out)
    result = {"总数": total.get("总数")} if total else {}
    result["列表"] = shaped
    return result


def _shape_person_office(data):
    items, total = _list_items(data)
    if not items:
        return data
    shaped = []
    for item in items:
        if not isinstance(item, dict):
            continue
        out = {}
        name = item.get("企业名称") or ""
        if name:
            out["任职企业"] = name
        pos = item.get("职务") or ""
        if pos:
            out["职务"] = pos
        # 上任时间 ~ 结束时间
        in_d = item.get("inDate") or ""
        off_d = item.get("offDate") or ""
        if in_d or off_d:
            out["上任时间"] = f"{in_d or '?'} ~ {off_d or '?'}"
        person = item.get("名称") or ""
        if person:
            out["法定代表人"] = person
        pno = item.get("人物编号") or ""
        if pno:
            out["法定代表人编号"] = pno
        reg = item.get("注册资本") or ""
        if reg:
            out["注册资本"] = reg
        area_parts = []
        for k in ("省", "市", "区县"):
            v = item.get(k)
            if v:
                area_parts.append(v)
        if area_parts:
            out["所属地区"] = "".join(area_parts)
        ind = item.get("行业代码中文") or ""
        if ind:
            out["国标行业"] = ind
        st = item.get("状态") or ""
        if st:
            out["经营状态"] = st
        shaped.append(out)
    result = {"总数": total.get("总数")} if total else {}
    result["列表"] = shaped
    return result


def _shape_person_beneficial(data):
    items, total = _list_items(data)
    if not items:
        return data
    shaped = []
    for item in items:
        if not isinstance(item, dict):
            continue
        out = {}
        name = item.get("企业名称") or ""
        if name:
            out["企业名称"] = name
        bc = item.get("beneficialClass") or ""
        if bc:
            out["收益类型"] = bc
        bp = item.get("beneficialPercentStr") or ""
        if bp:
            out["收益股份"] = bp
        person = item.get("名称") or ""
        if person:
            out["法定代表人"] = person
        pno = item.get("人物编号") or ""
        if pno:
            out["法定代表人编号"] = pno
        reg = item.get("注册资本") or ""
        if reg:
            out["注册资本"] = reg
        area_parts = []
        for k in ("省", "市", "区县"):
            v = item.get(k)
            if v:
                area_parts.append(v)
        if area_parts:
            out["所属地区"] = "".join(area_parts)
        ind = item.get("行业代码中文") or ""
        if ind:
            out["国标行业"] = ind
        st = item.get("状态") or ""
        if st:
            out["经营状态"] = st
        shaped.append(out)
    result = {"总数": total.get("总数")} if total else {}
    result["列表"] = shaped
    return result


def _shape_person_controller(data):
    items, total = _list_items(data)
    if not items:
        return data
    shaped = []
    for item in items:
        if not isinstance(item, dict):
            continue
        out = {}
        name = item.get("企业名称") or ""
        if name:
            out["企业名称"] = name
        pct = item.get("shareholdingRatioStr") or ""
        if pct:
            out["持股比例"] = pct
        bp = item.get("beneficialPercentStr") or ""
        if bp:
            out["收益股份"] = bp
        person = item.get("名称") or ""
        if person:
            out["法定代表人"] = person
        pno = item.get("人物编号") or ""
        if pno:
            out["法定代表人编号"] = pno
        reg = item.get("注册资本") or ""
        if reg:
            out["注册资本"] = reg
        area_parts = []
        for k in ("省", "市", "区县"):
            v = item.get(k)
            if v:
                area_parts.append(v)
        if area_parts:
            out["所属地区"] = "".join(area_parts)
        ind = item.get("行业代码中文") or ""
        if ind:
            out["国标行业"] = ind
        st = item.get("状态") or ""
        if st:
            out["经营状态"] = st
        shaped.append(out)
    result = {"总数": total.get("总数")} if total else {}
    result["列表"] = shaped
    return result


def _shape_person_holder(data):
    items, total = _list_items(data)
    if not items:
        return data
    shaped = []
    for item in items:
        if not isinstance(item, dict):
            continue
        out = {}
        # 企业名称
        name = item.get("企业名称") or item.get("持股企业") or ""
        if name:
            out["企业名称"] = name

        # 持股比例 + %
        pct = item.get("持股比例")
        if pct is not None:
            out["持股比例"] = f"{pct}%"

        # 最短层级 + 级
        level = item.get("最短层级")
        if level is not None:
            out["最短层级"] = f"{level}级"

        # 注册资本（直接取 registeredCapital）
        regcap = item.get("registeredCapital") or item.get("注册资本") or ""
        if regcap:
            out["注册资本"] = str(regcap)

        # 法定代表人
        legal = item.get("法定代表人") or item.get("法人") or ""
        if legal:
            out["法定代表人"] = legal

        # 成立日期
        esdate = item.get("成立日期") or ""
        if esdate:
            out["成立日期"] = esdate

        # 所属地区
        parts = []
        for k in ("省", "市", "区县"):
            v = item.get(k)
            if v:
                parts.append(v)
        if parts:
            out["所属地区"] = "".join(parts)

        # 经营状态
        st = item.get("经营状态") or item.get("状态") or ""
        if st:
            out["经营状态"] = st

        # 持股路径（已由函数预处理为字符串）
        path_str = item.get("持股路径") or ""
        if path_str:
            out["持股路径"] = path_str

        shaped.append(out)
    result = {"总数": total.get("总数")} if total else {}
    result["列表"] = shaped
    return result


def _shape_person_union(data):
    items, total = _list_items(data)
    if not items:
        return data
    shaped = []
    for item in items:
        if not isinstance(item, dict):
            continue
        out = {}
        # 企业名称
        name = item.get("企业名称") or item.get("companyName") or ""
        if name:
            out["关联企业名称"] = name
        # 关联类型（已由函数预处理为字符串）
        utype = item.get("unionCategorys") or item.get("关联类型") or ""
        if utype:
            out["关联类型"] = utype
        # 注册资本
        reg = item.get("注册资本") or item.get("registCapiStr") or ""
        if reg:
            out["注册资本"] = reg
        # 所属地区
        parts = []
        for k in ("省", "市", "区县"):
            v = item.get(k)
            if v:
                parts.append(v)
        if parts:
            out["所属地区"] = "".join(parts)
        # 国标行业
        ind = item.get("行业代码中文") or item.get("industrycoName") or ""
        if ind:
            out["国标行业"] = ind
        # 经营状态
        st = item.get("状态") or item.get("status") or item.get("经营状态") or ""
        if st:
            out["经营状态"] = st
        shaped.append(out)
    result = {"总数": total.get("总数")} if total else {}
    result["列表"] = shaped
    return result


_PERSON_PARTNER_FIELDS = [
    ("合作伙伴姓名", "合作伙伴姓名"), ("代表合作企业", "代表合作企业"),
    ("正在合作次数", "正在合作次数"), ("合作详情", "合作详情"),
    ("合作详情列表", "合作详情列表"),
]


def _shape_person_partner(data):
    if not isinstance(data, dict):
        return data
    total_count = data.get("总数") or data.get("数据总量") or 0
    items = data.get("数据") or data.get("列表") or []
    if not items:
        return {"合作伙伴总数": total_count, "部分合作伙伴信息": []}
    shaped = []
    for item in items:
        if not isinstance(item, dict):
            continue
        out = {}
        name_val = item.get("name") or item.get("名称") or ""
        no_val = item.get("no") or item.get("编号") or ""
        company_val = item.get("companyName") or item.get("企业名称") or ""
        amount_val = item.get("amount") or item.get("金额") or 0
        out["合作伙伴姓名"] = name_val
        out["编号"] = no_val
        out["代表性合作企业"] = company_val
        out["正在合作次数"] = amount_val

        detail_list = item.get("detailTop10") or item.get("detailTop10") or []
        if detail_list:
            out["合作详情（Top10）"] = detail_list
        shaped.append(out)

    return {"合作伙伴总数": total_count, "部分合作伙伴信息": shaped}


def _shape_talent_basic(data):
    if not isinstance(data, dict):
        return data
    return _pick(data, [
        ("人物简介", "人物简介"), ("科技人才信息", "科技人才信息"),
        ("名称", "姓名"), ("所属集团", "所属集团"), ("性别", "性别"),
        ("学历", "学历"), ("出生年份", "出生年份"),
    ])


def _shape_industry_tree(data):
    if not isinstance(data, dict):
        return data
    match_list = data.get("匹配列表")
    if not isinstance(match_list, list):
        return data
    nodes = []
    for node in match_list:
        if not isinstance(node, dict):
            continue
        nodes.append(_pick(node, [
            ("代码", "code"), ("名称", "name"), ("chain", "chain"),
            ("类型", "type"),
        ]))
    return {"匹配列表": nodes}


def _shape_region_tree(data):
    if not isinstance(data, dict):
        return data
    return _pick(data, [("树", "树")])


def _shape_enterprise_name(data):
    if not isinstance(data, dict):
        return data
    return _pick(data, [("企业名称", "企业名称")])


def _shape_person_search(data):
    """search_person_by_name 出参整形：拍平，无二层子结构。"""
    if not isinstance(data, dict):
        return data
    match_list = data.get("匹配列表")
    if not isinstance(match_list, list):
        return data
    nodes = []
    for node in match_list:
        if not isinstance(node, dict):
            continue
        out = {}
        # 编号 / 名称
        out["编号"] = node.get("no") or node.get("编号") or ""
        out["名称"] = node.get("name") or node.get("名称") or ""
        # 关联企业总数量 / 合作伙伴数量
        out["关联企业总数量"] = node.get("companyAmount") or node.get("companyAmount") or 0
        out["合作伙伴数量"] = node.get("partnerAmount") or node.get("partnerAmount") or 0

        # 角色数量拍平到顶层
        roles = node.get("roleBreakdown") or node.get("角色数量分布") or {}
        if isinstance(roles, dict):
            for k, v in roles.items():
                out[k] = v

        # 企业主要区域分布拼接
        regions = node.get("regionDistribution") or node.get("区域分布") or []
        parts = []
        if isinstance(regions, list):
            for item in regions:
                if not isinstance(item, dict):
                    continue
                rname = item.get("name") or item.get("名称") or ""
                rcount = item.get("amount") or item.get("金额") or item.get("关联企业数") or 0
                rrep = item.get("companyName") or item.get("representative") or item.get("企业名称") or ""
                if rname:
                    parts.append(f"{rname}({rcount}家）：{rrep}等")
        if parts:
            out["企业主要区域分布"] = "\n".join(parts)

        nodes.append(out)

    total = data.get("total") or data.get("总数") or 0
    return {"匹配列表": nodes, "总数": total}


def _shape_competitive(data):
    if not isinstance(data, dict):
        return data
    return _pick(data, [("本公司", "本公司"), ("竞品对比列表", "竞品对比列表"), ("相似类型", "相似类型")])


# 工具名 -> 整形函数
TOOL_SHAPERS = {
    "get_enterprise_tags": _shape_enterprise_tags,
    "get_enterprise_basic": _shape_enterprise_basic,
    "get_enterprise_shareholders": _shape_shareholders,
    "get_enterprise_management": _shape_management,
    "get_enterprise_VCPE_financing": _shape_finance_events,
    "get_enterprise_stock_financing": _shape_finance_events,
    "get_enterprise_bond_financing": _shape_finance_events,
    "get_enterprise_bank_financing": _shape_finance_events,
    "get_enterprise_receivables_financing": _shape_finance_events,
    "get_enterprise_leasing_financing": _shape_finance_events,
    "get_enterprise_trust_financing": _shape_finance_events,
    "get_enterprise_bondHolder": _shape_bond_holder,
    "get_enterprise_credit_financing": _shape_credit_line,
    "get_enterprise_outbound_investment": _shape_outbound_investment,
    "get_company_graphy": _shape_graph,
    "get_businessFinance_graphy": _shape_graph,
    "get_query_winTenderer_tenderee": _shape_tender,
    "search_financing_companies": _shape_financing_companies,
    "get_industryFund_list": _shape_fund_list,
    "search_industryFund_investmen_list": _shape_fund_investment,
    "get_industryFund_exit_list": _shape_fund_exit,
    "get_fund_detail_basic": _shape_fund_detail_basic,
    "get_fund_detail_investor_list": _shape_fund_investor,
    "get_fund_detail_investment_list": _shape_fund_investment,
    "get_fund_detail_exit_list": _shape_fund_exit,
    "get_query_competitive_Finance": _shape_competitive,
    "get_person_legal": _shape_person_list,
    "get_person_office": _shape_person_office,
    "get_person_beneficial": _shape_person_beneficial,
    "get_person_controller": _shape_person_controller,
    "get_person_holder": _shape_person_holder,
    "get_person_union": _shape_person_union,
    "get_person_partner": _shape_person_partner,
    "get_talent_basic": _shape_talent_basic,
    "get_industry_tree": _shape_industry_tree,
    "get_region_tree": _shape_region_tree,
    "search_enterprise_by_name": _shape_enterprise_name,
    "search_person_by_name": _shape_person_search,
}


def shape_tool_output(result, tool_name: str):
    """MCP 出参整形管线：信封清理 -> ID 剔除 -> 键翻译 -> 字段筛选。"""
    from common.field_mapper import translate_keys

    cleaned = translate_keys(_clean_output(result))
    if not isinstance(cleaned, dict):
        return cleaned
    payload = cleaned.get("数据")
    if payload is not None:
        shaper = TOOL_SHAPERS.get(tool_name)
        if shaper is not None:
            cleaned["数据"] = shaper(payload)
    return cleaned
