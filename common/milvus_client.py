"""名称消歧：DashScope embedding + Milvus 向量检索的共享封装。

Milvus 库：172.29.19.25:19530，database 名字比较误导人——集团和园区的
消歧都在 db_name="park_name" 这个库里（不是"park_name"专属园区，历史命名
而已），政策相关的在 db_name="policy_kb_500"。

score >= _CONFIDENCE_THRESHOLD 才自动采用最高分结果；分数不够或没查到，
返回多个候选让上层（MCP 工具）决定是报错还是把候选列表交给 agent 去问用户。
"""

import os

import httpx
from pymilvus import AsyncMilvusClient

_EMBEDDING_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
_EMBEDDING_MODEL = "text-embedding-v4"

_CONFIDENCE_THRESHOLD = 0.85

_milvus_client: AsyncMilvusClient | None = None


def _get_milvus_client() -> AsyncMilvusClient:
    global _milvus_client
    if _milvus_client is None:
        _milvus_client = AsyncMilvusClient(
            uri=os.getenv("MILVUS_URI", "http://172.29.19.25:19530"),
            db_name=os.getenv("MILVUS_DB_NAME", "park_name"),
            user=os.getenv("MILVUS_USER", ""),
            password=os.getenv("MILVUS_PASSWORD", ""),
        )
    return _milvus_client


async def close_milvus_client() -> None:
    global _milvus_client
    if _milvus_client is not None:
        await _milvus_client.close()
        _milvus_client = None


async def _embed(text: str) -> list[float]:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            _EMBEDDING_URL,
            headers={"Authorization": f"Bearer {os.getenv('DASHSCOPE_API_KEY', '')}"},
            json={"model": _EMBEDDING_MODEL, "input": text},
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]


async def search_by_name(
    collection_name: str,
    embedding_field: str,
    output_fields: list[str],
    query_text: str,
    limit: int = 3,
) -> list[dict]:
    """按名称做语义检索，返回按相似度降序的候选列表（每条带 score 字段）。"""
    embedding = await _embed(query_text)
    client = _get_milvus_client()
    results = await client.search(
        collection_name=collection_name,
        data=[embedding],
        anns_field=embedding_field,
        search_params={"metric_type": "COSINE", "params": {}},
        limit=limit,
        output_fields=output_fields,
    )
    candidates = []
    for hit in results[0]:
        entity = dict(hit["entity"])
        entity["score"] = hit["distance"]
        candidates.append(entity)
    return candidates


async def resolve_entity(
    collection_name: str,
    embedding_field: str,
    output_fields: list[str],
    query_text: str,
) -> dict:
    """消歧的通用落脚点，适用于需要拿回不止"id+name"两个字段的场景（比如园区
    要同时拿 park_id/zjs_park_id/park_name 三个字段）。置信度够就直接给出唯一
    结果，不够就把候选原样返回。

    Returns:
        {"status": "resolved", "fields": {...output_fields}, "score": ...} 或
        {"status": "ambiguous", "candidates": [...]}（分数不够/没结果）
    """
    candidates = await search_by_name(
        collection_name, embedding_field, output_fields, query_text, limit=5
    )
    if candidates and candidates[0]["score"] >= _CONFIDENCE_THRESHOLD:
        top = candidates[0]
        return {
            "status": "resolved",
            "fields": {k: top[k] for k in output_fields},
            "score": top["score"],
        }
    return {"status": "ambiguous", "candidates": candidates}


async def resolve_single(
    collection_name: str,
    embedding_field: str,
    id_field: str,
    name_field: str,
    query_text: str,
) -> dict:
    """resolve_entity 的简化版，只要 id+name 两个字段的场景用这个（比如集团）。

    Returns:
        {"status": "resolved", "id": ..., "name": ..., "score": ...} 或
        {"status": "ambiguous", "candidates": [...]}（分数不够/没结果）
    """
    result = await resolve_entity(
        collection_name, embedding_field, [id_field, name_field], query_text
    )
    if result["status"] == "resolved":
        fields = result["fields"]
        return {
            "status": "resolved",
            "id": fields[id_field],
            "name": fields[name_field],
            "score": result["score"],
        }
    return result
