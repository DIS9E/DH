# parser.py
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re

def parse_post(url: str) -> dict:
    print(f"📄 파싱 중: {url}")
    r = requests.get(url, timeout=10)
    soup = BeautifulSoup(r.text, "html.parser")

    title = soup.select_one("h1.entry-title").text.strip()
    content_div = soup.select_one("div.tdb_single_content")
    html_content = str(content_div)

    # 예시: 주소, 시간, 전화, 지도, 이미지 파싱
    address = soup.find(string=re.compile("Адрес|주소")) or ""
    hours = soup.find(string=re.compile("Время работы|영업시간")) or ""
    phone = soup.find(string=re.compile(r"\+375")) or ""

    images = [img["src"] for img in content_div.select("img") if img.get("src")]

    map_iframe = soup.select_one("iframe")
    map_url = map_iframe["src"] if map_iframe else None

    return {
        "title": title,
        "html": html_content,
        "address": address.strip(),
        "hours": hours.strip(),
        "phone": phone.strip(),
        "images": images,
        "map_url": map_url,
        "source_url": url,
    }
