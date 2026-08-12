import unittest
import inspect

from entities import group, park, region
from models.entity_refs import GroupRef, ParkRef, RegionRef


class EntityReferenceModelTests(unittest.TestCase):
    def test_park_ref_requires_all_three_standard_fields(self):
        ref = ParkRef(
            park_id="P1",
            zjs_park_id="ZJS_PARK_P1",
            park_name="测试园区",
        )

        self.assertEqual(ref.park_id, "P1")
        self.assertEqual(set(ParkRef.model_json_schema()["required"]), {
            "park_id", "zjs_park_id", "park_name",
        })

    def test_region_ref_contains_region_code_and_breadcrumb(self):
        ref = RegionRef(
            region_code="310000",
            region_name="上海市",
            province_name="上海市",
            city_name="上海市",
            district_name="",
        )

        self.assertEqual(ref.region_code, "310000")

    def test_query_tools_declare_their_standard_reference_model(self):
        self.assertIs(inspect.signature(park.park_detail).parameters["park_ref"].annotation, ParkRef)
        self.assertIs(inspect.signature(group.group_detail).parameters["group_ref"].annotation, GroupRef)
        self.assertIs(inspect.signature(region.region_score).parameters["region_ref"].annotation, RegionRef)

    def test_park_query_docs_describe_the_standard_park_reference(self):
        for tool in (
            park.park_detail,
            park.park_sub_parks,
            park.park_industry_distribution,
            park.park_company_features,
            park.park_companies,
        ):
            with self.subTest(tool=tool.__name__):
                self.assertIn("park_ref", tool.__doc__)
                self.assertNotIn("name_or_id", tool.__doc__)
