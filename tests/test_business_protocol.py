import unittest
from unittest.mock import AsyncMock, patch

from common.business_protocol import (
    call_failed,
    entity_not_matched,
    multiple_candidates,
    no_data,
    query_success,
    unique_match,
)
from common import milvus_client
from entities import group, park


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
        self.assertEqual(unique_match("集团", "国家电网", {"group_id": "G1"})["状态码"], "唯一匹配")
        self.assertEqual(multiple_candidates("园区", "张江", [])["状态码"], "多候选")
        self.assertEqual(entity_not_matched("企业", "腾讯")["状态码"], "实体未匹配")

    def test_query_responses_distinguish_no_data_and_failure(self):
        self.assertEqual(query_success({})["状态码"], "查询成功")
        self.assertEqual(no_data("未查询到公开记录")["状态码"], "查询无数据")
        self.assertEqual(call_failed("上游服务异常")["状态码"], "调用失败")

    async def test_resolve_park_converts_milvus_exception_to_business_failure(self):
        with patch.object(park, "_resolve_park", new=AsyncMock(side_effect=RuntimeError("Milvus unavailable"))):
            result = await park.resolve_park("张江高科技园区")

        self.assertEqual(result["状态码"], "调用失败")
        self.assertNotIn("Milvus unavailable", result["摘要"])

    async def test_resolve_group_keeps_candidate_id_and_hides_similarity_score(self):
        with patch.object(
            group,
            "resolve_single",
            new=AsyncMock(return_value={
                "status": "ambiguous",
                "candidates": [{"group_id": "G0001", "group_name": "测试集团", "score": 0.7}],
            }),
        ):
            result = await group.resolve_group("测试集团")

        self.assertEqual(result["状态码"], "多候选")
        self.assertEqual(result["候选列表"], [{"group_id": "G0001", "group_name": "测试集团"}])

    async def test_group_companies_loads_its_internal_query_identifier(self):
        with (
            patch.object(
                group,
                "_get_group_meta",
                new=AsyncMock(return_value={"group_name": "测试集团", "zjs_group_id": "ZJSG0001"}),
            ),
            patch.object(group, "api_post", new=AsyncMock(return_value={"success": True, "data": {}})) as api_post,
        ):
            await group.group_companies({"group_id": "G0001", "group_name": "测试集团"})

        self.assertEqual(api_post.await_args.args[1]["groupId"], "ZJSG0001")

    async def test_group_detail_returns_chinese_model_facing_data(self):
        response = {
            "success": True,
            "data": {
                "groupId": "G0001",
                "groupName": "测试集团",
                "groupLevel": "大型集团",
                "companyCount": 12,
                "companyInfo": {
                    "companyId": "C0001",
                    "companyName": "测试成员企业",
                    "industryCode": "C39",
                    "industryName": "计算机、通信和其他电子设备制造业",
                },
            },
        }
        with patch.object(group, "api_get", new=AsyncMock(return_value=response)):
            result = await group.group_detail({"group_id": "G0001", "group_name": "测试集团"})

        self.assertEqual(result["状态"], "查询成功")
        self.assertEqual(
            result["数据"],
            {
                "集团名称": "测试集团",
                "集团级别": "大型集团",
                "企业数量": 12,
                "企业信息": {
                    "企业名称": "测试成员企业",
                    "产业名称": "计算机、通信和其他电子设备制造业",
                },
            },
        )

    async def test_group_events_keep_structure_but_remove_identifiers(self):
        response = {
            "success": True,
            "data": {
                "totalCount": 1,
                "list": [{
                    "eventId": "E0001",
                    "eventName": "经营风险事件",
                    "eventTypeCode": "Z0101",
                    "eventTypeName": "司法风险",
                    "companyName": "测试企业",
                }],
            },
        }
        with patch.object(group, "api_post", new=AsyncMock(return_value=response)):
            result = await group.group_risk_events({"group_id": "G0001", "group_name": "测试集团"})

        self.assertEqual(
            result["数据"],
            {
                "总数": 1,
                "列表": [{"事件名称": "经营风险事件", "事件类型": "司法风险", "企业名称": "测试企业"}],
            },
        )
