import copy
import json
from pathlib import Path
import tempfile
import unittest

from catfish.data import (
    LEVEL_KEYS, DataStore, QueryError, captured_label, chart_page, chart_rows,
    find_hero, hero_tier, recommended_builds, tier_rows, top_builds,
)


def hero(slug, name, rate=50.0, games=100):
    return {"name": name, "short_name": slug, "win_rate": rate, "games_played": games}


def build(rate, games, talent_id):
    return {"win_rate": rate, "games_played": games,
            **{k: {"talent_id": talent_id + i} for i, k in enumerate(LEVEL_KEYS)}}


def snapshot():
    return {
        "schema_version": 1, "mode": "aram", "captured_at": "2026-09-26T22:00:43.728Z",
        "filters": {"timeframe": ["2.55.17.98025"]},
        "heroes": [hero("azmodan", "Azmodan", 59.88, 14308), hero("zuljin", "Zul'jin"),
                   hero("xul", "Xul"), hero("lucio", "Lúcio"), hero("etc", "E.T.C.")],
        "builds": {"azmodan": [build(80, 5, 1), build(60, 500, 10), build(62, 200, 20), build(58, 300, 30)]},
    }


class QueryTests(unittest.TestCase):
    def test_korean_english_accents_spacing_and_aliases(self):
        data = snapshot()
        for query, slug in [("아즈모단", "azmodan"), ("AZMODAN", "azmodan"), ("줄진", "zuljin"),
                            ("zul jin", "zuljin"), ("LUCIO", "lucio"), ("정타족", "etc")]:
            with self.subTest(query=query):
                self.assertEqual(find_hero(data, query)["short_name"], slug)
        self.assertEqual(find_hero(data, "줄")["short_name"], "xul")
        for query in ("", "없음"):
            with self.assertRaises(QueryError):
                find_hero(data, query)

    def test_ambiguous_partial_requires_selection(self):
        data = snapshot()
        data["heroes"].extend([hero("malfurion", "Malfurion"), hero("malganis", "Mal'Ganis")])
        with self.assertRaisesRegex(QueryError, "여러 영웅"):
            find_hero(data, "말")

    def test_chart_sort_filter_pages_and_out_of_range(self):
        data = {"heroes": [hero(str(i), str(i), 40 + i, 100 - i) for i in range(31)]}
        rows = chart_rows(data)
        self.assertEqual(rows[0]["short_name"], "30")
        self.assertEqual(chart_page(rows, 3)[0][0]["short_name"], "0")
        self.assertEqual(chart_page(rows, 1)[1], 3)
        self.assertEqual(chart_rows(data, "games_played")[0]["short_name"], "0")
        self.assertEqual(len(chart_rows(data, min_games=90)), 11)
        for page in (0, 4):
            with self.assertRaises(QueryError):
                chart_page(rows, page)
        with self.assertRaises(QueryError):
            chart_rows(data, min_games=101)

    def test_tiers_include_every_hero_at_exact_win_rate_boundaries(self):
        rates = [100, 55, 54.99, 52, 51.99, 48, 47.99, 45, 44.99, 0]
        data = {"heroes": [hero(str(i), str(i), rate, 0 if i == 9 else 100)
                           for i, rate in enumerate(rates)]}
        tiers = tier_rows(data)
        self.assertEqual(list(tiers), ["S", "A", "B", "C", "D"])
        self.assertEqual([[h["win_rate"] for h in rows] for rows in tiers.values()],
                         [[100, 55], [54.99, 52], [51.99, 48], [47.99, 45], [44.99, 0]])
        self.assertEqual(sum(map(len, tiers.values())), len(data["heroes"]))
        for tier, rows in tiers.items():
            for row in rows:
                self.assertEqual(hero_tier(row), tier)

    def test_tiers_preserve_win_rate_sort_and_all_empty_bands(self):
        data = {"heroes": [hero(str(i), str(i), 56 + i % 4, i) for i in range(90)]}
        tiers = tier_rows(data)
        self.assertEqual(tiers["S"], chart_rows(data))
        self.assertEqual([tiers[name] for name in ("A", "B", "C", "D")], [[], [], [], []])

    def test_top_three_sort_filter_and_dedup(self):
        data = snapshot()
        azmodan = data["heroes"][0]
        data["builds"]["azmodan"].append(copy.deepcopy(data["builds"]["azmodan"][1]))
        self.assertEqual([b["games_played"] for b in top_builds(data, azmodan)], [500, 300, 200])
        self.assertEqual(top_builds(data, azmodan, "win_rate")[0]["games_played"], 5)
        self.assertEqual([b["win_rate"] for b in top_builds(data, azmodan, "win_rate", 100)], [62, 60, 58])
        self.assertEqual(len(top_builds(data, azmodan, min_games=400)), 1)
        with self.assertRaises(QueryError):
            top_builds(data, azmodan, min_games=1000)
        with self.assertRaisesRegex(QueryError, "아직 없습니다"):
            top_builds(data, data["heroes"][1])

    def test_recommendations_compare_win_rate_and_usage_without_mutating_source(self):
        data = snapshot()
        before = copy.deepcopy(data)
        recommendations = recommended_builds(data, data["heroes"][0])
        self.assertEqual([(b["win_rate"], b["games_played"], b["recommendation_labels"])
                          for b in recommendations],
                         [(80, 5, ("승률 1위",)), (60, 500, ("선택 수 1위",))])
        self.assertEqual(data, before)

    def test_recommendations_merge_same_talents_for_both_categories(self):
        data = snapshot()
        winner = build(90, 1000, 100)
        data["builds"]["azmodan"].extend([winner, copy.deepcopy(winner)])
        recommendations = recommended_builds(data, data["heroes"][0])
        self.assertEqual(len(recommendations), 1)
        self.assertEqual(recommendations[0]["recommendation_labels"], ("승률 1위", "선택 수 1위"))
        self.assertEqual(recommendations[0]["level_one"], winner["level_one"])

    def test_store_missing_mode_reload_and_korean_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            store = DataStore(Path(directory))
            with self.assertRaisesRegex(QueryError, "아직 없습니다"):
                store.snapshot("standard")
            path = Path(directory) / "aram.json"
            data = snapshot()
            path.write_text(json.dumps(data))
            loaded = store.snapshot("aram")
            self.assertEqual(loaded["heroes"][0]["name_ko"], "아즈모단")
            self.assertEqual(captured_label(loaded), "2026-09-27 07:00 KST")
            data["heroes"][0]["games_played"] = 20000
            path.write_text(json.dumps(data))
            self.assertEqual(store.snapshot("aram")["heroes"][0]["games_played"], 20000)
            path.write_text("broken")
            with self.assertRaisesRegex(QueryError, "읽을 수 없습니다"):
                store.snapshot("aram")


if __name__ == "__main__":
    unittest.main()
