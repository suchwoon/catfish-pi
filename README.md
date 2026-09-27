# Catfish — 히오스 디스코드 봇

`imports/`에 넣은 Heroes Profile HAR 파일을 읽어 전체 영웅 티어표와 빌드 카드를 보여줍니다. Python 3.11 이상이 필요합니다. 봇을 사용하려면 프로세스가 계속 실행되어 있어야 합니다.

## 디스코드에서 사용

채팅창에서 `/히오스`를 입력하고 **무영대** 또는 **빠대**를 선택합니다. 두 메뉴 모두 “전체 티어표 · 영웅 이름을 입력하면 빌드”로 안내합니다.

```text
/히오스 무영대
/히오스 빠대
/히오스 무영대 영웅:줄진
/히오스 빠대 영웅:줄진
```

- **`/히오스 무영대`**: 무영대 전체 영웅 티어표를 보여줍니다.
- **`/히오스 빠대`**: 빠른 대전 & 영웅 리그 통합 티어표를 보여줍니다.
- **`/히오스 무영대 영웅:줄진`**: 줄진의 무영대 빌드를 보여줍니다.
- **`/히오스 빠대 영웅:줄진`**: 줄진의 빠른 대전 & 영웅 리그 통합 빌드를 보여줍니다.

**`영웅:`은 직접 타이핑하는 문구가 아니라 디스코드가 표시하는 입력칸 이름**입니다. 영웅을 비워 두면 전체 티어표, 입력하면 해당 영웅의 빌드를 보여줍니다. 입력칸에 `줄진`처럼 영웅 이름을 입력하고 실행하면 됩니다. `정타족`, `모랄` 같은 등록된 별명과 영문 이름도 사용할 수 있습니다.

일반 채팅으로 보내는 단축 입력도 지원합니다. 이 방식에는 슬래시 메뉴나 자동완성이 없습니다.

```text
/히오스 줄진 ㅁㅇㄷ
/히오스 줄진 ㅇㄹ
/히오스 ㅃㄷ
```

채팅 단축 입력에서 `무영대`와 `ㅁㅇㄷ`는 무작위 영웅 대전, `빠대`·`ㅃㄷ`·`영리`·`ㅇㄹ`는 모두 빠른 대전 & 영웅 리그 통합 데이터를 조회합니다. 모드만 입력하면 티어표, 영웅 이름 뒤에 모드를 입력하면 빌드를 보여줍니다.

티어는 저장된 승률에 따른 구간 분류입니다. **S: 55% 이상 / A: 52% 이상 55% 미만 / B: 48% 이상 52% 미만 / C: 45% 이상 48% 미만 / D: 45% 미만**입니다. 같은 티어 안에서는 승률순으로 표시하고, 게임 수로 영웅을 제외하지 않습니다. 기준은 `catfish/data.py`의 `TIER_THRESHOLDS`에서 조정할 수 있습니다.

빌드 조회는 가져온 후보 안에서 **승률 1위**·**선택 수 1위**를 고릅니다. 같은 빌드면 두 라벨을 붙여 한 번만 표시합니다. 빌드별 픽률 퍼센트는 원본에 없으므로, 사용 빈도는 기록된 **게임 수**로 비교합니다. 영웅 자체의 픽률을 빌드 픽률로 사용하지 않습니다. 각 카드에 승률과 게임 수를 함께 표시하며, 표본이 적은 승률 1위도 포함됩니다.

빌드와 티어표 조회 결과는 이미지 파일만 첨부합니다. 빌드 이미지는 영웅·모드, 추천 구분, 승률·게임 수, 레벨별 특성 아이콘·한글 이름·선택 번호를 보여주며, 긴 특성명은 줄바꿈합니다.

## 설치 및 로컬 미리보기

```bash
git clone https://github.com/suchwoon/catfish-pi.git
cd catfish-pi
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

python -m catfish import
python -m catfish preview --hero 아즈모단
```

미리보기는 디스코드 토큰 없이 실행되며 `previews/`에 전체 티어표(`aram-tiers.png` 또는 `standard-tiers.png`), 성능 차트와 빌드 카드 PNG를 만듭니다. 기본 모드는 무작위 영웅 대전이며, `--mode standard`로 빠른 대전 & 영웅 리그 통합 데이터를 조회합니다. 전체 티어표는 항상 모든 영웅을 승률로 분류하며, 정렬·최소 게임 수·페이지 옵션은 상세 성능 차트와 빌드 카드에 적용됩니다. Windows에서는 가상환경 활성화에 `.venv\Scripts\activate`를 사용하고 프로젝트 경로를 환경에 맞게 바꾸세요.

```bash
python -m catfish preview --hero 발리라 --build-sort win_rate --min-games 10
python -m catfish preview --hero 가즈로 --recommendations
python -m catfish preview --mode standard --hero 줄진 --recommendations
python -m catfish preview --page 6
python -m unittest discover -s tests -v
```

