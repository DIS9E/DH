# koko_crawler.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
koko.by/category/cafehouse 크롤러
• 첫 페이지에서만 모든 게시글 링크+제목 수집
• '/category/cafehouse/' 패턴으로 필터링
"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import time

BASE_URL = "https://koko.by/category/cafehouse"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

def crawl_cafehouse():
    print("🔍 크롤링 시작:", BASE_URL)
    res = requests.get(BASE_URL, headers=HEADERS)
    if res.status_code != 200:
        print(f"⛔️ 요청 실패: {res.status_code}")
        return []

    soup = BeautifulSoup(res.text, "html.parser")
    links = soup.select("a[href*='/category/cafehouse/']")
    results = []
    seen = set()

    for a in links:
        href = a.get("href", "").strip()
        title = a.get_text(strip=True)
        # 본문 리스트 상단의 “/category/cafehouse” 자체 링크는 건너뛰기
        if not title or href.rstrip("/") == BASE_URL.rstrip("/"):
            continue
        url = urljoin(BASE_URL, href)
        if url in seen:
            continue
        seen.add(url)
        results.append({"title": title, "url": url})

    print(f"🔗 총 {len(results)}개 게시글 수집됨")
    return results

if __name__ == "__main__":
    posts = crawl_cafehouse()
    for p in posts:
        print(f"- {p['title']} → {p['url']}")
