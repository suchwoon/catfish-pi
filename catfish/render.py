"""Render self-contained Discord image attachments from imported statistics.

Rendering is deliberately independent of Discord and does not make network calls.
All artwork is loaded from the imported asset manifest; missing artwork gets a
legible placeholder so a partially captured HAR can still produce useful cards.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache
from io import BytesIO
from pathlib import Path
import math
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .data import TIER_THRESHOLDS


WIDTH = 1100
TIER_WIDTH = 2560
PAGE_SIZE = 15
BACKGROUND = "#10111E"
PANEL = "#191B2D"
PANEL_ALT = "#1D1F34"
BORDER = "#30344E"
TEXT = "#F1F2FC"
MUTED = "#9299B5"
PURPLE = "#AF92FF"
TEAL = "#69D6C2"
KST = timezone(timedelta(hours=9))
FONT_PATH = Path(__file__).resolve().parent.parent / "assets/fonts/NotoSansKR.ttf"
LEVEL_FIELDS = (
    (1, "level_one"),
    (4, "level_four"),
    (7, "level_seven"),
    (10, "level_ten"),
    (13, "level_thirteen"),
    (16, "level_sixteen"),
    (20, "level_twenty"),
)
ROLE_NAMES = {
    "Tank": "전사",
    "Bruiser": "투사",
    "Ranged Assassin": "원거리 암살자",
    "Melee Assassin": "근접 암살자",
    "Healer": "치유사",
    "Support": "지원가",
}
MODE_NAMES = {"aram": "무작위 영웅 대전", "standard": "빠른 대전 · 영웅 리그"}


@lru_cache(maxsize=64)
def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        font = ImageFont.truetype(str(FONT_PATH), size=size)
        # The bundled Noto Sans KR is a variable font. Each cached size/weight
        # owns its font instance, so rendering never mutates a shared face.
        try:
            font.set_variation_by_axes([700 if bold else 400])
        except (AttributeError, OSError):
            pass
        return font
    except OSError:
        # Deployments should keep assets/fonts. A missing font must not crash
        # the entire interaction, even though fallback Korean coverage varies.
        for name in ("NotoSansCJK-Regular.ttc", "DejaVuSans.ttf"):
            try:
                return ImageFont.truetype(name, size=size)
            except OSError:
                continue
        return ImageFont.load_default(size=size)


def _text(
    draw: ImageDraw.ImageDraw,
    position: tuple[float, float],
    value: Any,
    size: int = 20,
    color: str = TEXT,
    bold: bool = False,
    anchor: str = "lt",
) -> None:
    draw.text(position, str(value), font=_font(size, bold), fill=color, anchor=anchor)


def _fit(value: str, width: float, size: int, bold: bool = False) -> str:
    font = _font(size, bold)
    if font.getlength(value) <= width:
        return value
    while value and font.getlength(value + "…") > width:
        value = value[:-1]
    return value.rstrip() + "…"


def _wrap(value: str, width: float, size: int, max_lines: int = 3) -> list[str]:
    words = value.split()
    lines: list[str] = []
    current = ""
    for index, word in enumerate(words):
        candidate = f"{current} {word}".strip()
        if current and _font(size).getlength(candidate) > width:
            lines.append(current)
            current = word
            if len(lines) == max_lines - 1:
                lines.append(_fit(" ".join(words[index:]), width, size))
                return lines
        else:
            current = candidate
    if current:
        lines.append(_fit(current, width, size))
    return lines[:max_lines]


def _number(value: Any) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else 0.0
    except (ValueError, TypeError):
        return 0.0


def _games(value: Any) -> str:
    return f"{int(_number(value)):,}"


def _rate(value: Any) -> str:
    return f"{_number(value):.2f}%"


def _name(hero: dict) -> str:
    return str(hero.get("name_ko") or hero.get("name") or "알 수 없는 영웅")


def _mode(snapshot: dict) -> str:
    return MODE_NAMES.get(snapshot.get("mode"), str(snapshot.get("mode") or "게임 모드 미상"))


def _capture_label(snapshot: dict) -> str:
    value = str(snapshot.get("captured_at") or "")
    try:
        captured = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if captured.tzinfo is None:
            captured = captured.replace(tzinfo=timezone.utc)
        return captured.astimezone(KST).strftime("%Y.%m.%d %H:%M KST")
    except ValueError:
        return "수집 시각 미상"


def _patch_label(snapshot: dict) -> str:
    filters = snapshot.get("filters") or {}
    patches = filters.get("timeframe") or filters.get("patch") or []
    if isinstance(patches, str):
        patches = [patches]
    return " · ".join(str(patch) for patch in patches) or "패치 정보 없음"


def _asset_path(snapshot: dict, key: str) -> Path | None:
    relative = (snapshot.get("assets") or {}).get(key)
    if not relative or not snapshot.get("_data_dir"):
        return None
    root = Path(snapshot["_data_dir"]).resolve()
    relative_path = Path(str(relative))
    candidates = [root / relative_path]
    # Older manifests included their leading data directory in asset paths.
    if relative_path.parts and relative_path.parts[0] == root.name:
        candidates.append(root.joinpath(*relative_path.parts[1:]))
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate.is_relative_to(root) and candidate.is_file():
            return candidate
    return None


def _artwork(
    image: Image.Image,
    snapshot: dict,
    key: str,
    xy: tuple[int, int],
    size: int,
    placeholder: str = "?",
    radius: int = 10,
) -> None:
    path = _asset_path(snapshot, key)
    artwork: Image.Image | None = None
    if path:
        try:
            with Image.open(path) as source:
                artwork = ImageOps.fit(source.convert("RGBA"), (size, size), method=Image.Resampling.LANCZOS)
        except (OSError, ValueError, Image.DecompressionBombError):
            pass
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius, fill=255)
    if artwork is not None:
        # Honor both rounded corners and original transparent pixels.
        from PIL import ImageChops

        mask = ImageChops.multiply(mask, artwork.getchannel("A"))
        image.paste(artwork.convert("RGB"), xy, mask)
    else:
        draw = ImageDraw.Draw(image)
        x, y = xy
        draw.rounded_rectangle((x, y, x + size, y + size), radius, fill="#302D4B")
        _text(draw, (x + size / 2, y + size / 2), placeholder[:1], max(16, int(size * 0.35)), PURPLE, True, "mm")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((xy[0], xy[1], xy[0] + size, xy[1] + size), radius, outline=BORDER, width=1)


def _pill(draw: ImageDraw.ImageDraw, x: int, y: int, label: str, *, accented: bool = False) -> int:
    width = int(_font(16).getlength(label)) + 26
    draw.rounded_rectangle((x, y, x + width, y + 33), 16, fill="#302945" if accented else "#22253B")
    _text(draw, (x + 13, y + 7), label, 16, PURPLE if accented else MUTED)
    return x + width + 10


def _canvas(height: int, *, width: int = WIDTH) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, 5), fill=PURPLE)
    draw.line((40, height - 96, width - 40, height - 96), fill=BORDER, width=1)
    return image, draw


def _footer(draw: ImageDraw.ImageDraw, snapshot: dict, height: int, *, build_method: str | None = None, width: int = WIDTH) -> None:
    _text(draw, (40, height - 77), f"수집 {_capture_label(snapshot)}", 15, MUTED)
    _text(draw, (width - 40, height - 77), "SOURCE  HEROES PROFILE", 13, PURPLE, True, "rt")
    _text(draw, (40, height - 53), _fit(f"패치  {_patch_label(snapshot)}", width - 80, 14), 14, MUTED)
    note = (
        f"{build_method} · 후보 빌드 중 정렬 · 아이콘 숫자: 해당 레벨의 특성 선택 번호"
        if build_method is not None
        else "가져온 데이터 기준 · 표시된 승률은 각 영웅의 기록된 게임에서 계산된 수치입니다."
    )
    _text(draw, (40, height - 29), _fit(note, width - 80, 13), 13, MUTED)


def _png(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def render_chart(
    snapshot: dict,
    heroes: list[dict],
    *,
    page: int = 1,
    pages: int = 1,
    sort_by: str = "win_rate",
    min_games: int = 0,
) -> bytes:
    """Render the supplied page (up to 15 already sorted hero rows) as a PNG."""
    visible = heroes[:PAGE_SIZE]
    height = 352 + max(1, len(visible)) * 62
    image, draw = _canvas(height)
    _text(draw, (40, 34), "CATFISH  /  HERO STATISTICS", 14, PURPLE, True)
    _text(draw, (40, 69), "영웅 성능 차트", 40, TEXT, True)
    _text(draw, (WIDTH - 40, 80), f"{page:02d} / {pages:02d}", 24, MUTED, True, "rt")
    x = _pill(draw, 40, 132, _mode(snapshot), accented=True)
    x = _pill(draw, x, 132, "승률 높은 순" if sort_by == "win_rate" else "게임 수 많은 순")
    _pill(draw, x, 132, f"최소 {_games(min_games)}게임")
    _text(draw, (40, 191), "순위", 15, MUTED)
    _text(draw, (173, 191), "영웅", 15, MUTED)
    _text(draw, (539, 191), "승률", 15, MUTED)
    _text(draw, (803, 191), "막대 0–100%", 12, MUTED, anchor="rt")
    _text(draw, (1034, 191), "게임 수", 15, MUTED, anchor="rt")

    if not visible:
        draw.rounded_rectangle((40, 226, WIDTH - 40, 288), 12, fill=PANEL)
        _text(draw, (WIDTH / 2, 257), "조건에 맞는 영웅 데이터가 없습니다.", 21, MUTED, anchor="mm")

    for index, hero in enumerate(visible):
        y = 226 + index * 62
        draw.rounded_rectangle((40, y, WIDTH - 40, y + 55), 10, fill=PANEL if index % 2 == 0 else PANEL_ALT)
        rank = max(0, page - 1) * PAGE_SIZE + index + 1
        _text(draw, (68, y + 28), f"{rank:02d}", 19, PURPLE if rank <= 3 else MUTED, True, "mm")
        _artwork(image, snapshot, f"portrait:{hero.get('short_name', '')}", (110, y + 5), 44, _name(hero), 9)
        _text(draw, (173, y + 7), _fit(_name(hero), 330, 21, True), 21, TEXT, True)
        role = str(hero.get("role") or hero.get("new_role") or "")
        _text(draw, (174, y + 33), ROLE_NAMES.get(role, role), 11, MUTED)
        bar_start, bar_width = 539, 264
        draw.rounded_rectangle((bar_start, y + 22, bar_start + bar_width, y + 34), 6, fill="#30334D")
        win_rate = max(0.0, min(100.0, _number(hero.get("win_rate"))))
        fill_end = bar_start + bar_width * win_rate / 100
        color = TEAL if win_rate >= 50 else PURPLE
        if fill_end > bar_start:
            draw.rounded_rectangle((bar_start, y + 22, fill_end, y + 34), 6, fill=color)
        # The center tick is the 50% reference on the 0–100% track.
        draw.line((bar_start + bar_width / 2, y + 19, bar_start + bar_width / 2, y + 37), fill="#71748E", width=1)
        _text(draw, (912, y + 28), _rate(hero.get("win_rate")), 22, color, True, "rm")
        _text(draw, (1034, y + 28), _games(hero.get("games_played")), 21, TEXT, True, "rm")

    _footer(draw, snapshot, height)
    return _png(image)


def render_tier_list(snapshot: dict, tiers: dict[str, list[dict]]) -> bytes:
    """Render all heroes as a wide board with compact, horizontal hero cards."""
    columns, card_width, card_height = 8, 289, 80
    gap, padding = 8, 8
    ordered_tiers = list(TIER_THRESHOLDS)
    colors = {"S": "#F49AA5", "A": "#F2BB89", "B": "#E9D88E", "C": "#88D6BB", "D": "#9CB9F4"}
    band_heights = {
        tier: max(1, math.ceil(len(tiers.get(tier, [])) / columns)) * (card_height + gap) - gap + padding * 2
        for tier in ordered_tiers
    }
    start_y = 112
    height = start_y + sum(band_heights.values()) + gap * (len(ordered_tiers) - 1) + 112
    image, draw = _canvas(height, width=TIER_WIDTH)
    count = sum(len(tiers.get(tier, [])) for tier in ordered_tiers)
    _text(draw, (40, 18), "CATFISH  /  HERO TIER LIST", 14, PURPLE, True)
    _text(draw, (40, 46), "영웅 티어표", 40, TEXT, True)
    _text(draw, (TIER_WIDTH - 40, 55), f"전체 {count}명", 26, MUTED, True, "rt")
    x = _pill(draw, 350, 50, _mode(snapshot), accented=True)
    x = _pill(draw, x, 50, "승률 기준 S–D")
    x = _pill(draw, x, 50, "티어 안에서는 승률 높은 순")
    _text(draw, (x + 18, 58), "모든 표본 포함 · 게임 수가 적으면 승률 변동이 큽니다.", 18, MUTED)

    y = start_y
    for tier_index, tier in enumerate(ordered_tiers):
        heroes = tiers.get(tier, [])
        band_height = band_heights[tier]
        color = colors[tier]
        draw.rounded_rectangle((32, y, TIER_WIDTH - 32, y + band_height), 12, fill=PANEL, outline=BORDER)
        draw.rounded_rectangle((40, y + padding, 144, y + band_height - padding), 8, fill=PANEL_ALT)
        lower = TIER_THRESHOLDS[tier]
        upper = TIER_THRESHOLDS[ordered_tiers[tier_index - 1]] if tier_index else None
        if upper is None:
            bounds = [f"{lower:g}% 이상"]
        elif tier_index == len(ordered_tiers) - 1:
            bounds = [f"{upper:g}% 미만"]
        else:
            bounds = [f"{lower:g}% 이상", f"{upper:g}% 미만"]
        label_y = y + (band_height - (48 + len(bounds) * 18 + 18)) / 2
        _text(draw, (92, label_y), tier, 40, color, True, "mt")
        for line_index, label in enumerate(bounds):
            _text(draw, (92, label_y + 48 + line_index * 18), label, 14, color, anchor="mt")
        _text(draw, (92, label_y + 53 + len(bounds) * 18), f"{len(heroes)}명", 13, MUTED, anchor="mt")

        if not heroes:
            _text(draw, ((156 + TIER_WIDTH - 32) / 2, y + band_height / 2), "해당 티어의 영웅이 없습니다.", 22, MUTED, anchor="mm")

        for index, hero in enumerate(heroes):
            column, row = index % columns, index // columns
            x = 156 + column * (card_width + gap)
            card_y = y + padding + row * (card_height + gap)
            draw.rounded_rectangle((x, card_y, x + card_width, card_y + card_height), 8, fill=BACKGROUND)
            name = _name(hero)
            _artwork(image, snapshot, f"portrait:{hero.get('short_name', '')}", (x + 10, card_y + 10), 60, name, 8)
            _text(draw, (x + 86, card_y + 8), _fit(name, card_width - 96, 24, True), 24, TEXT, True)
            _text(draw, (x + 86, card_y + 43), _rate(hero.get("win_rate")), 26, color, True)
            _text(draw, (x + card_width - 10, card_y + 50), f"{_games(hero.get('games_played'))}게임", 17, MUTED, anchor="rt")
        y += band_height + gap

    _footer(draw, snapshot, height, width=TIER_WIDTH)
    return _png(image)


def render_builds(
    snapshot: dict,
    hero: dict,
    builds: list[dict],
    *,
    sort_by: str = "games_played",
    min_games: int = 0,
) -> bytes:
    """Render two labeled recommendations or three ranked candidate builds."""
    comparing = any(build.get("recommendation_labels") for build in builds)
    visible = builds[:2 if comparing else 3]
    card_height, gap = 282, 18
    height = 282 + max(1, len(visible)) * (card_height + gap) + 100
    image, draw = _canvas(height)
    _text(draw, (40, 34), "CATFISH  /  TALENT BUILDS", 14, PURPLE, True)
    _artwork(image, snapshot, f"portrait:{hero.get('short_name', '')}", (40, 73), 86, _name(hero), 18)
    hero_title = f"{_name(hero)}  추천 빌드"
    _text(draw, (148, 76), _fit(hero_title, WIDTH - 194, 37, True), 37, TEXT, True)
    subtitle = (
        "승률 1위와 선택 수 1위 비교 · 레벨 순서대로 선택한 특성"
        if comparing else f"후보 중 상위 {len(visible)}개 · 레벨 순서대로 선택한 특성"
    )
    _text(draw, (150, 128), subtitle, 17, MUTED)
    x = _pill(draw, 40, 184, _mode(snapshot), accented=True)
    if comparing:
        x = _pill(draw, x, 184, "승률 · 선택 수 1위")
        _pill(draw, x, 184, "선택 수 = 기록된 게임 수")
    else:
        x = _pill(draw, x, 184, "게임 수 많은 순" if sort_by == "games_played" else "승률 높은 순")
        _pill(draw, x, 184, f"최소 {_games(min_games)}게임")

    if not visible:
        draw.rounded_rectangle((40, 253, WIDTH - 40, 253 + card_height), 18, fill=PANEL, outline=BORDER)
        _text(draw, (WIDTH / 2, 375), "조건에 맞는 빌드 데이터가 없습니다.", 25, TEXT, True, "mm")
        _text(draw, (WIDTH / 2, 418), "최소 게임 수를 낮추거나 해당 영웅의 데이터를 가져와 주세요.", 17, MUTED, anchor="mm")

    for index, build in enumerate(visible):
        y = 253 + index * (card_height + gap)
        draw.rounded_rectangle((40, y, WIDTH - 40, y + card_height), 18, fill=PANEL, outline=BORDER, width=1)
        draw.rounded_rectangle((63, y + 21, 104, y + 62), 11, fill="#352D4F")
        _text(draw, (84, y + 41), str(index + 1), 22, PURPLE, True, "mm")
        labels = build.get("recommendation_labels") or ()
        title = " · ".join(labels) if labels else f"BUILD {index + 1:02d}"
        _text(draw, (120, y + 28), _fit(title, 560, 24, True), 24, TEXT, True)
        _text(draw, (817, y + 20), "게임 수", 13, MUTED, anchor="rt")
        _text(draw, (817, y + 44), _games(build.get("games_played")), 25, TEXT, True, "rt")
        _text(draw, (1030, y + 20), "승률", 13, MUTED, anchor="rt")
        _text(draw, (1030, y + 41), _rate(build.get("win_rate")), 30, TEAL, True, "rt")
        draw.line((64, y + 87, WIDTH - 64, y + 87), fill=BORDER)

        for talent_index, (level, field) in enumerate(LEVEL_FIELDS):
            talent = build.get(field) or {}
            center = 134 + talent_index * (832 / 6)
            _text(draw, (center, y + 102), f"LEVEL {level}", 12, PURPLE if level in (10, 20) else MUTED, True, "mt")
            icon_xy = (round(center - 31), y + 126)
            _artwork(image, snapshot, str(talent.get("icon") or ""), icon_xy, 62, "?", 11)
            if talent.get("sort") is not None:
                draw.rounded_rectangle((center + 15, y + 169, center + 37, y + 191), 7, fill="#C7B4FF")
                _text(draw, (center + 26, y + 179), str(talent["sort"]), 13, BACKGROUND, True, "mm")
            title = str(talent.get("title") or "특성 정보 없음")
            for line_index, line in enumerate(_wrap(title, 121, 14)):
                _text(draw, (center, y + 201 + line_index * 20), line, 14, TEXT, anchor="mt")

    build_filters = (snapshot.get("build_filters") or {}).get(hero.get("short_name"), {})
    method = str(build_filters.get("talentbuildtype") or "Heroes Profile")
    _footer(draw, snapshot, height, build_method=method)
    return _png(image)
