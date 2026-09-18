import json
import tempfile
import unittest
from pathlib import Path

from common import field_mapper
from common.server_factory import _clean_output


class OutputCleanupTests(unittest.TestCase):
    def test_top_level_envelope_fields_are_removed(self):
        result = _clean_output({
            "status": "success", "data": {"x": 1},
            "状态码": "查询成功", "摘要": "ok", "数据": {"x": 1},
        })
        self.assertNotIn("status", result)
        self.assertNotIn("data", result)
        self.assertEqual(result["状态码"], "查询成功")

    def test_nested_business_status_and_data_are_kept(self):
        result = _clean_output({
            "状态码": "查询成功",
            "数据": [{"companyName": "测试企业", "status": "存续", "data": {"note": 1}}],
        })
        self.assertEqual(result["数据"][0]["status"], "存续")
        self.assertEqual(result["数据"][0]["data"], {"note": 1})

    def test_id_fields_are_removed_recursively(self):
        result = _clean_output({
            "状态码": "查询成功",
            "数据": {
                "companyName": "测试企业",
                "companyId": "abc",
                "fundOrgId": "123",
                "id": "x",
                "investId": 1,
                "serialNo": 7,
                "fundNo": "SCS723",
                "list": [{"exitId": 2, "person_no": "no1", "name": "张三"}],
            },
        })
        data = result["数据"]
        self.assertNotIn("companyId", data)
        self.assertNotIn("fundOrgId", data)
        self.assertEqual(data["id"], "x")
        self.assertNotIn("investId", data)
        self.assertEqual(data["serialNo"], 7)
        self.assertEqual(data["fundNo"], "SCS723")
        self.assertNotIn("exitId", data["list"][0])
        self.assertEqual(data["list"][0]["person_no"], "no1")

    def test_plain_words_ending_in_lowercase_id_are_kept(self):
        result = _clean_output({"valid": True, "paid": "yes", "状态码": "查询成功"})
        self.assertEqual(result["valid"], True)
        self.assertEqual(result["paid"], "yes")


class AutoTranslationTests(unittest.TestCase):
    def _mapper_with_tmp_auto(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_paths = field_mapper._AUTO_PATHS
            field_mapper._AUTO_PATHS = [Path(tmp) / "field_mapping_auto.json"]
            try:
                mapper = field_mapper.FieldMapper()
                yield mapper, Path(tmp) / "field_mapping_auto.json"
            finally:
                field_mapper._AUTO_PATHS = old_paths

    def test_unknown_key_is_auto_translated_and_persisted(self):
        for mapper, auto_file in self._mapper_with_tmp_auto():
            out = mapper.translate_keys({"fundName": "毅达绿色基金", "unknownXyzKey": 1})
            self.assertEqual(out["基金名称"], "毅达绿色基金")
            self.assertEqual(out["unknownXyzKey"], 1)
            self.assertTrue(auto_file.exists())
            saved = json.loads(auto_file.read_text(encoding="utf-8"))
            self.assertEqual(saved["fundName"], "基金名称")

    def test_word_composition_fallback(self):
        for mapper, _ in self._mapper_with_tmp_auto():
            out = mapper.translate_keys({"investorName": "红杉", "companyCount": 3})
            self.assertEqual(out["出资人名称"], "红杉")
            self.assertEqual(out["企业数量"], 3)

    def test_configured_mapping_takes_priority_over_auto(self):
        for mapper, _ in self._mapper_with_tmp_auto():
            out = mapper.translate(
                {"name": "宁德时代", "creditCode": "9135"},
                "/cmp/detail/basic",
            )
            self.assertIn("企业名称", out)
            self.assertIn("统一社会信用代码", out)


class ShapingTests(unittest.TestCase):
    def test_enterprise_tags_shaper_returns_six_label_categories(self):
        from common.output_shaping import _shape_enterprise_tags

        data = {
            "企业名称": "测试企业",
            "标签信息": {
                "financeTagList": [{"标签名称": "融资"}],
                "technologyTagList": [{"标签名称": "高新技术企业"}],
                "rankingTagList": [{"标签名称": "专精特新"}],
                "standardTagList": [{"标签名称": "标准制定"}],
            },
            "企业基本信息": {"企业性质": "民营企业", "注册资本": "1000万元"},
        }
        out = _shape_enterprise_tags(data)
        self.assertEqual(out["企业名称"], "测试企业")
        self.assertEqual(out["资本市场标签"], ["融资"])
        self.assertEqual(out["科技标签"], ["高新技术企业"])
        self.assertEqual(out["榜单荣誉标签"], ["专精特新"])
        self.assertEqual(out["标准制定标签"], ["标准制定"])
        self.assertNotIn("产业标签", out)
        self.assertEqual(out["风险标签"], [])
        self.assertNotIn("企业信息", out)

    def test_names_compacts_dict_items(self):
        from common.output_shaping import _names

        value = [{"投资企业名称": "红杉资本"}, {"投资企业名称": "高瓴"}]
        self.assertEqual(_names(value), ["红杉资本", "高瓴"])


if __name__ == "__main__":
    unittest.main()
