import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re

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

    # ────────── 제목 ──────────
    title_tag = soup.select_one("h1.pagetitle.posttitle._js-pagetitle-text")
    title = title_tag.get_text(strip=True) if title_tag else "제목 없음"

    # ────────── 본문 HTML ──────────
    content_div = soup.select_one("div.text")
    html_content = str(content_div) if content_div else ""

    # ────────── 주소 추출 ──────────
    address = "정보 없음"
    addr_patterns = re.compile(r"(ул\.|пр\.|г\.|дом|улица)", re.IGNORECASE)
    for tag in soup.find_all("div", class_="text"):
        if addr_patterns.search(tag.get_text()):
            address = tag.get_text(strip=True)
            break

    # ────────── 영업시간 ──────────
    hours = []
    hour_pattern = re.compile(r"(с\s*\d{1,2}:\d{2}\s*до\s*\d{1,2}:\d{2})", re.IGNORECASE)
    for tag in soup.find_all(text=hour_pattern):
        h = hour_pattern.search(tag)
        if h:
            hours.append(h.group(1))
    hours = "\n".join(hours) if hours else "정보 없음"

    # ────────── 전화번호 (현재 없음) ──────────
    phone = ""

    # ────────── 메뉴 항목 ──────────
    menu_items = re.findall(r"[А-Яа-я\w\s]+? за \d+р", html_content)

    # ────────── 리뷰 (strong, blockquote 기반) ──────────
    reviews = [t.get_text(strip=True) for t in BeautifulSoup(html_content, "html.parser").find_all(["strong", "blockquote"])]
    reviews = reviews[:3]

    # ────────── 이미지 ──────────
    images = []
    post_section = soup.select_one("div.text") or soup
    for img in post_section.select("img[src]"):
        src = img.get("src")
        if src and not src.startswith("data:"):
            images.append(urljoin(url, src))

    # ────────── 지도 URL (얀덱스 iframe만) ──────────
    iframe = soup.select_one("iframe[src*='yandex']")
    map_url = iframe["src"] if iframe else ""

    return {
        "title": title,
        "html": html_content,
        "address": address,
        "hours": hours,
        "phone": phone,
        "menu_items": menu_items,
        "reviews": reviews,
        "images": images,
        "map_url": map_url,
        "source_url": url
    }

# 테스트
if __name__ == "__main__":
    sample = "https://koko.by/cafehouse/13610-tako-burrito"
    from pprint import pprint
    pprint(parse_post(sample))

if __name__ == "__main__":
    sample = "https://koko.by/cafehouse/13610-tako-burrito"
    from pprint import pprint
    pprint(parse_post(sample))
