from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from catfish import talents
from catfish.talents import talent_name
from scripts.update_talent_names import apply_json_patch, extract_names


class TalentNamesTests(unittest.TestCase):
    def test_game_names_include_heroics_punctuation_and_recent_talent(self):
        expected = {
            "ZuljinRecklessness": "무모함",
            "Zul'jinAmaniRageAmaniHide": "아마니의 가죽",
            "ZuljinTazdingo": "타즈딩고!",
            "AbathurSlapathur": "찰싹투르",
            "ETCBlockParty": "자꾸만 막고 싶네",
            "LiliHeroicAbilityJugOf1000Cups": "1,000잔 돌리기",
        }
        for identifier, korean in expected.items():
            with self.subTest(identifier=identifier):
                self.assertEqual(talent_name({"talent_name": identifier, "title": "English title"}), korean)

    def test_stable_id_is_used_independently_of_title_and_profile_numeric_id(self):
        record = {"talent_name": "ZUL’JIN-AMANI-RAGE-AMANI-HIDE", "title": "Stale English", "talent_id": 99999}
        original = deepcopy(record)
        self.assertEqual(talent_name(record), "아마니의 가죽")
        self.assertEqual(record, original)

    def test_unknown_ids_keep_original_title_without_guessing(self):
        self.assertEqual(talent_name({"talent_name": "FutureTalent", "title": "Recklessness"}), "Recklessness")
        self.assertEqual(talent_name({"title": "이미 한글"}), "이미 한글")
        self.assertEqual(talent_name({"talent_name": "FutureTalent"}), "FutureTalent")
        self.assertEqual(talent_name({}), "—")

    def test_missing_catalog_does_not_break_build_rendering(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(talents, "CATALOG_PATH", Path(directory) / "missing.json"):
                talents._catalog.cache_clear()
                try:
                    with self.assertLogs("catfish.talents", level="WARNING"):
                        self.assertEqual(talent_name({"talent_name": "ZuljinRecklessness", "title": "Recklessness"}), "Recklessness")
                finally:
                    talents._catalog.cache_clear()

    def test_bundled_catalog_covers_roster_and_records_reproducible_source(self):
        catalog = json.loads(talents.CATALOG_PATH.read_text(encoding="utf-8"))
        self.assertEqual(catalog["locale"], "ko-KR")
        self.assertGreater(len(catalog["names"]), 1800)
        self.assertEqual(catalog["source"]["license"], "MIT")
        for source in catalog["source"]["files"]:
            self.assertIn(catalog["source"]["revision"], source["url"])
            self.assertRegex(source["sha256"], r"^[0-9a-f]{64}$")
        self.assertTrue(all(name.strip() for name in catalog["names"].values()))


class TalentCatalogBuilderTests(unittest.TestCase):
    def test_patches_handle_game_name_changes_and_json_pointer_escaping(self):
        data = {"items": {"talent": {"name": {"Old|Button|Q|Level1": "옛 이름", "Slash/Name~|B|W|Level4": "원본"}}}}
        result = apply_json_patch(data, [
            {"op": "remove", "path": "/items/talent/name/Old|Button|Q|Level1"},
            {"op": "add", "path": "/items/talent/name/New|Button|Q|Level1", "value": "새 이름"},
            {"op": "replace", "path": "/items/talent/name/Slash~1Name~0|B|W|Level4", "value": "바뀐 이름"},
        ])
        self.assertEqual(extract_names(result), {"new": "새 이름", "slashname": "바뀐 이름"})

    def test_conflicting_ids_or_missing_translations_fail_generation(self):
        for names in (
            {"A-B|Button|Q|Level1": "첫째", "AB|Button|Q|Level1": "둘째"},
            {"Talent|Button|Q|Level1": ""},
        ):
            with self.subTest(names=names), self.assertRaises(ValueError):
                extract_names({"items": {"talent": {"name": names}}})

    def test_unknown_patch_operation_fails_instead_of_omitting_changes(self):
        with self.assertRaises(ValueError):
            apply_json_patch({}, [{"op": "move", "from": "/old", "path": "/new"}])


if __name__ == "__main__":
    unittest.main()
