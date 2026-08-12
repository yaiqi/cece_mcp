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
    async def test_park_detail_returns_llm_facing_fields_only(self):
        raw_detail = {
            "parkId": "CSF_PARK_054416",
            "zjsParkId": None,
            "parkName": "中国(上海)自由贸易试验区临港新片区",
            "parkClass": "省级",
            "parkType": "自贸区",
            "province": "上海市",
            "city": "上海市",
            "district": "浦东新区",
            "parkAddr": " ",
            "parkArea": "87300.0000",
            "areaUnit": "公顷",
            "leadingIndsy": "集成电路|人工智能",
            "companyCount": 395039,
            "sonParkCount": 153,
            "lng": "121.923474",
            "lat": "30.906271",
            "approvalTime": "2018.08",
            "isHaveShape": True,
        }
        with patch.object(park, "api_post", new=AsyncMock(return_value={"success": True, "data": raw_detail})):
            result = await park.park_detail(PARK_REF)

        self.assertEqual(result["状态"], "查询成功")
        self.assertEqual(result["数据"]["园区名称"], "中国(上海)自由贸易试验区临港新片区")
        self.assertEqual(result["数据"]["面积"], "87300公顷")
        self.assertEqual(result["数据"]["主导产业"], ["集成电路", "人工智能"])
        self.assertNotIn("存在园区边界", result["数据"])
        self.assertNotIn("parkId", result["数据"])
        self.assertNotIn("status", result)
        self.assertNotIn("data", result)

    async def test_park_queries_use_the_unified_chinese_envelope(self):
        response_data = [{
            "parkId": "P1",
            "zjsParkId": "ZJS_PARK_P1",
            "regionCode": "310000",
            "parkName": "测试子园区",
            "companyCount": 12,
            "nested": {"industryCode": "A01", "industryName": "集成电路"},
        }]
        with patch.object(park, "api_post", new=AsyncMock(return_value={"success": True, "data": response_data})):
            result = await park.park_sub_parks(PARK_REF)

        self.assertEqual(result["状态"], "查询成功")
        self.assertEqual(result["数据"], [{"子园区名称": "测试子园区", "子园区内企业数量": "12家"}])

    async def test_park_industry_distribution_uses_business_fields(self):
        responses = [
            {"success": True, "data": {"companyCount": 100, "province": "上海市"}},
            {"success": True, "data": [{"industryName": "集成电路", "companyCount": 36, "ratio": 36, "industryCode": "A01"}]},
        ]
        with patch.object(park, "api_post", new=AsyncMock(side_effect=responses)):
            result = await park.park_industry_distribution(PARK_REF)

        self.assertEqual(result["数据"], [{"产业名称": "集成电路", "占比": "36%"}])

    async def test_park_company_features_uses_tab_count_and_merges_results(self):
        responses = [
            {"success": True, "data": {"高新技术企业": {"type": 0, "count": 3144, "companyNature": None, "tabArrays": None}, "全部企业": {"count": 24}}},
            {"success": True, "data": {
                "regcap": [{"name": "100万以下", "value": 12.5}],
                "model": [{"name": "大型", "value": 20}],
                "time": [{"name": "成立1年内", "value": 8}],
                "type": [{"name": "民营企业", "value": 60}],
                "parkId": "P1",
            }},
        ]
        with patch.object(park, "api_post", new=AsyncMock(side_effect=responses)) as api_post:
            result = await park.park_company_features(PARK_REF)

        self.assertEqual(api_post.await_args_list[0].args[0], "/idis_industry/teis/park/tabcompanycount")
        self.assertEqual(api_post.await_args_list[1].args[0], "/idis_industry/teis/park/companyfeatures")
        self.assertEqual(api_post.await_args_list[1].args[1]["companyCount"], 24)
        self.assertEqual(result["状态"], "查询成功")
        self.assertEqual(result["数据"]["企业数量统计"], {"高新技术企业": "3144家", "全部企业": "24家"})
        self.assertEqual(result["数据"]["企业特征分布"], {
            "注册资本": {"100万以下": "12.5%"},
            "企业规模": {"大型": "20%"},
            "成立年限": {"成立1年内": "8%"},
            "企业性质": {"民营企业": "60%"},
        })
        self.assertNotIn("status", result)
        self.assertNotIn("data", result)

    async def test_park_companies_keeps_only_requested_company_fields(self):
        raw_data = {
            "totalCount": 2,
            "list": [{
                "companyName": "测试企业",
                "registCapiValue": "1000",
                "registCapiUnit": "万元人民币",
                "province": "上海",
                "city": "上海市",
                "district": "浦东新区",
                "registeredCapital": "1000万元人民币",
                "status": "存续",
                "companyType": "有限责任公司",
                "creditCode": "9131...",
            }],
        }
        with patch.object(park, "api_post", new=AsyncMock(return_value={"success": True, "data": raw_data})):
            result = await park.park_companies(PARK_REF)

        self.assertEqual(result["数据"], {
            "企业总数": 2,
            "企业列表": [{
                "企业名称": "测试企业",
                "注册资本": "1000万元人民币",
                "所在地": "上海上海市浦东新区",
                "注册资本信息": "1000万元人民币",
                "经营状态": "存续",
                "企业类型": "有限责任公司",
            }],
        })

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
