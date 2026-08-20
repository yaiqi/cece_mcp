import ast
from pathlib import Path
import unittest


class PackageImportTests(unittest.TestCase):
    def test_production_identifiers_are_ascii(self):
        source_root = Path(__file__).resolve().parents[1]
        invalid_identifiers = []
        for path in source_root.glob("*/**/*.py"):
            if "__pycache__" in path.parts or "tests" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.append(node.name)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        names.extend(arg.arg for arg in [
                            *node.args.posonlyargs,
                            *node.args.args,
                            *node.args.kwonlyargs,
                        ])
                elif isinstance(node, ast.Name):
                    names.append(node.id)
                invalid_identifiers.extend(
                    f"{path.relative_to(source_root)}:{name}"
                    for name in names
                    if not name.isascii()
                )

        self.assertEqual(invalid_identifiers, [])

    def test_project_root_modules_import_without_parent_directory_on_python_path(self):
        from entities import company, group, industry, park, person, region

        self.assertEqual(group.__name__, "entities.group")
        self.assertEqual(company.__name__, "entities.company")
        self.assertEqual(industry.__name__, "entities.industry")
        self.assertEqual(park.__name__, "entities.park")
        self.assertEqual(person.__name__, "entities.person")
        self.assertEqual(region.__name__, "entities.region")

