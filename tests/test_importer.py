import base64
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from catfish.__main__ import main as catfish_main
from catfish.data import QueryError, recommended_builds, top_builds
from catfish.importer import LEVEL_KEYS, import_har, import_hars, main as importer_main


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/lGkAAAAASUVORK5CYII="
)
BASE_FILTERS = {"game_type": ["ar"], "timeframe": ["patch-1"],
                "timeframe_type": "minor", "mirror": "0", "region": None,
                "statfilter": "win_rate", "groupsize": []}
HERO = {"hero_id": 7, "name": "Azmodan", "short_name": "azmodan",
        "role": "Ranged Assassin", "games_played": 100, "wins": 60,
        "losses": 40, "win_rate": 60}


def filters(**overrides):
    return {**deepcopy(BASE_FILTERS), **overrides}


def build(games=10, win_rate=70, *, talent_start=1):
    row = {"hero": {"id": 7, "name": "Azmodan", "short_name": "azmodan"},
           "games_played": games, "win_rate": win_rate,
           "buildData": {"wins": 7, "losses": 3}}
    for index, key in enumerate(LEVEL_KEYS):
        row[key] = {"talent_id": index + talent_start, "title": "Talent", "icon": "talent.png",
                    "sort": "1", "level": [1, 4, 7, 10, 13, 16, 20][index]}
    return row


def entry(route, payload, request_filters=None, *, minute=0, status=200, encoded=False):
    body = json.dumps(payload)
    content = {"mimeType": "application/json", "text": body}
    if encoded:
        content.update(text=base64.b64encode(body.encode()).decode(), encoding="base64")
    request = {"url": "https://www.heroesprofile.com" + route,
               "headers": [{"name": "Authorization", "value": "DO_NOT_EXPORT"}],
               "cookies": [{"name": "session", "value": "DO_NOT_EXPORT"}]}
    if request_filters is not None:
        request["postData"] = {"text": json.dumps(request_filters)}
    return {"startedDateTime": f"2026-09-27T01:{minute:02d}:00Z", "request": request,
            "response": {"status": status, "content": content}}


def image_entry(route, content=PNG):
    result = entry(route, None)
    result["response"]["content"] = {"mimeType": "image/png", "encoding": "base64",
                                      "text": base64.b64encode(content).decode()}
    return result


class ImporterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "data"

    def import_entries(self, entries, name="input.har"):
        return import_har(self.write_entries(entries, name), self.output)

    def write_entries(self, entries, name="input.har"):
        source = self.root / name
        source.write_text(json.dumps({"log": {"entries": entries}}))
        return source

    def snapshot(self, mode="aram"):
        return json.loads((self.output / f"{mode}.json").read_text())

    def test_async_join_exports_only_required_assets_and_safe_data(self):
        result = self.import_entries([
            entry("/api/v1/global/hero", {"data": [HERO]}, filters(), encoded=True),
            entry("/api/v1/global/status/job-a", [build()], minute=2),
            entry("/api/v1/global/talents/build", {"async": True, "job_id": "job-a"},
                  filters(hero="Azmodan", talentbuildtype="HP Algorithm"), minute=1, status=202),
            image_entry("/images/heroes/azmodan.png"),
            image_entry("/images/heroes/circular/azmodan.png", PNG + b"circular"),
            image_entry("/images/talents/talent.png"),
            image_entry("/images/talents/unrelated.png"),
        ])
        snapshot = self.snapshot()
        self.assertEqual(result[0]["build_count"], 1)
        self.assertEqual(snapshot["builds"]["azmodan"][0]["games_played"], 10)
        self.assertEqual(snapshot["build_filters"]["azmodan"]["talentbuildtype"], "HP Algorithm")
        self.assertEqual(snapshot["assets"]["portrait:azmodan"], "assets/heroes/azmodan.png")
        self.assertEqual((self.output / "assets/heroes/azmodan.png").read_bytes(), PNG)
        self.assertFalse((self.output / "assets/talents/unrelated.png").exists())
        self.assertEqual(snapshot["warnings"], [])
        self.assertNotIn("DO_NOT_EXPORT", json.dumps(snapshot))
        self.assertNotIn("https://", json.dumps(snapshot))

    def test_modes_and_population_filters_are_not_combined(self):
        entries = [
            entry("/api/v1/global/hero", {"data": [HERO]}, filters()),
            entry("/api/v1/global/hero", {"data": [HERO]}, filters(game_type=["sl", "qm"])),
            entry("/api/v1/global/talents/build", [build(11)], filters(hero="Azmodan")),
            entry("/api/v1/global/talents/build", [build(22)], filters(hero="Azmodan", game_type=["qm", "sl"])),
            entry("/api/v1/global/talents/build", [build(33)], filters(hero="Azmodan", timeframe=["patch-2"]), minute=2),
            entry("/api/v1/global/talents/build", [build(44)], filters(hero="Azmodan", region=[1]), minute=3),
            entry("/api/v1/global/talents/build", [build(55)], filters(hero="Azmodan", game_type=["qm"]), minute=4),
        ]
        summaries = self.import_entries(entries)
        self.assertEqual({item["mode"] for item in summaries}, {"aram", "standard"})
        self.assertEqual(self.snapshot()["builds"]["azmodan"][0]["games_played"], 11)
        self.assertEqual(self.snapshot("standard")["builds"]["azmodan"][0]["games_played"], 22)

    def test_latest_stats_and_duplicate_requests_keep_latest_compatible_build(self):
        latest_filters = filters(timeframe=["patch-2"])
        self.import_entries([
            entry("/api/v1/global/hero", {"data": [HERO]}, filters(), minute=0),
            entry("/api/v1/global/talents/build", [build(99)], filters(hero="Azmodan"), minute=9),
            entry("/api/v1/global/hero", {"data": [{**HERO, "games_played": 200}]}, latest_filters, minute=4),
            entry("/api/v1/global/talents/build", [build(20)], {**latest_filters, "hero": "Azmodan"}, minute=5),
            entry("/api/v1/global/talents/build", [build(30), build(30)], {**latest_filters, "hero": "Azmodan"}, minute=6),
            entry("/api/v1/global/talents/build", [build(25)], {**latest_filters, "hero": "Azmodan"}, minute=3),
        ])
        snapshot = self.snapshot()
        self.assertEqual(snapshot["filters"]["timeframe"], ["patch-2"])
        self.assertEqual(snapshot["heroes"][0]["games_played"], 200)
        self.assertEqual(len(snapshot["builds"]["azmodan"]), 1)
        self.assertEqual(snapshot["builds"]["azmodan"][0]["games_played"], 30)

    def test_older_file_cannot_replace_a_newer_saved_snapshot(self):
        self.import_entries([entry("/api/v1/global/hero", {"data": [HERO]}, filters(), minute=5)])
        previous = (self.output / "aram.json").read_bytes()
        summaries = self.import_entries([entry("/api/v1/global/hero", {"data": [HERO]}, filters(), minute=1)], "older.har")
        self.assertEqual(summaries[0]["status"], "skipped")
        self.assertEqual((self.output / "aram.json").read_bytes(), previous)

    def test_popular_stats_override_duplicates_regardless_of_order_or_filename(self):
        algorithm = build(800, 98)
        algorithm["popularity"] = 80
        popular = build(50, 45)
        popular["popularity"] = 5
        # Sharing the first six talents still leaves two distinct builds.
        algorithm_only = build(100, 65)
        algorithm_only["level_twenty"]["talent_id"] = 107
        popular_only = build(300, 60, talent_start=21)
        algorithm_entries = [
            entry("/api/v1/global/hero", {"data": [{**HERO, "games_played": 200}]},
                  filters(), minute=5),
            entry("/api/v1/global/talents/build", [algorithm, algorithm_only],
                  filters(hero="Azmodan", talentbuildtype="HP Algorithm"), minute=9),
        ]
        popular_entries = [
            entry("/api/v1/global/hero", {"data": [HERO]}, filters()),
            entry("/api/v1/global/talents/build", [popular, popular_only],
                  filters(hero="Azmodan", talentbuildtype="Popular"), minute=1),
        ]
        expected = {
            tuple(row[key]["talent_id"] for key in LEVEL_KEYS): row
            for row in (popular, algorithm_only, popular_only)
        }
        for separate_files in (False, True):
            for reverse in (False, True):
                with self.subTest(separate_files=separate_files, reverse=reverse):
                    output = self.root / f"merged-{separate_files}-{reverse}"
                    if separate_files:
                        # Request metadata determines precedence, even with swapped filenames.
                        paths = [
                            self.write_entries(algorithm_entries, "heroesprofile-ar-popular.har"),
                            self.write_entries(popular_entries, "heroesprofile-ar.har"),
                        ]
                        if reverse:
                            paths.reverse()
                        summaries = import_hars(paths, output)
                    else:
                        entries = algorithm_entries + popular_entries
                        if reverse:
                            entries.reverse()
                        summaries = import_har(self.write_entries(entries), output)
                    snapshot = json.loads((output / "aram.json").read_text())
                    rows = snapshot["builds"]["azmodan"]
                    actual = {tuple(row[key]["talent_id"] for key in LEVEL_KEYS): row
                              for row in rows}
                    self.assertEqual(len(rows), 3)
                    self.assertEqual(actual, expected)
                    self.assertEqual(summaries[0]["build_count"], 3)
                    self.assertEqual(snapshot["heroes"][0]["games_played"], 200)
                    self.assertEqual(snapshot["build_filters"]["azmodan"]["talentbuildtype"],
                                     "Popular")

                    hero = snapshot["heroes"][0]
                    self.assertEqual(top_builds(snapshot, hero),
                                     [popular_only, algorithm_only, popular])
                    self.assertEqual(top_builds(snapshot, hero, "win_rate"),
                                     [algorithm_only, popular_only, popular])
                    self.assertEqual(top_builds(snapshot, hero, min_games=60),
                                     [popular_only, algorithm_only])
                    with self.assertRaises(QueryError):
                        top_builds(snapshot, hero, min_games=500)
                    self.assertEqual(recommended_builds(snapshot, hero), [
                        {**algorithm_only, "recommendation_labels": ("승률 1위",)},
                        {**popular_only, "recommendation_labels": ("선택 수 1위",)},
                    ])

    def test_latest_response_per_build_type_replaces_that_types_old_candidates(self):
        old = self.write_entries([
            entry("/api/v1/global/hero", {"data": [HERO]}, filters()),
            entry("/api/v1/global/talents/build", [build(900, talent_start=41)],
                  filters(hero="Azmodan", talentbuildtype="HP Algorithm"), minute=1),
            entry("/api/v1/global/talents/build", [build(20), build(800, talent_start=31)],
                  filters(hero="Azmodan", talentbuildtype="Popular"), minute=3),
        ], "old.har")
        popular = build(30, 40)
        algorithm_only = build(40, 65, talent_start=11)
        latest = self.write_entries([
            entry("/api/v1/global/talents/build", [popular],
                  filters(hero="Azmodan", talentbuildtype="Popular"), minute=4),
            entry("/api/v1/global/talents/build", [build(90, 99), algorithm_only],
                  filters(hero="Azmodan", talentbuildtype="HP Algorithm"), minute=5),
        ], "latest.har")
        for paths in ([old, latest], [latest, old]):
            with self.subTest(paths=[path.name for path in paths]):
                import_hars(paths, self.output)
                self.assertCountEqual(self.snapshot()["builds"]["azmodan"],
                                      [popular, algorithm_only])

    def test_async_build_jobs_remain_associated_with_their_own_capture(self):
        algorithm = self.write_entries([
            entry("/api/v1/global/hero", {"data": [HERO]}, filters()),
            entry("/api/v1/global/talents/build", {"job_id": "same-job-id"},
                  filters(hero="Azmodan", talentbuildtype="HP Algorithm"), minute=5, status=202),
            entry("/api/v1/global/status/same-job-id", [build(900), build(80, talent_start=11)],
                  minute=6),
        ], "algorithm.har")
        popular = self.write_entries([
            entry("/api/v1/global/status/same-job-id", [build(30, 40)], minute=2),
            entry("/api/v1/global/talents/build", {"job_id": "same-job-id"},
                  filters(hero="Azmodan", talentbuildtype="Popular"), minute=1, status=202),
        ], "popular.har")
        import_hars([popular, algorithm], self.output)
        self.assertCountEqual(self.snapshot()["builds"]["azmodan"],
                              [build(30, 40), build(80, talent_start=11)])

    def test_import_commands_combine_explicit_and_default_files_in_one_batch(self):
        imports = self.root / "imports"
        imports.mkdir()
        algorithm = self.write_entries([
            entry("/api/v1/global/hero", {"data": [HERO]}, filters()),
            entry("/api/v1/global/talents/build", [build(900), build(80, talent_start=11)],
                  filters(hero="Azmodan", talentbuildtype="HP Algorithm"), minute=5),
        ], "imports/algorithm.har")
        popular = self.write_entries([
            entry("/api/v1/global/talents/build", [build(30, 40)],
                  filters(hero="Azmodan", talentbuildtype="Popular"), minute=1),
        ], "imports/popular.har")
        for command in ("importer", "explicit", "default"):
            with self.subTest(command=command), redirect_stdout(io.StringIO()):
                output = self.root / f"cli-{command}"
                if command == "importer":
                    self.assertEqual(importer_main([str(algorithm), str(popular),
                                                    "--output", str(output)]), 0)
                else:
                    argv = ["catfish", "--data-dir", str(output), "import"]
                    if command == "explicit":
                        argv.extend([str(algorithm), str(popular)])
                    with patch("catfish.__main__.ROOT", self.root), patch("sys.argv", argv):
                        catfish_main()
                snapshot = json.loads((output / "aram.json").read_text())
                self.assertCountEqual(snapshot["builds"]["azmodan"],
                                      [build(30, 40), build(80, talent_start=11)])

    def test_batch_builds_must_match_latest_hero_population_and_mode(self):
        current = filters(timeframe=["patch-2"], region=[1])
        stats = self.write_entries([
            entry("/api/v1/global/hero", {"data": [{**HERO, "games_played": 200}]},
                  current, minute=10),
            entry("/api/v1/global/hero", {"data": [HERO]},
                  filters(game_type=["sl", "qm"]), minute=9),
            entry("/api/v1/global/talents/build", [build(11)],
                  {**current, "hero": "Azmodan", "talentbuildtype": "HP Algorithm"}, minute=11),
        ], "stats.har")
        candidates = self.write_entries([
            entry("/api/v1/global/hero", {"data": [HERO]}, filters()),
            entry("/api/v1/global/talents/build", [build(22), build(33, talent_start=11)],
                  {**current, "hero": "Azmodan", "talentbuildtype": "Popular"}, minute=8),
            entry("/api/v1/global/talents/build", [build(44)],
                  filters(hero="Azmodan", talentbuildtype="Popular", region=[1]), minute=30),
            entry("/api/v1/global/talents/build", [build(55)],
                  filters(hero="Azmodan", talentbuildtype="Popular", timeframe=["patch-2"]),
                  minute=31),
            entry("/api/v1/global/talents/build", [build(66)],
                  filters(hero="Azmodan", talentbuildtype="Popular", game_type=["qm", "sl"]),
                  minute=32),
            entry("/api/v1/global/talents/build", [build(77)],
                  {**current, "hero": "Azmodan", "talentbuildtype": "Popular", "game_type": ["qm"]},
                  minute=33),
        ], "candidates.har")
        for paths in ([stats, candidates], [candidates, stats]):
            with self.subTest(paths=[path.name for path in paths]):
                import_hars(paths, self.output)
                self.assertEqual(self.snapshot()["heroes"][0]["games_played"], 200)
                self.assertEqual(self.snapshot()["filters"], current)
                self.assertCountEqual(self.snapshot()["builds"]["azmodan"],
                                      [build(22), build(33, talent_start=11)])
                self.assertEqual(self.snapshot("standard")["builds"]["azmodan"], [build(66)])

    def test_new_batch_does_not_reuse_builds_from_a_saved_snapshot(self):
        self.import_entries([
            entry("/api/v1/global/hero", {"data": [HERO]}, filters()),
            entry("/api/v1/global/talents/build", [build(900, talent_start=21)],
                  filters(hero="Azmodan", talentbuildtype="Popular"), minute=1),
        ])
        source = self.write_entries([
            entry("/api/v1/global/hero", {"data": [HERO]}, filters(), minute=5),
            entry("/api/v1/global/talents/build", [build(20)],
                  filters(hero="Azmodan", talentbuildtype="HP Algorithm"), minute=6),
        ], "new.har")
        import_hars([source], self.output)
        self.assertEqual(self.snapshot()["builds"]["azmodan"], [build(20)])

    def test_older_batch_keeps_newer_saved_snapshot_and_assets(self):
        self.import_entries([
            entry("/api/v1/global/hero", {"data": [HERO]}, filters(), minute=10),
            image_entry("/images/heroes/azmodan.png"),
        ])
        snapshot_path = self.output / "aram.json"
        asset_path = self.output / "assets/heroes/azmodan.png"
        previous = snapshot_path.read_bytes()
        stats = self.write_entries([
            entry("/api/v1/global/hero", {"data": [HERO]}, filters(), minute=1),
            image_entry("/images/heroes/azmodan.png", PNG + b"older"),
        ], "older-stats.har")
        popular = self.write_entries([
            entry("/api/v1/global/talents/build", [build(500)],
                  filters(hero="Azmodan", talentbuildtype="Popular"), minute=20),
        ], "older-popular.har")
        summaries = import_hars([stats, popular], self.output)
        self.assertEqual(summaries[0]["status"], "skipped")
        self.assertEqual(snapshot_path.read_bytes(), previous)
        self.assertEqual(asset_path.read_bytes(), PNG)

    def test_missing_bodies_and_unfinished_jobs_produce_visible_warnings(self):
        absent = entry("/api/v1/global/talents/build", [build()], filters(hero="Azmodan"))
        del absent["response"]["content"]["text"]
        self.import_entries([
            entry("/api/v1/global/hero", {"data": [HERO]}, filters()), absent,
            entry("/api/v1/global/talents/build", {"job_id": "unfinished"}, filters(hero="Azmodan"), status=202),
        ])
        snapshot = self.snapshot()
        self.assertEqual(snapshot["builds"], {})
        warnings = " ".join(snapshot["warnings"])
        self.assertIn("body is missing", warnings)
        self.assertIn("pending build job", warnings)
        self.assertIn("no compatible build data", warnings)

    def test_legacy_combined_standard_mode_is_supported(self):
        self.import_entries([entry("/api/v1/global/hero", {"data": [HERO]}, filters(game_type=["qm", "hl"]))])
        self.assertEqual(self.snapshot("standard")["mode"], "standard")
        self.assertFalse((self.output / "aram.json").exists())

    def test_har_without_supported_stats_fails_without_creating_a_snapshot(self):
        with self.assertRaisesRegex(ValueError, "No usable hero snapshot"):
            self.import_entries([entry("/api/v1/global/hero", {"data": [HERO]}, filters(game_type=["qm"]))])
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