`--recommendations`는 `/히오스 무영대 영웅:가즈로`나 `/히오스 빠대 영웅:줄진`과 같은 두 기준 비교 카드를 만듭니다. 이때 빌드는 정렬·최소 게임 수 옵션과 관계없이 전체 후보에서 선택합니다. 옵션을 생략하면 로컬 미리보기용 빌드 카드(최대 3개)를 만듭니다.

## 디스코드 연결

1. [Discord Developer Portal](https://discord.com/developers/applications)에서 애플리케이션을 만들고 **Bot**에서 봇 토큰을 발급합니다. 같은 화면의 **Privileged Gateway Intents → Message Content Intent**를 켭니다. 일반 채팅 단축 입력을 읽는 데 필요합니다.
2. `.env.example`을 `.env`로 복사하고 `DISCORD_TOKEN`을 입력합니다. `DISCORD_GUILD_ID`에 서버 ID를 입력하면 해당 서버에 슬래시 명령을 등록하고, 비워 두면 전역으로 등록합니다. 서버 ID는 디스코드 개발자 모드를 켠 후 서버 우클릭 → ID 복사로 확인할 수 있습니다.
3. OAuth2 URL Generator에서 `bot`과 `applications.commands`를 선택하고 **View Channels, Send Messages, Embed Links, Attach Files** 권한으로 본인 서버에 초대합니다. 권한 숫자는 `52224`입니다.
4. 아래 명령으로 실행합니다.

```bash
cp .env.example .env
# .env에서 DISCORD_TOKEN, DISCORD_GUILD_ID 편집
python -m catfish run
```

시작할 때 설정한 범위에 `/히오스` 슬래시 명령을 갱신합니다. 서버 등록을 사용하면 기존 전역 `/히오스`를 정리하고, 예전 `/히오스상세`는 전역 및 설정한 서버에서 삭제합니다. 봇은 Gateway 연결로 명령을 처리하므로 HTTP Interactions Endpoint URL은 설정하지 않아도 됩니다.

명령어 코드가 변경되면 실행 중인 봇을 재시작하세요.

오프라인 테스트와 미리보기로 조회·렌더링을 검증합니다. 실제 디스코드 로그인과 서버 응답은 별도로 확인해야 합니다. `.env`와 원본 HAR는 Git에서 제외됩니다.

## 데이터의 의미와 현재 샘플

현재 제공된 두 HAR의 데이터는 다음과 같습니다.

| 항목 | 무작위 영웅 대전 | 빠른 대전 & 영웅 리그 |
| --- | --- | --- |
| 원본 파일 | `heroesprofile-ar-20260927.har` | `heroesprofile-qmsl-20260927.har` |
| 게임 모드 필터 | `ar` | `qm` + `sl` 통합 |
| 영웅 성능 | 84명 | 90명 |
| 빌드 후보 | 영웅마다 7개, 총 588개 | 영웅마다 7개, 총 630개 |
| 이미지 | 특성 아이콘 741개, 초상화 84개 | 특성 아이콘 833개, 초상화 90개 |
| 성능 수집 시각 | 2026-09-27 07:00 KST | 2026-09-27 17:13 KST |
| 적용 패치 | `2.55.17.98025`, `2.55.17.97771` | `2.55.17.98025`, `2.55.17.97771` |
| 빌드 후보 생성 방식 | Heroes Profile `HP Algorithm` | Heroes Profile `HP Algorithm` |

‘현재 성능’은 **가장 최근에 가져온 HAR의 통계**를 의미합니다. 사이트를 실시간으로 조회하거나 자동 갱신하지 않습니다. 티어표·성능 차트에는 수집 시각과 패치를 표시합니다. 빌드의 수집 시각과 패치는 해당 모드의 `data/*.json`에서 확인할 수 있으며, 빌드 순위는 저장된 후보 안에서 정렬한 결과입니다.

영웅명과 특성명은 한국어로 표시합니다. 특성명은 [HeroesToolChest의 게임 추출 데이터](https://github.com/HeroesToolChest/heroes-data2) 중 `2.55.17.98025` 패치의 한국어 문자열을 사용하며, 특성 내부 ID로 연결합니다. 이름 사전은 `assets/localization/`에 포함되어 봇 실행 중 네트워크 요청 없이 사용합니다. 사전에 없는 새 특성은 원본 이름을 표시합니다. 사전의 출처·고정 커밋·원본 해시는 JSON에 기록되어 있으며, 갱신할 때는 `python3 scripts/update_talent_names.py --version <패치> --revision <커밋 해시>`를 실행합니다.

## 새 데이터 추가

1. 브라우저 개발자 도구의 Network에서 기록을 켜고 Heroes Profile의 영웅 성능 페이지를 엽니다.
2. 게임 모드와 패치 등 필터를 설정하고 필요한 영웅들의 빌드 화면을 열어 로딩을 마칩니다. 통계와 빌드의 필터는 같아야 합니다. 전체 빌드를 갱신하려면 모든 대상 영웅의 빌드 응답이 기록에 있어야 합니다.
3. **응답 본문이 포함된 HAR**로 저장하여 `imports/`에 넣습니다. 아이콘이 캐시에만 남아 HAR에 빠진 경우, Network의 캐시 비활성화 후 다시 로딩해 저장하세요.
4. 가져오기를 실행합니다. 실행 중인 봇은 다음 조회부터 새 JSON을 읽습니다.

```bash
python -m catfish import
# 특정 파일만 가져오기
python -m catfish import imports/new-capture.har
# 저장 디렉터리를 지정하려면
python -m catfish --data-dir data import imports/new-capture.har
```

무작위 대전은 `game_type: ["ar"]`, 빠른 대전·리그 통합은 `["qm", "sl"]` 또는 이전 영웅 리그의 `["qm", "hl"]` 필터를 인식합니다. 사이트의 현재 리그 이름은 폭풍 리그일 수 있으며 봇에서는 요청한 두 모드 구분을 유지합니다. 빠른 대전과 리그를 함께 선택한 HAR를 가져오세요. 서로 따로 수집한 모드의 승률을 평균내지 않습니다.

같은 HAR에 여러 통계 응답이 있으면 모드별 최신 성능 응답과 필터가 일치하는 빌드만 선택합니다. `202` 비동기 빌드 요청도 작업 ID로 최종 응답과 연결합니다. 기존 데이터보다 오래된 성능 스냅샷은 덮어쓰지 않습니다. 모드별 파일을 교체하는 방식이므로 새 HAR에 빠진 빌드를 과거 HAR에서 이어 붙이지 않습니다. 누락된 빌드·이미지는 가져오기 결과의 경고로 확인할 수 있습니다.

`DATA_DIR`을 `.env`에 지정하면 가져오기·미리보기·봇 실행에 동일하게 적용됩니다. `--data-dir`을 지정하면 우선 적용합니다. 의존성 설치 전에도 `python3 -m catfish.importer imports/example.har --output data`로 가져오기만 실행할 수 있습니다. JSON과 필요한 이미지만 `data/`에 저장하고 쿠키·인증 헤더·관련 없는 요청은 내보내지 않습니다.

## Git으로 변경 관리

프로젝트 루트에서 변경 내용을 확인하고 커밋합니다.

```bash
git status
git diff
git add .
git diff --cached --stat
git commit -m "변경 내용 요약"
git push
```

소스 코드, 테스트, 의존성 목록, 폰트와 라이선스, `.env.example`을 관리합니다. 실제 토큰이 들어 있는 `.env`와 `.env.*` 설정 파일(`.env.example` 제외), 가상환경, 원본 HAR, `data/`의 데이터와 `previews/`의 미리보기는 `.gitignore`로 제외합니다. 제외된 파일은 로컬에 그대로 남지만 Git으로 복구하거나 다른 PC로 전달할 수 없으므로 필요하면 별도로 보관하세요.

다른 PC에서 저장소를 복제한 뒤에는 설치 절차에 따라 가상환경과 의존성을 준비하고, `.env.example`을 `.env`로 복사해 설정합니다. 필요한 HAR를 `imports/`에 넣고 `python -m catfish import`를 실행해 데이터를 다시 생성하세요.

## 파일 구조

```text
catfish/
  importer.py   HAR → 모드별 JSON / 이미지
  data.py       정렬, 티어 분류, 필터, 검색, 페이지 조회
  heroes.py     한국어 영웅명과 별칭
  talents.py    게임 특성 ID → 한국어 특성명
  query.py      영웅·모드 입력과 모드 별칭 해석
  render.py     PNG 전체 티어표 / 성능 차트 / 빌드 카드
  bot.py        /히오스 슬래시 명령 / 영웅 이름 입력 / 채팅 단축 입력
  __main__.py   import / preview / run 실행
assets/fonts/   Noto Sans KR 및 OFL 라이선스
assets/localization/  한국어 특성명 사전 / 출처 / MIT 라이선스
scripts/        한국어 특성명 사전 갱신
imports/        원본 HAR (Git 제외)
data/           가져온 JSON / 아이콘 (Git 제외)
previews/       로컬 미리보기 PNG (Git 제외)
tests/          가져오기 / 조회 / 렌더링 / 봇 오프라인 검증
```

한글 폰트는 [Google Fonts의 Noto Sans KR](https://github.com/google/fonts/tree/main/ofl/notosanskr)을 포함하며 `assets/fonts/OFL.txt`의 SIL Open Font License를 따릅니다. 영웅·특성 이미지는 제공된 Heroes Profile HAR에서 추출합니다.
