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

    # 제목
    title_tag = soup.select_one("h1.pagetitle.posttitle._js-pagetitle-text")
    title = title_tag.get_text(strip=True) if title_tag else "제목 없음"

    # 본문 영역: 제목 다음 형제들 중 태그 영역 전까지 수집
    body_nodes = []
    if title_tag:
        for sib in title_tag.find_next_siblings():
            # 태그 리스트 진입 전까지
            if sib.name == "div" and sib.get("class") and "text" in sib.get("class"):
                break
            body_nodes.append(sib)

    # 원본 HTML 내용(재작성에 활용)
    html_content = "".join(str(node) for node in body_nodes)

    # 주소 추출
    address_tag = soup.find("div", class_="text", string=re.compile(r"пр\.|ул\."))
    address = address_tag.get_text(strip=True) if address_tag else "정보 없음"

    # 영업시간 추출
    hours = []
    for tag in soup.find_all("div", string=re.compile(r"(с \d{1,2}:\d{2}|до \d{1,2}:\d{2})")):
        hours.append(tag.get_text(strip=True).replace("—", "-"))
    hours = "\n".join(hours) if hours else "정보 없음"

    # 전화번호 (선택)
    phone = ""  # 이 사이트에는 전화번호가 없을 수 있음

    # 메뉴 항목 ("… за XXр" 패턴)
    menu_items = re.findall(r"[А-Яа-я\w\s]+? за \d+р", html_content)

    # 리뷰 (strong 또는 blockquote에서 최대 3개)
    reviews = [t.get_text(strip=True) for t in BeautifulSoup(html_content, "html.parser").find_all(["strong", "blockquote"])][:3]

    # 이미지 URL 수집
    images = []
    for img in soup.select("img[src]"):
        src = img["src"]
        images.append(urljoin(url, src))

    # 지도 iframe URL
    iframe = soup.find("iframe")
    map_url = iframe.get("src", "") if iframe else ""

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


if __name__ == "__main__":
    sample = "https://koko.by/cafehouse/13610-tako-burrito"
    from pprint import pprint
    pprint(parse_post(sample))
