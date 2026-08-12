import unittest


class PackageImportTests(unittest.TestCase):
    def test_project_root_modules_import_without_parent_directory_on_python_path(self):
        from entities import company, group, industry, park, person, region

        self.assertEqual(group.__name__, "entities.group")
        self.assertEqual(company.__name__, "entities.company")
        self.assertEqual(industry.__name__, "entities.industry")
        self.assertEqual(park.__name__, "entities.park")
        self.assertEqual(person.__name__, "entities.person")
        self.assertEqual(region.__name__, "entities.region")

