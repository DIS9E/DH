# tag_generator.py
# -*- coding: utf-8 -*-
"""
tag_generator.py
WordPress 게시글 자동 태그 생성 모듈
- article_data(딕셔너리)를 받아서 공개 태그 목록을 반환합니다.

필요 시 로직을 확장해 본문 어휘, 도시명, 메뉴 키워드 등을 기반으로 태그를 생성하세요.
"""

def generate_tags_for_post(article_data: dict) -> list[str]:
    """
    article_data 예시:
      {
        "title": str,
        "content": str,
        "menu_items": list[str],
        "reviews": list[str]
      }

    간단한 태그 생성 예:
      1) 제목에서 도시 추출 (민스크 등)
      2) 메뉴 아이템 키워드
      3) 음식 카테고리(한식, 양식 등)
    """
    tags = set()
    title = article_data.get("title", "").lower()
    content = article_data.get("content", "").lower()

    # 1) 도시 태그
    cities = ["минск", "гродно", "гомель", "витебск", "брест"]
    for city in cities:
        if city in title or city in content:
            tags.add(city.capitalize())

    # 2) 메뉴 태그
    for item in article_data.get("menu_items", []):
        # 예: '치즈 케이크 BYN5' -> '치즈 케이크'
        name = item.split()[0]
        tags.add(name)

    # 3) 리뷰 태그 (간단히 리뷰 첫 단어)
    for review in article_data.get("reviews", []):
        first_word = review.split()[0].strip('"')
        tags.add(first_word)

    return list(tags)
``` 
