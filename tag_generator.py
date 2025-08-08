# tag_generator.py

from typing import List

# 벨라루스 주요 도시
BELARUS_CITIES = [
    "Минск", "Брест", "Гомель", "Гродно", "Витебск", "Могилёв"
]

# 본문에서 찾을 메뉴 키워드 샘플
MENU_KEYWORDS = [
    "taco", "буррито", "шаурма", "плов", "суши", "блины",
    "пельмени", "бургеры", "кофе", "латте", "завтрак", "десерт"
]

# 1차 요리 분류 → 키워드 매핑
CUISINE_TYPES = {
    "양식":     ["паста", "стейк", "бургер", "пицца", "ризотто"],
    "중식":     ["китай", "лапша", "пекин", "мандарин", "дим-сам"],
    "일식":     ["суши", "роллы", "якитори", "рамэн", "сашими"],
    "한식":     ["кимчи", "бибимпап", "токпокки"],
}

# 2차 세부 분류 → 키워드 매핑
SUB_CATEGORIES = {
    "파스타":    ["паста", "спагетти", "карбонара"],
    "피자":     ["пицца", "маргарита", "пепперони"],
    "초밥":     ["суши", "нигири", "маки"],
    "라멘":     ["рамэн", "тоночиру"],
    "만두":     ["пельмени", "вареники"],
    "크레페":    ["блины", "креп"],
}

def extract_tags(text: str) -> List[str]:
    """
    본문(text)을 스캔해서 아래 순서대로 태그를 뽑아 리턴합니다.
    1) 도시
    2) 메뉴 키워드
    3) 1차 요리 분류
    4) 2차 세부 분류
    """
    tags: List[str] = []
    lower = text.lower()

    # 1) 도시
    for city in BELARUS_CITIES:
        if city.lower() in lower and city not in tags:
            tags.append(city)

    # 2) 메뉴 키워드
    for kw in MENU_KEYWORDS:
        if kw in lower and kw not in tags:
            tags.append(kw)

    # 3) 요리 분류
    for cuisine, kws in CUISINE_TYPES.items():
        for kw in kws:
            if kw in lower and cuisine not in tags:
                tags.append(cuisine)
                break

    # 4) 세부 분류
    for subcat, kws in SUB_CATEGORIES.items():
        for kw in kws:
            if kw in lower and subcat not in tags:
                tags.append(subcat)
                break

    return tags


# 예시
if __name__ == "__main__":
    sample = """
    Мы зашли в новое кафе в Минск, где подают отличные бургер и паста карбонара.
    Завтрак здесь начинается с блины и латте.
    """
    print(extract_tags(sample))
    # 출력 예: ['Минск', 'бургер', 'паста', '양식', '파스타', 'завтрак', 'блины']
