#!/usr/bin/env python3
"""Rebuild the bundled talent-name catalog from pinned HeroesToolChest data.

Uses only the Python standard library. Network access is only needed when this
maintenance script runs; the Discord bot reads the resulting local catalog.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from catfish.talents import normalize_talent_id  # noqa: E402


REPOSITORY = "https://github.com/HeroesToolChest/heroes-data2"
REVISION = "52f5cb7ad081ad1439a414c36b70c6e42b4526aa"
VERSION = "2.55.17.98025"


def apply_json_patch(document: dict, operations: list[dict]) -> dict:
    """Apply the add/remove/replace operations used by the upstream extracts.

    Fail on an unknown operation instead of silently emitting incomplete names.
    JSON Pointer escaping and array insertion follow RFC 6902.
    """
    for operation in operations:
        action, path = operation["op"], operation["path"]
        if action not in {"add", "remove", "replace"}:
            raise ValueError(f"Unsupported JSON patch operation: {action}")
        if not path:
            if action == "remove":
                raise ValueError("Cannot remove the source document")
            document = deepcopy(operation["value"])
            continue
        if not path.startswith("/"):
            raise ValueError(f"Invalid JSON pointer: {path}")
        parts = [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")]
        parent = document
        for part in parts[:-1]:
            parent = parent[int(part)] if isinstance(parent, list) else parent[part]
        key = parts[-1]
        if isinstance(parent, list):
            index = len(parent) if key == "-" else int(key)
            if action == "add":
                if not 0 <= index <= len(parent):
                    raise ValueError(f"Invalid array insertion: {path}")
                parent.insert(index, deepcopy(operation["value"]))
            elif action == "remove":
                del parent[index]
            else:
                parent[index] = deepcopy(operation["value"])
        elif action == "remove":
            del parent[key]
        else:
            if action == "replace" and key not in parent:
                raise ValueError(f"Missing replacement target: {path}")
            parent[key] = deepcopy(operation["value"])
    return document


def extract_names(document: dict) -> dict[str, str]:
    """Game-string keys begin with talentId, followed by button/ability/level."""
    result: dict[str, str] = {}
    for link_id, name in document["items"]["talent"]["name"].items():
        identifier = normalize_talent_id(link_id.split("|", 1)[0])
        if not identifier or not isinstance(name, str) or not name.strip():
            raise ValueError(f"Missing talent ID or localized name: {link_id}")
        if identifier in result and result[identifier] != name:
            raise ValueError(f"Conflicting names after ID normalization: {link_id}")
        result[identifier] = name
    return dict(sorted(result.items()))


def build_catalog(version: str, revision: str, source_dir: Path | None = None) -> tuple[dict, str]:
    sources: list[dict[str, str]] = []
    base_url = f"https://raw.githubusercontent.com/HeroesToolChest/heroes-data2/{revision}"

    def fetch(path: str) -> bytes:
        url = f"{base_url}/{path}"
        if source_dir is not None:
            content = (source_dir / path).read_bytes()
        else:
            with urlopen(url, timeout=60) as response:
                content = response.read()
        sources.append({"url": url, "sha256": hashlib.sha256(content).hexdigest()})
        return content

    def reconstruct(current_version: str, seen: set[str]) -> dict:
        if current_version in seen:
            raise ValueError("Circular source patch dependency")
        if not re.fullmatch(r"\d+\.\d+\.\d+\.\d+(?:_ptr)?", current_version):
            raise ValueError(f"Invalid game version: {current_version}")
        seen.add(current_version)
        metadata = json.loads(fetch(f"heroesdata/{current_version}/.hdp.json"))
        if not metadata.get("extracted"):
            raise ValueError(f"Game data was not extracted for {current_version}")
        filename = metadata["files"]["[gamestrings]"]["kokr"]
        if Path(filename).name != filename:
            raise ValueError("Unexpected source filename")
        if metadata["json"] == "patch":
            document = reconstruct(metadata["depends-on"], seen)
            patch = json.loads(fetch(f"heroesdata/{current_version}/gamestrings/{filename}"))
            return apply_json_patch(document, patch)
        if metadata["json"] != "full":
            raise ValueError("Unknown source data format")
        return json.loads(fetch(f"heroesdata/{current_version}/gamestrings/{filename}"))

    document = reconstruct(version, set())
    if document["meta"]["heroesVersion"] != version:
        raise ValueError("Reconstructed game version does not match the request")
    if document["meta"]["gameStringText"]["locale"] != "KOKR":
        raise ValueError("Source strings are not Korean")
    license_text = fetch("LICENSE").decode("utf-8")
    catalog = {
        "schema_version": 1,
        "locale": "ko-KR",
        "game_version": version,
        "source": {
            "repository": REPOSITORY,
            "revision": revision,
            "license": "MIT",
            "license_file": "LICENSE.heroes-data2.txt",
            "description": "Korean in-game talent names extracted with Heroes Data Parser.",
            "files": sources,
        },
        "names": extract_names(document),
    }
    return catalog, license_text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=VERSION)
    parser.add_argument("--revision", default=REVISION, help="Pinned 40-character upstream Git commit")
    parser.add_argument("--source-dir", type=Path, help="Use an upstream checkout instead of HTTP")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "assets/localization")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        parser.error("--revision must be a full Git commit hash")
    catalog, license_text = build_catalog(args.version, args.revision, args.source_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / "talents.ko-KR.json"
    output.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "LICENSE.heroes-data2.txt").write_text(license_text, encoding="utf-8")
    print(f"Wrote {len(catalog['names'])} Korean talent names for {args.version} to {output}")


if __name__ == "__main__":
    main()
