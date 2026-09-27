import base64
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from catfish.importer import LEVEL_KEYS, import_har


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


def build(games=10, win_rate=70):
    row = {"hero": {"id": 7, "name": "Azmodan", "short_name": "azmodan"},
           "games_played": games, "win_rate": win_rate,
           "buildData": {"wins": 7, "losses": 3}}
    for index, key in enumerate(LEVEL_KEYS):
        row[key] = {"talent_id": index + 1, "title": "Talent", "icon": "talent.png",
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
        source = self.root / name
        source.write_text(json.dumps({"log": {"entries": entries}}))
        summaries = import_har(source, self.output)
        return summaries

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
