import unittest

from models.entity_refs import EntityRef, PersonRef


class EntityReferenceModelTests(unittest.TestCase):
    def test_person_ref_requires_only_person_no(self):
        ref = PersonRef(person_no="02ad6587897a976a793aa72ead924a47")

        self.assertEqual(ref.person_no, "02ad6587897a976a793aa72ead924a47")
        self.assertEqual(set(PersonRef.model_json_schema()["required"]), {"person_no"})

    def test_entity_ref_forbids_extra_fields(self):
        with self.assertRaises(Exception):
            PersonRef(person_no="x", extra_field="nope")

    def test_entity_ref_supports_dict_access(self):
        ref = PersonRef(person_no="abc")

        self.assertEqual(ref["person_no"], "abc")
        self.assertEqual(ref.get("missing", "default"), "default")
