"""Parse explicit game modes and optional hero names after the /히오스 prefix."""

import unicodedata

from .data import QueryError


MODE_ALIASES = {
    "무영대": "aram", "ㅁㅇㄷ": "aram",
    "빠대": "standard", "ㅃㄷ": "standard", "영리": "standard", "ㅇㄹ": "standard",
}
MODE_LABELS = {"aram": "무영대", "standard": "빠대"}

# NFKC turns compatibility consonants such as ㅁ into their canonical jamo.
# Normalize both sides so the short Korean aliases remain usable.
_NORMALIZED_MODES = {unicodedata.normalize("NFKC", alias): mode
                     for alias, mode in MODE_ALIASES.items()}
_EXAMPLES = (
    "예: /히오스 무영대, /히오스 빠대, /히오스 줄진 무영대, /히오스 줄진 빠대. "
    "무영대=ㅁㅇㄷ, 빠대=ㅃㄷ=영리=ㅇㄹ을 사용할 수 있습니다."
)


def parse_query(query: str) -> tuple[str, str | None]:
    """Return (mode, hero), with None selecting the mode's tier list.

    A hero query must end with exactly one mode alias. Mode-only input selects
    the tier list; there is no default mode.
    """
    tokens = unicodedata.normalize("NFKC", query).split()
    mode_positions = [index for index, token in enumerate(tokens)
                      if token in _NORMALIZED_MODES]
    if not mode_positions:
        raise QueryError(f"게임 모드를 입력해 주세요. 빌드는 영웅 이름 뒤에 모드를 붙여 주세요. {_EXAMPLES}")
    if len(mode_positions) != 1:
        raise QueryError(f"게임 모드는 한 번만 입력해 주세요. {_EXAMPLES}")

    position = mode_positions[0]
    mode = _NORMALIZED_MODES[tokens[position]]
    if len(tokens) == 1:
        return mode, None
    if position != len(tokens) - 1:
        raise QueryError(f"영웅 이름 뒤에 모드를 입력해 주세요. 티어표는 모드만 입력하면 됩니다. {_EXAMPLES}")

    hero_name = " ".join(tokens[:-1])
    if hero_name in {"전체", "통계", "전체 통계"}:
        raise QueryError(f"티어표는 모드만 입력해 주세요. {_EXAMPLES}")
    return mode, hero_name
