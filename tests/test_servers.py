import unittest
from pathlib import Path

from servers import (
    enterprise_server,
    entity_resolve_server,
    finance_server,
    person_insight_server,
)


class ServerRegistrationTests(unittest.TestCase):
    def test_each_server_has_only_its_entity_tools(self):
        expected_tools = {
            finance_server: {
                "search_financing_companies", "get_industryFund_list",
                "search_industryFund_investmen_list", "get_industryFund_exit_list",
                "get_fund_detail_basic", "get_fund_detail_investor_list",
                "get_fund_detail_investment_list", "get_fund_detail_exit_list",
                "get_query_competitive_Finance",
            },
            enterprise_server: {
                "get_enterprise_tags", "get_enterprise_basic",
                "get_enterprise_shareholders", "get_enterprise_management",
                "get_enterprise_VCPE_financing", "get_enterprise_stock_financing",
                "get_enterprise_bond_financing", "get_enterprise_bondHolder",
                "get_enterprise_bank_financing", "get_enterprise_receivables_financing",
                "get_enterprise_leasing_financing", "get_enterprise_trust_financing",
                "get_enterprise_credit_financing", "get_enterprise_outbound_investment",
                "get_company_graphy", "get_businessFinance_graphy",
                "get_query_winTenderer_tenderee",
            },
            person_insight_server: {
                "resolve_person", "get_person_legal", "get_person_office",
                "get_person_beneficial", "get_person_controller", "get_person_holder",
                "get_person_union", "get_person_partner", "get_talent_basic",
            },
            entity_resolve_server: {
                "get_industry_tree", "get_region_tree", "search_enterprise_by_name",
            },
        }

        for server, expected in expected_tools.items():
            with self.subTest(server=server.SERVICE_KEY):
                self.assertEqual(set(server.TOOL_NAMES), expected)

    def test_each_server_has_a_unique_entity_route(self):
        servers = [
            finance_server, enterprise_server, person_insight_server,
            entity_resolve_server,
        ]

        self.assertEqual(len({server.ROUTE for server in servers}), 4)
        self.assertEqual(finance_server.ROUTE, "/cece-mcp-servers/PEVC/stream")
        self.assertEqual(enterprise_server.ROUTE, "/cece-mcp-servers/enterprise/stream")
        self.assertEqual(person_insight_server.ROUTE, "/cece-mcp-servers/person/stream")
        self.assertEqual(entity_resolve_server.ROUTE, "/cece-mcp-servers/NER/stream")

    def test_legacy_aggregate_server_is_removed(self):
        self.assertFalse(Path("server.py").exists())
