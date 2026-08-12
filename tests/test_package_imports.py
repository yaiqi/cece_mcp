import unittest


class PackageImportTests(unittest.TestCase):
    def test_entity_mcp_is_a_regular_package_and_its_entity_modules_import_from_project_root(self):
        import entity_mcp
        from entity_mcp.entities import company, group, industry, park, person, region

        self.assertIsNotNone(entity_mcp.__file__)
        self.assertEqual(group.__name__, "entity_mcp.entities.group")
        self.assertEqual(company.__name__, "entity_mcp.entities.company")
        self.assertEqual(industry.__name__, "entity_mcp.entities.industry")
        self.assertEqual(park.__name__, "entity_mcp.entities.park")
        self.assertEqual(person.__name__, "entity_mcp.entities.person")
        self.assertEqual(region.__name__, "entity_mcp.entities.region")

