"""Korean display names and searchable aliases, independent of imported patches."""

import unicodedata


NAMES = {
    "abathur": "아바투르", "alarak": "알라라크", "alexstrasza": "알렉스트라자",
    "ana": "아나", "anduin": "안두인", "anubarak": "아눕아락", "artanis": "아르타니스",
    "arthas": "아서스", "auriel": "아우리엘", "azmodan": "아즈모단", "blaze": "블레이즈",
    "brightwing": "빛나래", "cassia": "카시아", "chen": "첸", "cho": "초", "chromie": "크로미",
    "deathwing": "데스윙", "deckard": "데커드", "dehaka": "데하카", "diablo": "디아블로",
    "dva": "D.Va", "etc": "정예 타우렌 족장", "falstad": "폴스타트", "fenix": "피닉스",
    "gall": "갈", "garrosh": "가로쉬", "gazlowe": "가즈로", "genji": "겐지",
    "greymane": "그레이메인", "guldan": "굴단", "hanzo": "한조", "hogger": "들창코",
    "illidan": "일리단", "imperius": "임페리우스", "jaina": "제이나", "johanna": "요한나",
    "junkrat": "정크랫", "kaelthas": "캘타스", "kelthuzad": "켈투자드", "kerrigan": "케리건",
    "kharazim": "카라짐", "leoric": "레오릭", "lili": "리 리", "liming": "리밍",
    "ltmorales": "모랄레스 중위", "lucio": "루시우", "lunara": "루나라", "maiev": "마이에브",
    "malfurion": "말퓨리온", "malganis": "말가니스", "malthael": "말티엘", "medivh": "메디브",
    "mei": "메이", "mephisto": "메피스토", "muradin": "무라딘", "murky": "머키",
    "nazeebo": "나지보", "nova": "노바", "orphea": "오르피아", "probius": "프로비우스",
    "qhira": "키히라", "ragnaros": "라그나로스", "raynor": "레이너", "rehgar": "레가르",
    "rexxar": "렉사르", "samuro": "사무로", "sgthammer": "해머 상사", "sonya": "소냐",
    "stitches": "누더기", "stukov": "스투코프", "sylvanas": "실바나스", "tassadar": "태사다르",
    "thebutcher": "도살자", "thelostvikings": "길 잃은 바이킹", "thrall": "스랄",
    "tracer": "트레이서", "tychus": "타이커스", "tyrael": "티리엘", "tyrande": "티란데",
    "uther": "우서", "valeera": "발리라", "valla": "발라", "varian": "바리안",
    "whitemane": "화이트메인", "xul": "줄", "yrel": "이렐", "zagara": "자가라",
    "zarya": "자리야", "zeratul": "제라툴", "zuljin": "줄진",
}

ALIASES = {
    "etc": ("타우렌", "정타족", "소"), "dva": ("디바", "디바송하나"),
    "ltmorales": ("모랄레스", "모랄"), "sgthammer": ("해머",),
    "deckard": ("데커드 케인", "케인"), "thelostvikings": ("바이킹", "길바"),
    "kaelthas": ("켈타스",), "kelthuzad": ("켈투",), "lili": ("리리",),
}


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    return "".join(c for c in value if c.isalnum())


def display_name(hero: dict) -> str:
    return NAMES.get(hero["short_name"], hero["name"])


def search_terms(hero: dict) -> set[str]:
    return {normalize(x) for x in (
        hero["name"], hero["short_name"], display_name(hero),
        *ALIASES.get(hero["short_name"], ()),
    )}
