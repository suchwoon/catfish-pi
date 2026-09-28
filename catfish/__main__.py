"""Run, import, and preview without requiring a token for local workflows."""

import argparse
import json
import logging
import os
from pathlib import Path

from .data import MODES, ROOT, SORTS, DataStore, QueryError, chart_page, chart_rows, find_hero, recommended_builds, tier_rows, top_builds


def main() -> None:
    parser = argparse.ArgumentParser(description="Catfish · 히오스 디스코드 봇")
    parser.add_argument("--data-dir", type=Path, help="가져온 JSON/아이콘 저장 디렉터리")
    commands = parser.add_subparsers(dest="command", required=True)
    import_parser = commands.add_parser("import", help="HAR에서 통계와 아이콘 가져오기")
    import_parser.add_argument("files", type=Path, nargs="*", help="생략 시 imports/*.har")
    preview_parser = commands.add_parser("preview", help="디스코드 연결 없이 결과 PNG 생성")
    preview_parser.add_argument("--mode", choices=MODES, default="aram")
    preview_parser.add_argument("--hero", default="아즈모단")
    preview_parser.add_argument("--chart-sort", choices=SORTS, default="win_rate")
    preview_parser.add_argument("--build-sort", choices=SORTS, default="games_played")
    preview_parser.add_argument("--recommendations", action="store_true", help="/히오스 영웅 조회처럼 승률 1위·선택 수 1위 빌드 비교")
    preview_parser.add_argument("--min-games", type=int, default=0)
    preview_parser.add_argument("--page", type=int, default=1)
    preview_parser.add_argument("--output", type=Path, default=ROOT / "previews")
    commands.add_parser("run", help="디스코드 봇 실행")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    directory = args.data_dir or Path(os.getenv("DATA_DIR", "data"))
    if not directory.is_absolute():
        directory = ROOT / directory
    store = DataStore(directory)

    try:
        if args.command == "import":
            from .importer import import_hars
            files = args.files or sorted((ROOT / "imports").glob("*.har"))
            if not files:
                parser.error("imports에 HAR 파일을 넣어 주세요.")
            for summary in import_hars(files, directory):
                print(json.dumps(summary, ensure_ascii=False, indent=2))
        elif args.command == "preview":
            from .render import render_builds, render_chart, render_tier_list
            snapshot = store.snapshot(args.mode)
            rows, pages = chart_page(chart_rows(snapshot, args.chart_sort, args.min_games), args.page)
            hero = find_hero(snapshot, args.hero)
            builds = recommended_builds(snapshot, hero) if args.recommendations else top_builds(snapshot, hero, args.build_sort, args.min_games)
            args.output.mkdir(parents=True, exist_ok=True)
            chart_path = args.output / f"{args.mode}-performance-{args.page}.png"
            build_path = args.output / f"{args.mode}-{hero['short_name']}-builds.png"
            tier_path = args.output / f"{args.mode}-tiers.png"
            chart_path.write_bytes(render_chart(snapshot, rows, page=args.page, pages=pages, sort_by=args.chart_sort, min_games=args.min_games))
            build_path.write_bytes(render_builds(snapshot, hero, builds, sort_by=args.build_sort, min_games=args.min_games))
            tier_path.write_bytes(render_tier_list(snapshot, tier_rows(snapshot)))
            print(f"전체 티어표: {tier_path}\n성능 차트: {chart_path}\n빌드 카드: {build_path}")
        elif args.command == "run":
            from .bot import CatfishClient
            token = os.getenv("DISCORD_TOKEN", "").strip()
            if not token or token == "your_bot_token_here":
                parser.error(".env의 DISCORD_TOKEN을 설정해 주세요. .env.example을 복사해서 시작할 수 있습니다.")
            guild = os.getenv("DISCORD_GUILD_ID", "").strip()
            if guild and (not guild.isdecimal() or int(guild) <= 0):
                parser.error("DISCORD_GUILD_ID는 서버 ID 숫자여야 합니다.")
            if not store.available():
                parser.error("가져온 데이터가 없습니다. 먼저 python -m catfish import를 실행해 주세요.")
            logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
            CatfishClient(store, int(guild) if guild else None).run(token)
    except (QueryError, ValueError, OSError) as exc:
        parser.exit(1, f"오류: {exc}\n")


if __name__ == "__main__":
    main()
