#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
koko_crawler.py – koko.by/category/cafehouse 전용 크롤러
• 첫 페이지 파싱 → CSRF 토큰 & 초기 링크 수집
• /load-more AJAX 호출로 다음 글들 순차 로드
"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import time

BASE_PAGE = "https://koko.by/category/cafehouse"
LOAD_MORE = "https://koko.by/load-more"
HEADERS   = {"User-Agent": "Mozilla/5.0"}

def crawl_cafehouse_pages(delay=1.0):
    session = requests.Session()
    session.headers.update(HEADERS)

    # 1) 첫 페이지
    print("🔍 첫 페이지 로드:", BASE_PAGE)
    res = session.get(BASE_PAGE)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")

    # CSRF 토큰 추출
    token_tag = soup.select_one("meta[name='csrf-token']")
    csrf = token_tag["content"] if token_tag else ""

    posts = []
    seen  = set()

    # 초기 링크
    for a in soup.select("div.w-post-name a.name__link"):
        href  = a["href"].strip()
        title = a.get_text(strip=True)
        full  = urljoin(BASE_PAGE, href)
        if full not in seen:
            seen.add(full)
            posts.append({"title": title, "url": full})

    # 2) AJAX 로드
    while True:
        offset = len(posts)
        print(f"🔍 AJAX 로드 – offset={offset}")
        data = {
            "offset": offset,
            "url": "/category/cafehouse"
        }
        headers = {
            "X-CSRF-Token": csrf,
            "Referer":      BASE_PAGE
        }
        ajax = session.post(LOAD_MORE, data=data, headers=headers)
        ajax.raise_for_status()

        # JSON 페이로드에 'content' 키가 있는지 확인
        try:
            payload = ajax.json()
            html    = payload.get("content", ajax.text)
        except ValueError:
            html = ajax.text

        snippet = BeautifulSoup(html, "html.parser")
        new_items = snippet.select("div.w-post-name a.name__link")
        if not new_items:
            print("✅ 더 이상 새로운 게시글 없음. 종료.")
            break

        for a in new_items:
            href  = a["href"].strip()
            title = a.get_text(strip=True)
            full  = urljoin(BASE_PAGE, href)
            if full not in seen:
                seen.add(full)
                posts.append({"title": title, "url": full})

        time.sleep(delay)

    print(f"🔗 총 {len(posts)}개 게시글 수집됨")
    return posts


if __name__ == "__main__":
    for p in crawl_cafehouse_pages():
        print("-", p["title"], "→", p["url"])
