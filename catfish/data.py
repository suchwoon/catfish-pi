"""Queries on imported snapshots. Never combine patches or invent missing modes."""

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .heroes import display_name, normalize, search_terms

ROOT = Path(__file__).resolve().parent.parent
MODES = {"standard": "빠른 대전 & 영웅 리그", "aram": "무작위 영웅 대전"}
SORTS = {"win_rate": "승률", "games_played": "게임 수"}
TIER_THRESHOLDS = {"S": 55.0, "A": 52.0, "B": 48.0, "C": 45.0, "D": 0.0}
PAGE_SIZE = 15
LEVEL_KEYS = (
    "level_one", "level_four", "level_seven", "level_ten",
    "level_thirteen", "level_sixteen", "level_twenty",
)


class QueryError(ValueError):
    """A readable error that can be sent to the requesting Discord user."""


class DataStore:
    def __init__(self, directory: Path = ROOT / "data"):
        self.directory = Path(directory).resolve()

    def snapshot(self, mode: str) -> dict:
        if mode not in MODES:
            raise QueryError("게임 모드를 다시 선택해 주세요.")
        path = self.directory / f"{mode}.json"
        if not path.is_file():
            raise QueryError(
                f"{MODES[mode]} 데이터가 아직 없습니다. 해당 모드의 HAR 파일을 imports에 넣고 "
                "가져오기를 실행해 주세요. 현재는 가져온 모드만 조회할 수 있습니다."
            )
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
            if snapshot.get("schema_version") != 1 or snapshot.get("mode") != mode:
                raise ValueError("Invalid snapshot schema")
            if not isinstance(snapshot.get("heroes"), list) or not snapshot["heroes"]:
                raise ValueError("Empty hero data")
            if not isinstance(snapshot.get("builds"), dict):
                raise ValueError("Invalid build data")
            for hero in snapshot["heroes"]:
                hero["name_ko"] = display_name(hero)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            raise QueryError("가져온 데이터 파일을 읽을 수 없습니다. HAR 가져오기를 다시 실행해 주세요.") from exc
        snapshot["_data_dir"] = str(self.directory)
        return snapshot

    def available(self) -> list[dict]:
        return [self.snapshot(mode) for mode in MODES if (self.directory / f"{mode}.json").is_file()]


def _validate_query(sort_by: str, min_games: int) -> None:
    if sort_by not in SORTS:
        raise QueryError("정렬은 승률 또는 게임 수를 선택해 주세요.")
    if min_games < 0:
        raise QueryError("최소 게임 수는 0 이상이어야 합니다.")


def chart_rows(snapshot: dict, sort_by: str = "win_rate", min_games: int = 0) -> list[dict]:
    _validate_query(sort_by, min_games)
    rows = [h for h in snapshot["heroes"] if h["games_played"] >= min_games]
    if not rows:
        raise QueryError("최소 게임 수를 만족하는 영웅이 없습니다. 기준을 낮춰 주세요.")
    secondary = "games_played" if sort_by == "win_rate" else "win_rate"
    return sorted(rows, key=lambda h: (-h[sort_by], -h[secondary], h["short_name"]))


def chart_page(rows: list[dict], page: int = 1) -> tuple[list[dict], int]:
    pages = max(1, math.ceil(len(rows) / PAGE_SIZE))
    if page < 1 or page > pages:
        raise QueryError(f"페이지는 1~{pages} 사이로 입력해 주세요.")
    return rows[(page - 1) * PAGE_SIZE:page * PAGE_SIZE], pages


def hero_tier(hero: dict) -> str:
    """Classify the hero's overall win rate in the selected mode."""
    return next((name for name, minimum in TIER_THRESHOLDS.items()
                 if hero["win_rate"] >= minimum), "D")


def tier_rows(snapshot: dict) -> dict[str, list[dict]]:
    """Group every imported hero by win rate, preserving rank within each tier."""
    tiers = {tier: [] for tier in TIER_THRESHOLDS}
    for hero in chart_rows(snapshot):
        tiers[hero_tier(hero)].append(hero)
    return tiers


def find_hero(snapshot: dict, query: str) -> dict:
    term = normalize(query)
    if not term:
        raise QueryError("영웅 이름을 입력해 주세요.")
    exact = [h for h in snapshot["heroes"] if term in search_terms(h)]
    if len(exact) == 1:
        return exact[0]
    partial = [h for h in snapshot["heroes"] if any(term in t for t in search_terms(h))]
    if len(partial) == 1:
        return partial[0]
    if partial:
        names = ", ".join(display_name(h) for h in partial[:8])
        raise QueryError(f"여러 영웅이 검색됐습니다: {names}. 영웅 이름을 더 정확하게 입력해 주세요.")
    raise QueryError("해당 영웅이 이 모드의 데이터에 없습니다. 영웅 이름을 확인해 주세요.")


def top_builds(snapshot: dict, hero: dict, sort_by: str = "games_played", min_games: int = 0) -> list[dict]:
    _validate_query(sort_by, min_games)
    raw = snapshot["builds"].get(hero["short_name"], [])
    if not raw:
        raise QueryError(f"{display_name(hero)}의 빌드 데이터가 아직 없습니다. 영웅의 빌드 화면도 HAR에 포함해 주세요.")
    # A repeated request/row must not consume two of the three result slots.
    unique = {}
    for build in raw:
        if build["games_played"] >= min_games:
            key = tuple(build[k]["talent_id"] for k in LEVEL_KEYS)
            unique.setdefault(key, build)
    secondary = "games_played" if sort_by == "win_rate" else "win_rate"
    rows = sorted(unique.values(), key=lambda b: (-b[sort_by], -b[secondary]))[:3]
    if not rows:
        raise QueryError("최소 게임 수를 만족하는 빌드가 없습니다. 기준을 낮춰 주세요.")
    return rows


def recommended_builds(snapshot: dict, hero: dict) -> list[dict]:
    """Compare the highest win rate and most used imported build candidates."""
    recommendations = {}
    for sort_by, label in (("win_rate", "승률 1위"), ("games_played", "선택 수 1위")):
        build = top_builds(snapshot, hero, sort_by)[0]
        key = tuple(build[field]["talent_id"] for field in LEVEL_KEYS)
        if key not in recommendations:
            recommendations[key] = {**build, "recommendation_labels": ()}
        recommendations[key]["recommendation_labels"] += (label,)
    return list(recommendations.values())


def captured_label(snapshot: dict) -> str:
    dt = datetime.fromisoformat(snapshot["captured_at"].replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M KST")


def source_note(snapshot: dict) -> str:
    patches = ", ".join(snapshot["filters"].get("timeframe", [])) or "미지정"
    return f"수집 {captured_label(snapshot)} · 패치 {patches} · Heroes Profile 저장 데이터"
