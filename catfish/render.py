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

from .data import TIER_THRESHOLDS, hero_tier
from .talents import talent_name


WIDTH = 1100
TIER_WIDTH = 2400
PAGE_SIZE = 15
BACKGROUND = "#10111E"
PANEL = "#191B2D"
PANEL_ALT = "#1D1F34"
BORDER = "#30344E"
TEXT = "#F1F2FC"
MUTED = "#9299B5"
PURPLE = "#AF92FF"
TEAL = "#69D6C2"
TIER_COLORS = {"S": "#F49AA5", "A": "#F2BB89", "B": "#E9D88E", "C": "#88D6BB", "D": "#9CB9F4"}
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
    remaining = " ".join(value.split())
    lines: list[str] = []
    font = _font(size)
    while remaining:
        if font.getlength(remaining) <= width:
            lines.append(remaining)
            break
        if len(lines) == max_lines - 1:
            lines.append(_fit(remaining, width, size))
            break
        end = 1
        while end < len(remaining) and font.getlength(remaining[:end + 1]) <= width:
            end += 1
        # Prefer word boundaries, but also wrap Korean names without spaces.
        boundary = remaining.rfind(" ", 0, end + 1)
        if boundary > 0:
            end = boundary
        lines.append(remaining[:end].rstrip())
        remaining = remaining[end:].lstrip()
    return lines


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
    """Show every hero and its statistics with compact tier labels."""
    columns, card_height = 8, 64
    margin, gap, row_gap, padding = 24, 8, 6, 8
    heroes_x = 116
    card_width = (TIER_WIDTH - margin - padding - heroes_x - (columns - 1) * gap) / columns
    ordered_tiers = list(TIER_THRESHOLDS)
    band_heights = {
        tier: (math.ceil(len(tiers[tier]) / columns) * (card_height + row_gap) - row_gap + padding * 2
               if tiers.get(tier) else 48)
        for tier in ordered_tiers
    }
    start_y = 68
    height = start_y + sum(band_heights.values()) + gap * (len(ordered_tiers) - 1) + 16
    image = Image.new("RGB", (TIER_WIDTH, height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    _text(draw, (margin, 16), f"{_mode(snapshot)} · 티어표", 32, TEXT, True)

    y = start_y
    for tier_index, tier in enumerate(ordered_tiers):
        heroes = tiers.get(tier, [])
        band_height = band_heights[tier]
        color = TIER_COLORS[tier]
        draw.rounded_rectangle((margin, y, TIER_WIDTH - margin, y + band_height), 8, fill=PANEL)
        if tier_index == len(ordered_tiers) - 1:
            cutoff = f"<{TIER_THRESHOLDS[ordered_tiers[tier_index - 1]]:g}%"
        else:
            cutoff = f"≥{TIER_THRESHOLDS[tier]:g}%"
        if not heroes:
            _text(draw, (64, y + 24), tier, 28, color, True, "mm")
            _text(draw, (heroes_x, y + 24), cutoff, 16, color, anchor="lm")
            _text(draw, (heroes_x + 96, y + 24), "없음", 18, MUTED, anchor="lm")
        else:
            label_y = y + (band_height - 60) / 2
            _text(draw, (64, label_y), tier, 34, color, True, "mt")
            _text(draw, (64, label_y + 44), cutoff, 14, color, anchor="mt")

        for index, hero in enumerate(heroes):
            column, row = index % columns, index // columns
            x = heroes_x + column * (card_width + gap)
            card_y = y + padding + row * (card_height + row_gap)
            name = _name(hero)
            _artwork(image, snapshot, f"portrait:{hero.get('short_name', '')}", (round(x), card_y + 6), 52, name, 6)
            _text(draw, (x + 64, card_y), _fit(name, card_width - 72, 24, True), 24, TEXT, True)
            _text(draw, (x + 64, card_y + 34), _rate(hero.get("win_rate")), 24, color, True)
            _text(draw, (x + card_width - 8, card_y + 40), f"{_games(hero.get('games_played'))}게임", 17, MUTED, anchor="rt")
        y += band_height + gap

    return _png(image)


def render_builds(
    snapshot: dict,
    hero: dict,
    builds: list[dict],
    *,
    sort_by: str = "games_played",
    min_games: int = 0,
) -> bytes:
    """Keep each build to its recommendation, sample size, and seven talents."""
    comparing = any(build.get("recommendation_labels") for build in builds)
    visible = builds[:2 if comparing else 3]
    margin, gap, start_y = 24, 12, 68
    cell_width = (WIDTH - 2 * margin - 24) / 7
    layouts = []
    for build in visible:
        talents = []
        for level, field in LEVEL_FIELDS:
            talent = build.get(field) or {}
            lines = _wrap(talent_name(talent), cell_width - 10, 20, max_lines=4)
            talents.append((level, talent, lines))
        card_height = 144 + max(len(lines) for _, _, lines in talents) * 26 + 14
        layouts.append((build, talents, card_height))

    content_height = sum(item[2] for item in layouts) + gap * max(0, len(layouts) - 1)
    height = start_y + (content_height if layouts else 112) + 16
    image = Image.new("RGB", (WIDTH, height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    context = _mode(snapshot)
    if not comparing:
        context += " · " + ("게임 수순" if sort_by == "games_played" else "승률순")
        if min_games:
            context += f" · {_games(min_games)}게임 이상"
    context = _fit(context, 580, 18)
    tier = hero_tier(hero)
    badge_width = math.ceil(_font(22, True).getlength(tier)) + 20
    name_width = min(440, WIDTH - 2 * margin - _font(18).getlength(context) - badge_width - 32)
    name = _fit(_name(hero), name_width, 30, True)
    _text(draw, (margin, 16), name, 30, TEXT, True)
    badge_x = margin + math.ceil(_font(30, True).getlength(name)) + 12
    name_bounds = _font(30, True).getbbox(name, anchor="lt")
    header_center = 16 + (name_bounds[1] + name_bounds[3]) / 2
    draw.rounded_rectangle((badge_x, header_center - 16, badge_x + badge_width, header_center + 16), 6, fill=PANEL)
    tier_bounds = _font(22, True).getbbox(tier, anchor="mt")
    tier_y = header_center - (tier_bounds[1] + tier_bounds[3]) / 2
    _text(draw, (badge_x + badge_width / 2, tier_y), tier, 22, TIER_COLORS[tier], True, "mt")
    _text(draw, (WIDTH - margin, 23), context, 18, MUTED, anchor="rt")

    if not layouts:
        _text(draw, (WIDTH / 2, start_y + 48), "조건에 맞는 빌드 데이터가 없습니다.", 23, MUTED, anchor="mm")

    y = start_y
    for index, (build, talents, card_height) in enumerate(layouts):
        draw.rounded_rectangle((margin, y, WIDTH - margin, y + card_height), 10, fill=PANEL)
        labels = build.get("recommendation_labels") or ()
        title = " · ".join(labels) if labels else f"빌드 {index + 1}"
        _text(draw, (margin + 16, y + 10), _fit(title, 520, 22, True), 22, TEXT, True)
        _text(draw, (WIDTH - margin - 16, y + 11), f"승률 {_rate(build.get('win_rate'))} · {_games(build.get('games_played'))}게임", 22, TEAL, True, "rt")

        for talent_index, (level, talent, lines) in enumerate(talents):
            center = margin + 12 + (talent_index + 0.5) * cell_width
            _text(draw, (center, y + 45), f"{level}레벨", 15, MUTED, anchor="mt")
            icon_xy = (round(center - 32), y + 68)
            _artwork(image, snapshot, str(talent.get("icon") or ""), icon_xy, 64, "?", 8)
            if talent.get("sort") is not None:
                draw.rounded_rectangle((center + 14, y + 111, center + 38, y + 135), 6, fill="#C7B4FF")
                _text(draw, (center + 26, y + 123), str(talent["sort"]), 15, BACKGROUND, True, "mm")
            for line_index, line in enumerate(lines):
                _text(draw, (center, y + 144 + line_index * 26), line, 20, TEXT, anchor="mt")
        y += card_height + gap
    return _png(image)
