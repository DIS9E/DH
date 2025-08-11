# tag_generator.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
본문(제목/HTML 본문/리뷰/메뉴/주소)에서 러시아어 키워드를 추출해
한국어 태그로 '매핑'하는 결정론적 태그 생성기.

- GPT 사용 안 함(임의 태그 생성 방지)
- 러시아어(키릴) 키워드를 정규식으로 감지 → 한국어 태그로 변환
- 도시/요리분류/대표메뉴/업태/분위기·가격 느낌 등을 조합
- 결과는 중복 제거 후 최대 12개 반환
"""

from __future__ import annotations
import re
from typing import Dict, List, Iterable, Tuple
from bs4 import BeautifulSoup

# 키릴 문자 단어 경계용 (러시아어, 벨라루스어 함께 커버)
WB = r"(?<![А-Яа-яЁёA-Za-z0-9]){}(?![А-Яа-яЁёA-Za-z0-9])"

def _textify(html: str | None) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "html.parser").get_text(" ", strip=True)

def _norm(x: str | None) -> str:
    return (x or "").strip()

def _contains(text: str, variants: Iterable[str]) -> bool:
    t = text.lower()
    for v in variants:
        if re.search(WB.format(re.escape(v.lower())), t):
            return True
    return False

def _add_if_match(text: str, mapping: Dict[str, Iterable[str]], ktag: str, bag: List[str]):
    # mapping: { 러시아어 or 벨라루스어 표현 : [동의어들...] }
    for v, syns in mapping.items():
        candidates = [v] + list(syns)
        if _contains(text, candidates):
            bag.append(ktag)
            return  # 한 번만 추가

# ──────────────────────────────────────────────────────────────
# 1) 도시 → 한국어 태그(“…맛집”)
CITIES: Dict[str, Iterable[str]] = {
    # 대도시
    "민스크맛집": ["минск", "minsk", "менск"],
    "브레스트맛집": ["брест", "brest"],
    "그로드노맛집": ["гродно", "hrodna", "grodno"],
    "고멜맛집": ["гомель", "homiel", "gomel"],
    "모길료프맛집": ["могилев", "magilëu", "mogilev", "mahilyow", "mahilyou"],
    "비텝스크맛집": ["витебск", "vitebsk", "viciebsk"],

    # 중대형 도시 & 자주 언급되는 곳
    "바라노비치맛집": ["барановичи", "baranovichi"],
    "보브루이스크맛집": ["бобруйск", "bobruisk", "babruysk"],
    "보리소프맛집": ["борисов", "borisov", "barysaw", "barysau", "barysaw"],
    "핀스크맛집": ["пинск", "pinsk"],
    "오르샤맛집": ["орша", "orsha"],
    "리다맛집": ["лида", "lida"],
    "모지르맛집": ["моzyr", "mozyr", "мозырь"],
    "솔리고르스크맛집": ["солигорск", "salihorsk", "soligorsk"],
    "노보폴로츠크맛집": ["новополоцк", "novopolotsk"],
    "폴라츠크맛집": ["полоцк", "polotsk", "polack"],
    "졸디노맛집": ["жодино", "zhodino"],
    "레치차맛집": ["речица", "rechytsa", "rechitsa"],
    "슬루츠크맛집": ["слуцк", "slutsk"],
    "스몰곤맛집": ["сморгонь", "smorgon"],
}

# 2) 업태
VENUE: Dict[str, Iterable[str]] = {
    "카페": ["кафе", "кофейня"],
    "레스토랑": ["ресторан", "трактир", "гостиной"],
    "바": ["бар", "паб", "винный бар", "гастробар"],
    "비스트로": ["бистро"],
    "푸드코트": ["столовая", "фудкорт"],
}

# 3) 요리 대분류/중분류/대표 메뉴
CUISINE: List[Tuple[str, Dict[str, Iterable[str]]]] = [
    ("양식", {"итальян": ["итал", "пицца", "паста"]}),
    ("일식",  {"япон": ["суши", "ролл", "рамаен", "рамэн", "рамен", "удон"]}),
    ("중식",  {"китай": ["лапша", "доширак", "рис", "бао", "вок"]}),
    ("한식",  {"корей": ["кимчи", "чимчи", "пибимпап", "пибимбап", "ттокпокки"]}),
    ("동유럽", {"узбек": ["плов", "манты", "самса"], "грузин": ["хачапури", "шашлык", "аджика"]}),
    ("멕시칸", {"мексикан": ["тако", "буррито", "начос", "сальса"]}),
]

DISHES: Dict[str, Iterable[str]] = {
    "피자": ["пицца"],
    "파스타": ["паста"],
    "초밥": ["суши"],
    "롤": ["ролл", "роллы"],
    "라멘": ["рамен", "рамэн", "рамен"],
    "우동": ["удон"],
    "샤슬릭": ["шашлык"],
    "샤워마": ["шаурма", "шаверма", "донер"],
    "버거": ["бургер", "бургеры"],
    "스테이크": ["стейк", "стейки"],
    "플로프": ["плов"],
    "만티": ["манты"],
    "삼사": ["самса"],
    "블리니": ["блины"],
    "펠메니": ["пельмени"],
    "보르щ": ["борщ"],
    "핫도그": ["хот-дог", "хотдог"],
    "타코": ["тако"],
    "부리또": ["буррито"],
    "커피": ["кофе", "эспрессо", "капучино", "латте", "раф"],
    "디저트": ["десерт", "мороженое", "эклер", "чизкейк", "наполеон"],
}

# 4) 분위기/가격 느낌
VIBES: Dict[str, Iterable[str]] = {
    "분위기좋은": ["атмосфер", "уютн", "лампов", "интерьер"],
    "가성비": ["недорог", "дешев"],
    "프리미엄": ["дорог", "премиум"],
    "데이트": ["романтич", "свидан"],
    "가족모임": ["семейн"],
    "테라스": ["террас"],
}

# 최대 태그 수
MAX_TAGS = 12

def generate_tags_for_post(article: dict) -> List[str]:
    """
    본문에서 도시/업태/요리/메뉴/분위기 키워드를 감지해 한국어 태그 목록 생성.
    반환: 한국어 태그 리스트(중복 제거, 최대 12개)
    """
    title = _norm(article.get("title"))
    html  = _norm(article.get("content"))  # HTML일 수도 있음
    menu_items = article.get("menu_items") or []
    reviews    = article.get("reviews") or []
    address    = _norm(article.get("address"))  # 있으면 가산점

    text = " ".join([
        title,
        _textify(html),
        "\n".join(menu_items),
        "\n".join(reviews),
        address,
    ]).lower()

    tags: List[str] = []

    # 0) 기본 지역 대분류(벨라루스맛집) + 민스크 등 도시 감지
    tags.append("벨라루스맛집")
    for ktag, variants in CITIES.items():
        if _contains(text, variants):
            tags.append(ktag)

    # 1) 업태
    for ktag, variants in VENUE.items():
        if _contains(text, variants):
            tags.append(ktag)

    # 2) 요리 대분류
    for ktag, group in CUISINE:
        for v, syns in group.items():
            if _contains(text, [v] + list(syns)):
                tags.append(ktag)
                break  # 한 대분류당 한 번만

    # 3) 대표 메뉴
    for ktag, variants in DISHES.items():
        if _contains(text, variants):
            tags.append(ktag)

    # 4) 분위기/가격
    for ktag, variants in VIBES.items():
        if _contains(text, variants):
            tags.append(ktag)

    # 5) 타이틀 기반 핵심 보강: “민스크맛집”이 없고 민스크가 감지되면 추가
    if "민스크맛집" not in tags and _contains(text, CITIES["민스크맛집"]):
        tags.append("민스크맛집")

    # 정리: 중복 제거 → 길이 제한
    seen = set()
    deduped: List[str] = []
    for t in tags:
        t = t.strip()
        if not t or t in seen:
            continue
        seen.add(t)
        deduped.append(t)
        if len(deduped) >= MAX_TAGS:
            break

    return deduped
