from io import BytesIO
from inspect import signature
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from catfish.render import (
    LEVEL_FIELDS, _artwork, _asset_path, _capture_label, _font, _text,
    render_builds, render_chart, render_tier_list,
)


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = {
            "mode": "aram",
            "captured_at": "2026-09-27T00:12:00Z",
            "filters": {"timeframe": ["2.55.17.98025", "2.55.17.97771"]},
            "assets": {},
        }
        self.hero = {
            "name": "The Lost Vikings",
            "name_ko": "길 잃은 바이킹",
            "short_name": "lostvikings",
            "role": "Support",
            "win_rate": 48.67,
            "games_played": 12034,
        }

    def assert_png(self, data: bytes, *, width: int = 1100, minimum_height: int = 300):
        with Image.open(BytesIO(data)) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.width, width)
            self.assertGreaterEqual(image.height, minimum_height)
            image.load()

    def assert_content_within_image(self, data, text_calls, artwork_calls):
        with Image.open(BytesIO(data)) as image:
            for call in text_calls:
                arguments = signature(_text).bind(*call.args, **call.kwargs)
                arguments.apply_defaults()
                values = arguments.arguments
                bounds = values["draw"].textbbox(
                    values["position"], str(values["value"]),
                    font=_font(values["size"], values["bold"]), anchor=values["anchor"],
                )
                with self.subTest(text=values["value"]):
                    self.assertGreaterEqual(bounds[0], 0)
                    self.assertGreaterEqual(bounds[1], 0)
                    self.assertLessEqual(bounds[2], image.width)
                    self.assertLessEqual(bounds[3], image.height)
            for call in artwork_calls:
                (x, y), size = call.args[3:5]
                self.assertGreaterEqual(x, 0)
                self.assertGreaterEqual(y, 0)
                self.assertLessEqual(x + size, image.width)
                self.assertLessEqual(y + size, image.height)

    def test_full_chart_with_korean_and_missing_portraits(self):
        self.assert_png(render_chart(self.snapshot, [self.hero] * 15, page=2, pages=6), minimum_height=1200)

    def test_tier_board_renders_all_heroes_past_chart_and_roster_limits(self):
        heroes = [dict(self.hero, short_name=f"hero{index}", name_ko=f"영웅{index}") for index in range(85)]
        tiers = {"S": [], "A": [], "B": heroes, "C": [], "D": []}
        with patch("catfish.render._artwork", wraps=_artwork) as artwork, patch("catfish.render._text", wraps=_text) as text:
            data = render_tier_list(self.snapshot, tiers)
        self.assert_png(data, width=2560, minimum_height=1441)
        self.assertEqual([call.args[2] for call in artwork.call_args_list], [f"portrait:hero{index}" for index in range(85)])
        labels = [str(call.args[2]) for call in text.call_args_list]
        self.assertIn("전체 85명", labels)
        self.assertIn("영웅84", labels)
        self.assertEqual(labels.count("48.67%"), 85)
        self.assertEqual(labels.count("12,034게임"), 85)
        with Image.open(BytesIO(data)) as image:
            last_portrait = artwork.call_args_list[-1]
            self.assertLess(last_portrait.args[3][1] + last_portrait.args[4], image.height - 112)

    def test_full_tier_board_is_widescreen_and_preserves_every_hero_and_long_names(self):
        tiers = {}
        heroes = []
        for tier, count, win_rate in (("S", 5, 55.1), ("A", 19, 53.1), ("B", 26, 50.1), ("C", 16, 46.1), ("D", 18, 44.1)):
            tiers[tier] = []
            for _ in range(count):
                hero = dict(self.hero, short_name=f"hero{len(heroes)}", name_ko=f"영웅{len(heroes)}", win_rate=win_rate)
                heroes.append(hero)
                tiers[tier].append(hero)
        heroes[0]["name_ko"] = "정예 타우렌 족장"
        heroes[-1]["name_ko"] = "길 잃은 바이킹"

        with patch("catfish.render._artwork", wraps=_artwork) as artwork, patch("catfish.render._text", wraps=_text) as text:
            data = render_tier_list(self.snapshot, tiers)
        self.assert_png(data, width=2560)
        self.assertEqual([call.args[2] for call in artwork.call_args_list], [f"portrait:hero{index}" for index in range(84)])
        labels = [str(call.args[2]) for call in text.call_args_list]
        self.assertIn("전체 84명", labels)
        for hero in heroes:
            self.assertIn(hero["name_ko"], labels)
        self.assertEqual(labels.count("12,034게임"), 84)
        with Image.open(BytesIO(data)) as image:
            self.assertEqual(image.size, (2560, 1440))
            for call in artwork.call_args_list:
                (x, y), size = call.args[3:5]
                self.assertGreaterEqual(x, 0)
                self.assertLessEqual(x + size, image.width)
                self.assertLess(y + size, image.height - 112)

    def test_tier_board_has_all_tier_labels_bounds_and_source_with_empty_data(self):
        with patch("catfish.render._text", wraps=_text) as text:
            self.assert_png(render_tier_list(self.snapshot, {}), width=2560)
        labels = [str(call.args[2]) for call in text.call_args_list]
        for label in ("S", "A", "B", "C", "D", "55% 이상", "52% 이상", "48% 이상", "45% 이상",
                      "55% 미만", "52% 미만", "48% 미만", "45% 미만", "SOURCE  HEROES PROFILE"):
            self.assertIn(label, labels)
        self.assertEqual(labels.count("해당 티어의 영웅이 없습니다."), 5)
        self.assertIn("수집 2026.09.27 09:12 KST", labels)
        self.assertTrue(any("2.55.17.98025" in label for label in labels))

    def test_three_builds_with_long_talent_names_and_missing_art(self):
        build = {
            "games_played": 2345,
            "win_rate": 58.35,
            "level_one": {"title": "This is a very long talent name that should wrap safely", "sort": "1"},
            "level_ten": {"title": "Let's Go!", "sort": "2"},
        }
        with patch("catfish.render._text", wraps=_text) as text, \
                patch("catfish.render._artwork", wraps=_artwork) as artwork:
            data = render_builds(self.snapshot, self.hero, [build] * 3, min_games=100)
        self.assert_png(data, minimum_height=500)
        self.assertEqual(len(artwork.call_args_list), 21)
        self.assert_content_within_image(data, text.call_args_list, artwork.call_args_list)
        with Image.open(BytesIO(data)) as image:
            self.assertLess(image.height, 1100)

    def test_all_korean_talent_names_icons_and_picks_survive_compact_wrapping(self):
        names = (
            "도끼 맛 좀 보여줄까?", "아마니의 분노", "잔혹한 공격", "타즈딩고!",
            "그물 덫", "모든대상에게추가피해를주는매우긴한글특성이름", "무모한 자의 분노",
        )
        picks = (1, 3, 2, 2, 1, 4, 3)
        build = {"games_played": 1234, "win_rate": 59.72, "recommendation_labels": ("선택 수 1위",)}
        for index, (_, field) in enumerate(LEVEL_FIELDS):
            build[field] = {
                "talent_name": f"talent{index}", "title": f"English talent {index}",
                "icon": f"talent:icon{index}", "sort": str(picks[index]),
            }
        catalog = {f"talent{index}": name for index, name in enumerate(names)}
        with patch("catfish.talents._catalog", return_value=catalog), \
                patch("catfish.render._text", wraps=_text) as text, \
                patch("catfish.render._artwork", wraps=_artwork) as artwork:
            data = render_builds(self.snapshot, self.hero, [build])
        self.assert_png(data, minimum_height=200)
        self.assertEqual([call.args[2] for call in artwork.call_args_list],
                         [f"talent:icon{index}" for index in range(7)])
        labels = [str(call.args[2]) for call in text.call_args_list]
        for level, _ in LEVEL_FIELDS:
            self.assertEqual(labels.count(f"{level}레벨"), 1)
        self.assertEqual([label for label in labels if label in {str(pick) for pick in picks}],
                         [str(pick) for pick in picks])
        self.assertFalse(any("English talent" in label for label in labels))

        # Reassemble every name from its visible lines below the corresponding icon.
        for name, icon in zip(names, artwork.call_args_list):
            (x, y), size = icon.args[3:5]
            lines = [call for call in text.call_args_list
                     if abs(call.args[1][0] - (x + size / 2)) < 1 and call.args[1][1] >= y + size]
            self.assertEqual("".join(str(call.args[2]).replace(" ", "") for call in lines),
                             name.replace(" ", ""))
            self.assertTrue(all(call.args[3] >= 18 for call in lines))
        self.assert_content_within_image(data, text.call_args_list, artwork.call_args_list)

        with patch("catfish.talents._catalog", return_value={key: "특성" for key in catalog}):
            short_data = render_builds(self.snapshot, self.hero, [build])
        with Image.open(BytesIO(data)) as long_image, Image.open(BytesIO(short_data)) as short_image:
            self.assertGreater(long_image.height, short_image.height)
            self.assertLess(long_image.height, 500)

    def test_recommended_builds_show_both_ranking_labels_and_their_statistics(self):
        builds = [
            {"games_played": 42, "win_rate": 71.43, "recommendation_labels": ("승률 1위",)},
            {"games_played": 1234, "win_rate": 59.72, "recommendation_labels": ("선택 수 1위",)},
        ]
        with patch("catfish.render._text", wraps=_text) as text:
            data = render_builds(self.snapshot, self.hero, builds, min_games=100)
        self.assert_png(data, minimum_height=350)
        labels = [str(call.args[2]) for call in text.call_args_list]
        for label in ("길 잃은 바이킹", "무작위 영웅 대전", "승률 1위", "선택 수 1위",
                      "승률 71.43% · 42게임", "승률 59.72% · 1,234게임"):
            self.assertIn(label, labels)
        self.assertEqual(labels.count("20레벨"), 2)
        self.assertNotIn("최소 100게임", labels)
        self.assertFalse(any(term in label for label in labels
                             for term in ("CATFISH", "SOURCE", "수집", "패치", "선택 수 =", "선택률")))
        with Image.open(BytesIO(data)) as image:
            self.assertLess(image.height, 700)

    def test_same_recommended_build_keeps_both_labels_on_one_card(self):
        build = {"games_played": 2345, "win_rate": 58.35, "recommendation_labels": ("승률 1위", "선택 수 1위")}
        with patch("catfish.render._text", wraps=_text) as text:
            data = render_builds(self.snapshot, self.hero, [build])
        self.assert_png(data, minimum_height=200)
        labels = [str(call.args[2]) for call in text.call_args_list]
        self.assertIn("승률 1위 · 선택 수 1위", labels)
        self.assertEqual(labels.count("20레벨"), 1)
        self.assertEqual(labels.count("승률 58.35% · 2,345게임"), 1)
        with Image.open(BytesIO(data)) as image:
            self.assertLess(image.height, 500)

    def test_empty_data_still_produces_valid_cards(self):
        self.assert_png(render_chart(self.snapshot, []))
        self.assert_png(render_builds(self.snapshot, self.hero, []), minimum_height=150)

    def test_capture_time_is_korean_local_time(self):
        self.assertEqual(_capture_label(self.snapshot), "2026.09.27 09:12 KST")

    def test_corrupt_asset_does_not_break_card(self):
        with tempfile.TemporaryDirectory() as directory:
            invalid = Path(directory) / "broken.png"
            invalid.write_bytes(b"not an image")
            self.snapshot["_data_dir"] = directory
            self.snapshot["assets"]["portrait:lostvikings"] = invalid.name
            self.assert_png(render_chart(self.snapshot, [self.hero]))

    def test_asset_paths_cannot_escape_the_data_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_dir = root / "data"
            data_dir.mkdir()
            (root / "outside.png").write_bytes(b"not an image")
            self.snapshot["_data_dir"] = str(data_dir)
            self.snapshot["assets"] = {"icon": "../outside.png"}
            self.assertIsNone(_asset_path(self.snapshot, "icon"))


if __name__ == "__main__":
    unittest.main()
