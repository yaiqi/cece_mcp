import unittest
from unittest.mock import AsyncMock, patch

from entity_mcp.common.business_protocol import (
    多候选,
    唯一匹配,
    实体未匹配,
    查询成功,
    查询无数据,
    调用失败,
)
from entity_mcp.common import milvus_client
from entity_mcp.entities import park


class BusinessProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_single_preserves_internal_score(self):
        with patch.object(
            milvus_client,
            "search_by_name",
            new=AsyncMock(return_value=[{"group_id": "G1", "group_name": "测试集团", "score": 0.9}]),
        ):
            result = await milvus_client.resolve_single(
                "collection", "embedding", "group_id", "group_name", "测试集团"
            )

        self.assertEqual(result["score"], 0.9)

    async def test_resolve_park_omits_score_from_candidates(self):
        with patch.object(
            park,
            "resolve_entity",
            new=AsyncMock(return_value={
                "status": "ambiguous",
                "candidates": [{
                    "park_id": "P1",
                    "zjs_park_id": "ZJS_PARK_P1",
                    "park_name": "测试园区",
                    "score": 0.8,
                }],
            }),
        ):
            _, result = await park._resolve_park("测试园区")

        self.assertNotIn("score", result["candidates"][0])

    def test_resolution_responses_use_chinese_status_codes(self):
        self.assertEqual(唯一匹配("集团", "国家电网", {"group_id": "G1"})["状态码"], "唯一匹配")
        self.assertEqual(多候选("园区", "张江", [])["状态码"], "多候选")
        self.assertEqual(实体未匹配("企业", "腾讯")["状态码"], "实体未匹配")

    def test_query_responses_distinguish_no_data_and_failure(self):
        self.assertEqual(查询成功({})["状态码"], "查询成功")
        self.assertEqual(查询无数据("未查询到公开记录")["状态码"], "查询无数据")
        self.assertEqual(调用失败("上游服务异常")["状态码"], "调用失败")

    async def test_resolve_park_converts_milvus_exception_to_business_failure(self):
        with patch.object(park, "_resolve_park", new=AsyncMock(side_effect=RuntimeError("Milvus unavailable"))):
            result = await park.resolve_park("张江高科技园区")

        self.assertEqual(result["状态码"], "调用失败")
        self.assertNotIn("Milvus unavailable", result["摘要"])
