"""Extract the captured Heroes Profile snapshot and its icons without network calls."""

from __future__ import annotations

import argparse
import base64
import binascii
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import sys
import tempfile
from typing import Any
from urllib.parse import urlsplit


LEVEL_KEYS = (
    "level_one", "level_four", "level_seven", "level_ten", "level_thirteen",
    "level_sixteen", "level_twenty",
)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_NAME = re.compile(r"[A-Za-z0-9_.-]+\.png\Z")
_SLUG = re.compile(r"[A-Za-z0-9_-]+\Z")
_API = "/api/v1/global/"


@dataclass
class _Capture:
    source_file: str
    stats: dict[str, tuple[datetime, str, dict[str, Any], list[dict[str, Any]]]]
    candidates: list[tuple[datetime, dict[str, Any], Any]]
    image_entries: dict[str, dict[str, Any]]
    warnings: list[str]


def _instant(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _mode(filters: dict[str, Any]) -> str | None:
    modes = filters.get("game_type")
    if not isinstance(modes, list):
        return None
    if not all(isinstance(mode, str) for mode in modes):
        return None
    values = set(modes)
    if values == {"ar"}:
        return "aram"
    if values in ({"qm", "sl"}, {"qm", "hl"}):
        return "standard"
    return None


def _population(filters: dict[str, Any]) -> str:
    """Ignore display/target fields, but preserve every nonempty population filter."""
    ignored = {"hero", "statfilter", "talentbuildtype"}
    normalized: dict[str, Any] = {}
    for key, value in filters.items():
        if key in ignored or value is None or value == [] or value == "":
            continue
        if isinstance(value, list):
            value = sorted(value, key=lambda item: json.dumps(item, sort_keys=True))
        normalized[key] = value
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"))


def _body(entry: dict[str, Any]) -> bytes:
    content = entry.get("response", {}).get("content", {})
    text = content.get("text")
    if not isinstance(text, str) or not text:
        raise ValueError("response body is missing")
    if content.get("encoding") == "base64":
        try:
            return base64.b64decode(text, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError("response body has invalid base64") from error
    return text.encode("utf-8")


def _request_filters(entry: dict[str, Any]) -> dict[str, Any]:
    text = entry.get("request", {}).get("postData", {}).get("text", "")
    result = json.loads(text)
    if not isinstance(result, dict):
        raise ValueError("request filters are not an object")
    return result


def _number(value: Any) -> bool:
    return (isinstance(value, (float, int)) and not isinstance(value, bool)
            and math.isfinite(value))


def _valid_counts(row: dict[str, Any]) -> bool:
    games, rate = row.get("games_played"), row.get("win_rate")
    return (_number(games) and games >= 0 and int(games) == games
            and _number(rate) and 0 <= rate <= 100)


def _hero_rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("hero response does not contain a data array")
    result: dict[str, dict[str, Any]] = {}
    for row in payload["data"]:
        if (not isinstance(row, dict) or not isinstance(row.get("name"), str)
                or not isinstance(row.get("short_name"), str)
                or not _SLUG.fullmatch(row["short_name"]) or not _valid_counts(row)):
            raise ValueError("hero response contains an invalid hero row")
        result[row["short_name"]] = row
    if not result:
        raise ValueError("hero response has no hero rows")
    return list(result.values())


def _build_rows(payload: Any, filters: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(payload, list) or not payload:
        raise ValueError("build response has no build rows")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    slug = None
    for row in payload:
        if not isinstance(row, dict) or not isinstance(row.get("hero"), dict):
            raise ValueError("build response contains an invalid hero")
        hero = row["hero"]
        current = hero.get("short_name")
        if not isinstance(current, str) or not _SLUG.fullmatch(current):
            raise ValueError("build response contains an invalid hero identifier")
        if slug is not None and current != slug:
            raise ValueError("build response mixes heroes")
        slug = current
        if filters.get("hero") not in (hero.get("name"), current, hero.get("alt_name")):
            raise ValueError("build hero does not match the original request")
        if not _valid_counts(row):
            raise ValueError("build response contains invalid counts")
        for key in LEVEL_KEYS:
            talent = row.get(key)
            if (not isinstance(talent, dict) or not isinstance(talent.get("icon"), str)
                    or not _PNG_NAME.fullmatch(talent["icon"])
                    or not isinstance(talent.get("talent_id"), (int, str))
                    or isinstance(talent["talent_id"], bool)
                    or talent["talent_id"] == ""):
                raise ValueError("build response contains a missing or invalid talent")
        fingerprint = json.dumps(row, sort_keys=True)
        if fingerprint not in seen:
            result.append(row)
            seen.add(fingerprint)
    return slug, result  # type: ignore[return-value]


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _read_har(path: Path) -> _Capture:
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
        entries = document["log"]["entries"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise ValueError("Not a valid HAR with log.entries") from error
    if not isinstance(entries, list):
        raise ValueError("HAR log.entries must be an array")

    warnings: list[str] = []
    stats: dict[str, tuple[datetime, str, dict[str, Any], list[dict[str, Any]]]] = {}
    jobs: dict[str, dict[str, Any]] = {}
    candidates: list[tuple[datetime, dict[str, Any], Any]] = []
    status_results: list[tuple[datetime, str, Any]] = []
    image_entries: dict[str, dict[str, Any]] = {}
    unsupported: set[str] = set()

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        request = entry.get("request", {})
        try:
            url = urlsplit(request.get("url", ""))
        except ValueError:
            continue
        if url.hostname not in {"heroesprofile.com", "www.heroesprofile.com"}:
            continue
        route = url.path
        response_status = entry.get("response", {}).get("status", 0)
        if (route.startswith("/images/talents/") or route.startswith("/images/heroes/")):
            if response_status == 200:
                image_entries[route] = entry
            continue
        if route not in {_API + "hero", _API + "talents/build"} and not route.startswith(_API + "status/"):
            continue
        label = "hero" if route.endswith("/hero") else "build"
        if response_status not in {200, 202}:
            warnings.append(f"Entry {index}: {label} response HTTP {response_status} was skipped.")
            continue
        try:
            capture = entry.get("startedDateTime", "")
            moment = _instant(capture)
            payload = json.loads(_body(entry))
            if route.startswith(_API + "status/"):
                if isinstance(payload, list):
                    status_results.append((moment, route.rsplit("/", 1)[-1], payload))
                continue
            filters = _request_filters(entry)
            mode = _mode(filters)
            if mode is None:
                unsupported.add(json.dumps(filters.get("game_type"), ensure_ascii=True))
                continue
            if route.endswith("/hero"):
                rows = _hero_rows(payload)
                if mode not in stats or moment >= stats[mode][0]:
                    stats[mode] = moment, capture, filters, rows
            elif response_status == 202:
                if not isinstance(payload, dict) or not isinstance(payload.get("job_id"), str):
                    raise ValueError("pending build response has no job ID")
                jobs[payload["job_id"]] = filters
            else:
                candidates.append((moment, filters, payload))
        except (ValueError, TypeError, UnicodeError, OverflowError) as error:
            # Do not expose response or request contents in errors.
            reason = str(error) if not isinstance(error, json.JSONDecodeError) else "invalid JSON"
            warnings.append(f"Entry {index}: {label} data was skipped ({reason}).")

    for modes in sorted(unsupported):
        warnings.append(f"Unsupported game_type {modes} was skipped; standard requires qm + sl (or qm + hl).")
    resolved_jobs: set[str] = set()
    for moment, job_id, payload in status_results:
        if job_id in jobs:
            candidates.append((moment, jobs[job_id], payload))
            resolved_jobs.add(job_id)
    if len(jobs) != len(resolved_jobs):
        warnings.append(f"{len(jobs) - len(resolved_jobs)} pending build job(s) have no captured completed response.")
    return _Capture(path.name, stats, candidates, image_entries, warnings)


def import_har(path: Path, output_dir: Path) -> list[dict[str, Any]]:
    """Import a single HAR; use import_hars to compare candidates across files."""
    return import_hars([path], output_dir)


def import_hars(paths: list[Path], output_dir: Path) -> list[dict[str, Any]]:
    """Combine compatible candidates from the supplied HARs into each mode snapshot.

    Keep the latest response per hero/build type and prefer Popular statistics for
    identical talents. Saved snapshots supply cached images, never old candidates.
    Raw HAR headers, cookies, request URLs, and unrelated responses are never saved.
    """
    output_dir = Path(output_dir)
    # Stable file order also resolves equal timestamps independently of CLI order.
    captures = [_read_har(path) for path in sorted({Path(path) for path in paths})]
    warnings = [warning for capture in captures for warning in capture.warnings]
    stats = {}
    image_entries = {}
    for source in captures:
        image_entries.update(source.image_entries)
        for mode, stat in source.stats.items():
            if mode not in stats or stat[0] >= stats[mode][0][0]:
                stats[mode] = stat, source.source_file
    if not stats:
        details = " ".join(warnings[:4])
        raise ValueError(f"No usable hero snapshot for aram or combined standard mode was found. {details}".strip())

    summaries = []
    for mode, ((moment, capture, filters, heroes), source_file) in sorted(stats.items()):
        snapshot_warnings = list(warnings)
        destination = output_dir / f"{mode}.json"
        if destination.exists():
            try:
                existing = json.loads(destination.read_text(encoding="utf-8"))
                if _instant(existing["captured_at"]) > moment:
                    summaries.append({"mode": mode, "status": "skipped", "source_file": source_file,
                                      "captured_at": capture, "warnings": [
                                          *snapshot_warnings, "A newer saved snapshot was kept."]})
                    continue
            except (ValueError, KeyError, TypeError):
                snapshot_warnings.append("The previous saved snapshot was unreadable and was replaced.")

        population = _population(filters)
        hero_slugs = {hero["short_name"] for hero in heroes}
        selected: dict[tuple[str, str], tuple[datetime, dict[str, Any], list[dict[str, Any]], str]] = {}
        for source in captures:
            for build_moment, build_filters, payload in source.candidates:
                if _mode(build_filters) != mode or _population(build_filters) != population:
                    continue
                try:
                    slug, rows = _build_rows(payload, build_filters)
                    build_type = build_filters.get("talentbuildtype") or "HP Algorithm"
                    if not isinstance(build_type, str):
                        raise ValueError("build type is invalid")
                    key = slug, build_type
                    if slug in hero_slugs and (key not in selected or build_moment >= selected[key][0]):
                        selected[key] = build_moment, build_filters, rows, source.source_file
                except (ValueError, TypeError) as error:
                    snapshot_warnings.append(f"A compatible build response was skipped ({error}).")

        unique: dict[str, dict[tuple, dict[str, Any]]] = {}
        build_filters = {}
        build_sources: dict[str, list[dict[str, Any]]] = {}
        # Apply Popular last so all of its recorded statistics replace duplicates,
        # even when the algorithm response is newer or reports a higher win rate.
        for (slug, build_type), (build_moment, request_filters, rows, filename) in sorted(
            selected.items(), key=lambda item: (item[0][1] == "Popular", item[1][0], item[0])
        ):
            hero_builds = unique.setdefault(slug, {})
            for row in rows:
                key = tuple(str(row[level]["talent_id"]) for level in LEVEL_KEYS)
                hero_builds[key] = row
            build_filters[slug] = request_filters
            build_sources.setdefault(slug, []).append({
                "source_file": filename, "captured_at": build_moment.isoformat(),
                "filters": request_filters,
            })
        builds = {slug: list(rows.values()) for slug, rows in unique.items()}
        source_files = sorted({source_file, *(value[3] for value in selected.values())})
        missing_builds = sorted(hero_slugs - builds.keys())
        if missing_builds:
            snapshot_warnings.append(f"{len(missing_builds)} hero(es) have no compatible build data: {', '.join(missing_builds)}.")
        required: dict[str, tuple[str, list[str]]] = {}
        for slug in sorted(hero_slugs):
            required[f"portrait:{slug}"] = (
                f"assets/heroes/{slug}.png",
                [f"/images/heroes/{slug}.png", f"/images/heroes/circular/{slug}.png"],
            )
        for rows in builds.values():
            for row in rows:
                for key in LEVEL_KEYS:
                    icon = row[key]["icon"]
                    required[icon] = f"assets/talents/{icon}", [f"/images/talents/{icon}"]
        assets: dict[str, str] = {}
        missing_assets: list[str] = []
        for key, (relative, routes) in sorted(required.items()):
            content = None
            for route in routes:
                if route not in image_entries:
                    continue
                try:
                    candidate = _body(image_entries[route])
                    if candidate.startswith(PNG_SIGNATURE):
                        content = candidate
                        break
                except ValueError:
                    pass
            asset_path = output_dir / relative
            if content is not None:
                _atomic_write(asset_path, content)
                assets[key] = relative
            elif asset_path.exists() and asset_path.read_bytes().startswith(PNG_SIGNATURE):
                assets[key] = relative
            else:
                missing_assets.append(key)
        if missing_assets:
            sample = ", ".join(missing_assets[:3])
            snapshot_warnings.append(f"{len(missing_assets)} image(s) are missing from the capture/cache (examples: {sample}).")

        snapshot = {
            "schema_version": 1, "mode": mode, "captured_at": capture,
            "source_file": source_file, "source_files": source_files, "filters": filters, "heroes": heroes,
            "builds": builds, "build_filters": build_filters,
            "build_sources": build_sources,
            "assets": assets, "warnings": snapshot_warnings,
        }
        _atomic_write(destination, (json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"))
        summaries.append({"mode": mode, "status": "imported", "source_file": source_file,
                          "source_files": source_files,
                          "captured_at": capture, "hero_count": len(heroes),
                          "build_hero_count": len(builds), "build_count": sum(map(len, builds.values())),
                          "asset_count": len(assets), "warnings": snapshot_warnings})
    return summaries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import captured Heroes Profile HAR data and icons locally.")
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent.parent / "data")
    args = parser.parse_args(argv)
    try:
        summaries = import_hars(args.paths, args.output)
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    for summary in summaries:
        print(f"{summary['source_file']}: {summary['mode']} {summary['status']} · {summary['captured_at']}")
        if summary["status"] == "imported":
            print(f"  {summary['hero_count']} heroes · {summary['build_count']} builds "
                  f"({summary['build_hero_count']} heroes) · {summary['asset_count']} images")
        for warning in summary["warnings"]:
            print(f"  Warning: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
