# 한국어 특성명

`talents.ko-KR.json`은 Heroes of the Storm 게임 클라이언트의 한국어 특성명을
[HeroesToolChest/heroes-data2](https://github.com/HeroesToolChest/heroes-data2)에서
추출한 카탈로그입니다. 임의 번역 없이 게임의 `KOKR` 문자열을 사용합니다.

- 게임 버전: `2.55.17.98025`
- 원본 커밋: `52f5cb7ad081ad1439a414c36b70c6e42b4526aa`
- 특성명: 1,909개
- 원본 라이선스: MIT, [원문](LICENSE.heroes-data2.txt)
- 각 입력 파일 URL과 SHA-256은 카탈로그의 `source.files`에 기록합니다.

원본은 `2.55.16.97039`의 전체 게임 문자열에 후속 버전의 JSON Patch를 차례로
적용하는 형식입니다. 최신 PTR을 그대로 사용하지 않고 통계 수집 시점의 정식
게임 버전에 맞췄습니다. 영웅 전체의 특성명을 포함하므로 새로운 빌드를 가져와도
해당 버전의 특성은 바로 한글로 표시합니다.

Heroes Profile의 `talent_name`은 게임 내부 특성 ID입니다. 그 ID에서 대소문자와
문장부호를 제거한 값으로 찾습니다. 표시 이름, 아이콘, 특성 위치로 추측해서
연결하지 않습니다. 아직 카탈로그에 없는 ID는 수집한 원래 특성명을 표시합니다.
봇을 실행할 때 네트워크 요청을 하지 않으며 수집 JSON도 수정하지 않습니다.

## 다시 생성하기

프로젝트 루트에서 실행합니다. Python 표준 라이브러리만 사용합니다.

```sh
python scripts/update_talent_names.py
```

게임 패치를 바꾸려면 해당 버전이 들어 있는 커밋을 명시합니다.

```sh
python scripts/update_talent_names.py --version 2.55.17.98025 --revision 52f5cb7ad081ad1439a414c36b70c6e42b4526aa
```

동일한 커밋을 체크아웃한 로컬 원본이 있으면 `--source-dir /path/to/heroes-data2`로
네트워크 없이 생성할 수 있습니다. 원본에 비어 있는 번역이나 서로 다른 이름으로
정규화되는 ID가 발견되면 생성이 실패하므로 이를 확인한 후 갱신합니다.

원본 저장소는 Heroes Data Parser로 게임 데이터를 추출합니다. 게임 명칭과
문자열에 대한 권리는 해당 권리자에게 있습니다.
