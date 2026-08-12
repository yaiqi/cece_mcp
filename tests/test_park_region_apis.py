import unittest
from unittest.mock import AsyncMock, patch

from entities import park, region


PARK_REF = {
    "park_id": "P1",
    "zjs_park_id": "ZJS_PARK_P1",
    "park_name": "测试园区",
}
REGION_REF = {
    "region_code": "310000",
    "province_name": "上海市",
    "city_name": "上海市",
    "district_name": "",
}


class ParkAndRegionApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_park_company_features_uses_tab_count_and_merges_results(self):
        responses = [
            {"success": True, "data": {"全部企业": {"count": 24}}},
            {"success": True, "data": {"规模分布": []}},
        ]
        with patch.object(park, "api_post", new=AsyncMock(side_effect=responses)) as api_post:
            result = await park.park_company_features(PARK_REF)

        self.assertEqual(api_post.await_args_list[0].args[0], "/idis_industry/teis/park/tabcompanycount")
        self.assertEqual(api_post.await_args_list[1].args[0], "/idis_industry/teis/park/companyfeatures")
        self.assertEqual(api_post.await_args_list[1].args[1]["companyCount"], 24)
        self.assertEqual(result["数据"]["企业数量统计"]["全部企业"]["count"], 24)
        self.assertEqual(result["数据"]["企业特征分布"], {"规模分布": []})

    async def test_region_park_tools_use_region_reference(self):
        with patch.object(
            region, "api_post", new=AsyncMock(return_value={"success": True, "data": {}}
        )) as api_post:
            await region.region_park_distribution(REGION_REF)
            await region.region_park_statistics(REGION_REF)
            await region.region_development_zone_list(
                REGION_REF, park_type_list=["经济技术开发区"], leading_indsy_list=["集成电路"]
            )

        self.assertEqual(api_post.await_args_list[0].args[0], "/idis_industry/teis/park/regiondisplaypark")
        self.assertEqual(api_post.await_args_list[0].args[1]["regionCode"], "310000")
        self.assertEqual(api_post.await_args_list[1].args[0], "/idis_industry/teis/park/statisticpark")
        self.assertEqual(api_post.await_args_list[1].args[1]["parkClass"], ["国家级", "省级", "市级", "其他"])
        self.assertEqual(api_post.await_args_list[2].args[0], "/idis_industry/teis/park/kaifaqulist")
        self.assertEqual(api_post.await_args_list[2].args[1]["parkTypeList"], ["经济技术开发区"])
        self.assertEqual(api_post.await_args_list[2].args[1]["leadingIndsyList"], ["集成电路"])
