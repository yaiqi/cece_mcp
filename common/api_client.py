"""共享网关（xhzjds.cnfic.com.cn）的 HTTP 客户端。

鉴权是 3 个固定值：Authorization（JWT）、x-Sec、x-Chl，从这个 MCP 自己的
.env 读，过期后需要去对应系统重新获取更新。

用一个模块级复用的 AsyncClient（连接池），不要每次调用都新建一个，
并发量上来之后新建连接的开销会很明显。
"""

import os
import time

import httpx

BASE_URL = "https://xhzjds.cnfic.com.cn"

_client: httpx.AsyncClient | None = None


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


async def api_get(path: str, params: dict) -> dict:
    params = {**params, "t": str(int(time.time() * 1000))}
    resp = await get_client().get(path, params=params, headers=_headers())
    resp.raise_for_status()
    return resp.json()


async def api_post(path: str, json_body: dict, params: dict | None = None) -> dict:
    resp = await get_client().post(path, json=json_body, params=params, headers=_headers())
    resp.raise_for_status()
    return resp.json()


def unwrap(resp: dict) -> dict:
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
    return {
        "status": "success", "data": data,
        "状态码": "查询成功", "摘要": "查询成功。", "数据": data,
    }
