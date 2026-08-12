import unittest
from pathlib import Path

from entity_mcp.servers import (
    company_server,
    group_server,
    industry_server,
    park_server,
    person_server,
    region_server,
)


class ServerRegistrationTests(unittest.TestCase):
    def test_each_server_has_only_its_entity_tools(self):
        expected_tools = {
            company_server: {
                "company_judicial_risk", "company_operating_risk", "company_registration_info",
                "company_ip", "company_graph", "company_score", "company_news",
                "company_qualification", "company_financials", "company_business_detail",
                "company_advanced_search", "company_finance_summary", "company_finance_events",
                "company_credit_and_investment", "resolve_company",
            },
            group_server: {
                "group_detail", "group_class_count", "group_companies", "group_finance_graphy",
                "group_industry_graphy", "group_qualification_graphy", "group_risk_events",
                "group_opportunity_events", "resolve_group",
            },
            industry_server: {
                "industry_score", "industry_score_comparison", "industry_concentration",
                "industry_company_portrait", "industry_financial_trend", "industry_company_financial",
                "industry_innovation", "resolve_industry",
            },
            park_server: {
                "park_detail", "park_sub_parks", "park_industry_distribution",
                "park_company_features", "park_companies", "resolve_park",
            },
            person_server: {
                "person_detail", "person_legal_representative", "person_office", "person_beneficial",
                "person_controller", "person_group", "person_union", "person_partners",
                "person_shareholding", "resolve_person",
            },
            region_server: {
                "region_score", "region_company_stats", "region_patent_stats",
                "region_fourteenth_five_year_industries", "region_finance_summary",
                "region_finance_distribution", "region_finance_trend", "region_finance_by_subregion",
                "region_finance_top_companies", "region_finance_events", "region_company_search",
                "region_park_list", "region_macro_portrait", "region_macro_key_indicators",
                "region_social_financing", "region_park_distribution", "region_park_statistics",
                "region_development_zone_list", "resolve_region",
            },
        }

        for server, expected in expected_tools.items():
            with self.subTest(server=server.SERVICE_KEY):
                self.assertEqual(set(server.TOOL_NAMES), expected)

    def test_each_server_has_a_unique_entity_route(self):
        servers = [
            company_server, group_server, industry_server,
            park_server, person_server, region_server,
        ]

        self.assertEqual(len({server.ROUTE for server in servers}), 6)
        self.assertEqual(group_server.ROUTE, "/mcp/group/stream")
        self.assertEqual(region_server.ROUTE, "/mcp/region/stream")

    def test_legacy_aggregate_server_is_removed(self):
        self.assertFalse(Path("server.py").exists())
