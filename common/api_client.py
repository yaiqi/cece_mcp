"""共享网关（xhzjds.cnfic.com.cn）的 HTTP 客户端。

鉴权是 3 个固定值：Authorization（JWT）、x-Sec、x-Chl，从这个 MCP 自己的
.env 读，过期后需要去对应系统重新获取更新。

用一个模块级复用的 AsyncClient（连接池），不要每次调用都新建一个，
并发量上来之后新建连接的开销会很明显。

出参中文翻译：api_get/api_post 会把本次请求的路径、financeType、tabName
等上下文随响应一起带回，unwrap 解包时按 api文件/中文映射 配置把字段 key
翻译成中文（配置里没有的 key 保留原名，见 common/field_mapper.py）。
需要读原始英文字段的内部逻辑直接读 resp（dict 子类）即可，不受翻译影响。
"""

import os
import time
from pathlib import Path

import httpx

from common.field_mapper import translate

BASE_URL = "https://xhzjds.cnfic.com.cn"

_client: httpx.AsyncClient | None = None


def _load_env_file() -> None:
    """加载项目根目录 .env 文件到 os.environ（不依赖 python-dotenv）。

    系统环境变量优先级更高（已存在则跳过），便于 Linux 部署时用 export 覆盖。
    解析规则：忽略空行与 # 注释；key=value 或 key="value"；支持 BOM 前缀。
    """
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    try:
        text = env_path.read_text(encoding="utf-8-sig")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        elif value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


_load_env_file()


class ApiResponse(dict):
    """网关响应 + 请求上下文（路径 / financeType / tabName），供 unwrap 做中文翻译。"""

    __slots__ = ("_path", "_finance_type", "_tab_name")

    def __init__(self, data: dict, path: str, finance_type=None, tab_name: str = ""):
        super().__init__(data)
        self._path = path
        self._finance_type = finance_type
        self._tab_name = tab_name or ""


def _headers() -> dict:
    return {
        "Authorization": os.getenv("ENTITY_API_AUTHORIZATION", ""),
        "x-Sec": os.getenv("ENTITY_API_XSEC", ""),
        "x-Chl": "agent",
    }


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=BASE_URL, timeout=30)
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _pick(mapping: dict | None, *names: str):
    if not isinstance(mapping, dict):
        return None
    for name in names:
        if name in mapping:
            return mapping[name]
    return None


async def api_get(path: str, params: dict) -> dict:
    params = {**params, "t": str(int(time.time() * 1000))}
    resp = await get_client().get(path, params=params, headers=_headers())
    resp.raise_for_status()
    return ApiResponse(
        resp.json(),
        path,
        finance_type=_pick(params, "financeType"),
        tab_name=str(_pick(params, "tabName") or ""),
    )


async def api_post(path: str, json_body: dict, params: dict | None = None) -> dict:
    resp = await get_client().post(path, json=json_body, params=params, headers=_headers())
    resp.raise_for_status()
    finance_type = _pick(json_body, "financeType") or _pick(params, "financeType")
    tab_name = _pick(json_body, "tabName") or _pick(params, "tabName")
    return ApiResponse(
        resp.json(), path, finance_type=finance_type, tab_name=str(tab_name or "")
    )


def unwrap(resp: dict) -> dict:
    """统一解包上游 {success, msg, data} 信封，并把 data 的 key 翻译成中文。"""
    if not resp.get("success"):
        message = resp.get("msg", "接口调用失败")
        return {
            "status": "error", "error_message": message,
            "状态码": "调用失败", "摘要": message,
        }
    data = resp.get("data")
    if data is None:
        return {
            "status": "success", "data": data,
            "状态码": "查询无数据", "摘要": "查询成功，但未返回相关数据。", "数据": [],
        }
    path = getattr(resp, "_path", "")
    if path:
        data = translate(
            data,
            path,
            finance_type=getattr(resp, "_finance_type", None),
            tab_name=getattr(resp, "_tab_name", ""),
        )
    return {
        "status": "success", "data": data,
        "状态码": "查询成功", "摘要": "查询成功。", "数据": data,
    }
