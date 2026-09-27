import unicodedata
import unittest

from catfish.data import QueryError
from catfish.query import MODE_ALIASES, MODE_LABELS, parse_query


class QueryTests(unittest.TestCase):
    def test_each_alias_selects_the_expected_hero_mode(self):
        aliases = {
            "무영대": "aram", "ㅁㅇㄷ": "aram",
            "빠대": "standard", "ㅃㄷ": "standard", "영리": "standard", "ㅇㄹ": "standard",
        }
        self.assertEqual(MODE_ALIASES, aliases)
        self.assertEqual(MODE_LABELS, {"aram": "무영대", "standard": "빠대"})
        for alias, mode in aliases.items():
            with self.subTest(alias=alias):
                self.assertEqual(parse_query(f"줄진 {alias}"), (mode, "줄진"))

    def test_each_alias_alone_selects_the_tier_list(self):
        for alias, mode in MODE_ALIASES.items():
            with self.subTest(alias=alias):
                self.assertEqual(parse_query(alias), (mode, None))

    def test_repeated_and_unicode_whitespace_is_normalized(self):
        self.assertEqual(parse_query(" \t정예\u3000타우렌  족장\nㅁㅇㄷ  "),
                         ("aram", "정예 타우렌 족장"))
        self.assertEqual(parse_query("\nㅃㄷ\t\u00a0  "), ("standard", None))

    def test_english_and_korean_hero_names_keep_spaces_and_punctuation(self):
        for name in ("The Lost Vikings", "Lt. Morales", "Zul'jin", "리 리", "모랄레스 중위"):
            with self.subTest(name=name):
                self.assertEqual(parse_query(f"{name} 영리"), ("standard", name))

    def test_nfkc_normalizes_hero_names_and_mode_aliases_consistently(self):
        self.assertEqual(parse_query("Ｚｕｌ＇ｊｉｎ 빠대"), ("standard", "Zul'jin"))
        for alias, mode in MODE_ALIASES.items():
            with self.subTest(alias=alias):
                normalized = unicodedata.normalize("NFKC", alias)
                self.assertEqual(parse_query(f"줄진 {normalized}"), (mode, "줄진"))
                decomposed = unicodedata.normalize("NFD", f"줄진 {alias}")
                self.assertEqual(parse_query(decomposed), (mode, "줄진"))

    def test_empty_hero_only_and_unknown_modes_have_no_default(self):
        for query in ("", " \n\t", "줄진", "The Lost Vikings", "줄진 폭리",
                      "폭리", "aram", "standard", "줄진빠대"):
            with self.subTest(query=query), self.assertRaises(QueryError) as error:
                parse_query(query)
            self.assertIn("/히오스 줄진 무영대", str(error.exception))
            self.assertIn("/히오스 빠대", str(error.exception))
            self.assertNotIn("검색:", str(error.exception))

    def test_only_mode_alone_or_hero_then_mode_is_accepted(self):
        for query in ("빠대 줄진", "무영대 The Lost Vikings", "ㅁㅇㄷ 줄진",
                      "줄진 빠대 통계", "빠대 통계", "빠대 전체 줄진",
                      "빠대 전체 통계 줄진", "줄진 빠대 전체", "전체 빠대",
                      "통계 빠대", "전체 통계 빠대", "무영대 전체",
                      "빠대 전체", "빠대 전체 통계", "ㅁㅇㄷ 전체 통계"):
            with self.subTest(query=query), self.assertRaises(QueryError):
                parse_query(query)

    def test_conflicting_and_repeated_aliases_are_rejected(self):
        for query in ("줄진 빠대 무영대", "줄진 빠대 빠대", "줄진 빠대 영리",
                      "빠대 줄진 영리", "무영대 ㅁㅇㄷ", "영리 ㅇㄹ",
                      "ㅃㄷ 전체 빠대", "줄진 빠대 무영대 영리"):
            with self.subTest(query=query), self.assertRaisesRegex(QueryError, "한 번만"):
                parse_query(query)

    def test_mode_aliases_are_recognized_as_whole_tokens(self):
        self.assertEqual(parse_query("빠대영웅 무영대"), ("aram", "빠대영웅"))
        self.assertEqual(parse_query("Hero영리 빠대"), ("standard", "Hero영리"))


if __name__ == "__main__":
    unittest.main()
