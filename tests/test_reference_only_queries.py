import inspect
import unittest

from entities import group, industry, park, person, region


class ReferenceOnlyQueryTests(unittest.TestCase):
    def test_group_queries_do_not_call_internal_resolution(self):
        for tool in (group.group_detail, group.group_class_count, group.group_companies,
                     group.group_finance_graphy, group.group_qualification_graphy,
                     group.group_industry_graphy, group.group_risk_events, group.group_opportunity_events):
            self.assertNotIn("_resolve_group_id(", inspect.getsource(tool))

    def test_specific_entity_queries_accept_standard_reference_objects(self):
        self.assertEqual(list(inspect.signature(park.park_detail).parameters)[0], "park_ref")
        self.assertEqual(list(inspect.signature(person.person_detail).parameters)[0], "person_ref")
        self.assertEqual(list(inspect.signature(region.region_score).parameters)[0], "region_ref")
        self.assertEqual(list(inspect.signature(industry.industry_score).parameters)[0], "industry_ref")

    def test_region_queries_do_not_call_internal_resolution(self):
        for name, tool in inspect.getmembers(region, inspect.iscoroutinefunction):
            if name.startswith("region_"):
                self.assertNotIn("_resolve_region(", inspect.getsource(tool))
