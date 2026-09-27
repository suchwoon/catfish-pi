"""Offline Korean talent names keyed by Heroes Profile's game talent IDs."""

from __future__ import annotations

from functools import lru_cache
import json
import logging
from pathlib import Path


CATALOG_PATH = Path(__file__).resolve().parent.parent / "assets/localization/talents.ko-KR.json"


def normalize_talent_id(value: str) -> str:
    """Ignore cosmetic punctuation/case differences in the stable game ID."""
    return "".join(character for character in value.casefold() if character.isalnum())


@lru_cache(maxsize=1)
def _catalog() -> dict[str, str]:
    try:
        data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        names = data["names"]
        if not isinstance(names, dict) or any(not isinstance(name, str) for name in names.values()):
            raise ValueError("Invalid talent-name catalog")
        return names
    except (OSError, ValueError, KeyError, TypeError):
        logging.getLogger(__name__).warning("Korean talent-name catalog is unavailable: %s", CATALOG_PATH)
        return {}


def talent_name(talent: dict) -> str:
    """Use the game's Korean name; preserve original text for unknown talents.

    Matching by ID avoids guessing when different talents share an English
    title or when Heroes Profile's numeric IDs change. Never modify the import.
    """
    identifier = str(talent.get("talent_name") or "")
    localized = _catalog().get(normalize_talent_id(identifier))
    return localized or str(talent.get("title") or identifier or "—")
