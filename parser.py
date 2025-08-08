# parser.py

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
}

def parse_post(url):
    print(f"📄 파싱 중: {url}")
    res = requests.get(url, headers=HEADERS)
    if res.status_code != 200:
        print(f"❌ 요청 실패: {res.status_code}")
        return None

    soup = BeautifulSoup(res.text, "html.parser")

    # 제목
    title = soup.select_one("h1.entry-title")
    title = title.get_text(strip=True) if title else "제목 없음"

    # 본문 내용
    content = soup.select_one("div.entry-content")
    if not content:
        return None

    # 주소, 연락처, 시간 추출
    text = content.get_text("\n", strip=True)

    address = extract_by_keywords(text, ["Адрес", "주소", "Address"])
    hours = extract_by_keywords(text, ["Время работы", "영업시간", "Hours"])
    phone = extract_by_keywords(text, ["Телефон", "전화", "Phone"], optional=True)

    # 메뉴 추출 (단순한 li나 p 안의 가격 정보 등)
    menu_items = []
    for line in text.split("\n"):
        if any(x in line for x in ["BYN", "р", "руб", "원"]):
            menu_items.append(line.strip())

    # 리뷰 (blockquote 또는 strong 사용됨)
    review_tags = content.select("blockquote, strong")
    reviews = [r.get_text(strip=True) for r in review_tags][:3]

    # 이미지 URL들
    image_tags = content.select("img")
    image_urls = [img.get("src") for img in image_tags if img.get("src")]

    # 지도 iframe
    iframe = content.select_one("iframe")
    map_url = iframe.get("src") if iframe else ""

    return {
        "title": title,
        "address": address,
        "hours": hours,
        "phone": phone or "",
        "menu_items": menu_items,
        "reviews": reviews,
        "images": image_urls,
        "map_url": map_url,
        "source_url": url
    }

def extract_by_keywords(text, keywords, optional=False):
    for line in text.split("\n"):
        for key in keywords:
            if key.lower() in line.lower():
                return line.strip()
    return "" if optional else "정보 없음"

if __name__ == "__main__":
    # 테스트용
    sample_url = "https://koko.by/cafehouse/where-to-go-for-coffee-in-minsk"
    result = parse_post(sample_url)
    from pprint import pprint
    pprint(result)
