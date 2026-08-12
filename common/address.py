"""地区名称转行政区划代码，本地代码表匹配，不依赖 Milvus/外部检索。"""

import json
from pathlib import Path

_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "region_codes.json"

with open(_DATA_PATH, encoding="utf-8") as _f:
    _REGION_CODES: dict = json.load(_f)

# 行政区划通名，匹配时去掉这些字方便做模糊比对（比如"北京朝阳区" vs "北京市朝阳区"）
_ADMIN_WORDS = [
    "特别行政区", "自治区", "自治州", "自治县",
    "地区", "省", "市", "区", "县", "旗", "盟", "州",
]


def _normalize(name: str) -> str:
    for word in _ADMIN_WORDS:
        name = name.replace(word, "")
    return name


def get_address(address: str = "", init_region_id: str = "", init_region_name: str = "") -> dict:
    """将地址/地区名称解析为行政区划代码（regionCode）。

    按地区筛选企业列表前必须先调用本工具获取 regionCode，禁止自行猜测代码。

    Args:
        address: 用户提供的地区名称，如"天津""北京朝阳区""浙江省杭州市"。
        init_region_id: 已知的区划代码时可直接传入，将跳过匹配直接返回。
        init_region_name: 与 init_region_id 配套的地区名称；也用于在多个候选中优先匹配。

    Returns:
        status、region_code、region_name；无法匹配时 status 为 error。
    """
    if not address:
        if init_region_name or init_region_id:
            return {
                "status": "success",
                "region_code": init_region_id,
                "region_name": init_region_name,
            }
        return {
            "status": "error",
            "error_message": "address 和 init_region_name/init_region_id 至少需要提供一个",
        }

    if address in _REGION_CODES:
        chain = _REGION_CODES[address]
    else:
        query_norm = _normalize(address)
        candidates = [
            key for key in _REGION_CODES
            if query_norm and query_norm in _normalize(key)
        ]
        if init_region_name and init_region_name in candidates:
            best = init_region_name
        elif candidates:
            best = min(candidates, key=len)
        else:
            best = None

        if best is None:
            return {
                "status": "error",
                "error_message": f"未找到匹配的地区: {address}",
            }
        chain = _REGION_CODES[best]

    if not chain:
        return {
            "status": "success",
            "region_code": "",
            "region_name": "全国",
            "note": "不限地区",
        }

    last = chain[-1]
    breadcrumb = _breadcrumb(chain)
    return {
        "status": "success",
        "region_code": str(last["code"]),
        "region_name": last["name"],
        **breadcrumb,
    }


def _breadcrumb(chain: list[dict]) -> dict:
    """把匹配到的层级链拆成 province/city/district 三个名称字段——很多接口
    （比如区域的融资类接口）不光要 regionCode，还要单独传省/市/区名称字符串。

    level 1=省/自治区，level 2=市（直辖市自己就是 level 2，没有单独的省层级），
    level 3=区/县。直辖市没有 level 1，这时候 province 就等于 city。
    """
    by_level = {item["level"]: item["name"] for item in chain}
    # 直辖市既是省级也是市级：单独查"北京市"时数据是 level=2；查"北京市朝阳区"
    # 这种带区县的链路里，北京市又变成 level=1、没有单独的 level=2 条目。
    # 用互相兜底的方式，两种情况都能拿到正确的 province/city。
    province = by_level.get(1) or by_level.get(2, "")
    city = by_level.get(2) or by_level.get(1, "")
    district = by_level.get(3, "")
    return {"province_name": province, "city_name": city, "district_name": district}
