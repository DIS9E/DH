#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
koko_crawler.py – koko.by/category/cafehouse 전용 크롤러
• 첫 페이지 파싱 → CSRF 토큰 & 초기 링크 수집
• /load-more AJAX 호출로 다음 글들 순차 로드
• 최대 max_posts개까지만 수집
"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import time

BASE_PAGE = "https://koko.by/category/cafehouse"
LOAD_MORE = "https://koko.by/load-more"
HEADERS   = {"User-Agent": "Mozilla/5.0"}

def crawl_cafehouse_pages(delay=1.0, max_posts=50):
    session = requests.Session()
    session.headers.update(HEADERS)

    # 1) 첫 페이지 로드
    print("🔍 첫 페이지 로드:", BASE_PAGE)
    res = session.get(BASE_PAGE)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")

    # 2) CSRF 토큰 추출
    token_tag = soup.select_one("meta[name='csrf-token']")
    csrf = token_tag["content"] if token_tag and token_tag.has_attr("content") else ""

    posts = []
    seen  = set()

    # 3) 초기 링크 수집
    for a in soup.select("div.w-post-name a.name__link"):
        href  = a["href"].strip()
        title = a.get_text(strip=True)
        full  = urljoin(BASE_PAGE, href)
        if full not in seen:
            seen.add(full)
            posts.append({"title": title, "url": full})
        if len(posts) >= max_posts:
            print(f"🔗 최대 {max_posts}개 수집 도달. 종료.")
            return posts

    # 4) AJAX 로드 반복
    while True:
        offset = len(posts)
        if offset >= max_posts:
            print(f"🔗 최대 {max_posts}개 수집 도달. 종료.")
            break

        print(f"🔍 AJAX 로드 – offset={offset}")
        files = {
            "offset": (None, str(offset)),
            "url":    (None, "/category/cafehouse")
        }
        headers = {
            "X-CSRF-Token": csrf,
            "Referer":      BASE_PAGE
        }
        ajax = session.post(LOAD_MORE, files=files, headers=headers)
        ajax.raise_for_status()

        # 응답 처리 (JSON 또는 HTML)
        content_type = ajax.headers.get("Content-Type", "")
        if "application/json" in content_type:
            payload = ajax.json()
            html    = payload.get("content", "")
        else:
            html = ajax.text

        if not html.strip():
            print("✅ 더 이상 새로운 게시글 없음. 종료.")
            break

        snippet   = BeautifulSoup(html, "html.parser")
        new_items = snippet.select("div.w-post-name a.name__link")
        if not new_items:
            print("✅ 더 이상 새로운 게시글 없음. 종료.")
            break

        new_count = 0
        for a in new_items:
            href  = a["href"].strip()
            title = a.get_text(strip=True)
            full  = urljoin(BASE_PAGE, href)
            if full not in seen:
                seen.add(full)
                posts.append({"title": title, "url": full})
                new_count += 1
                if len(posts) >= max_posts:
                    print(f"🔗 최대 {max_posts}개 수집 도달. 종료.")
                    return posts

        if new_count == 0:
            print("✅ 더 이상 새로운 게시글 없음. 종료.")
            break

        time.sleep(delay)

    print(f"🔗 총 {len(posts)}개 게시글 수집됨")
    return posts


if __name__ == "__main__":
    posts = crawl_cafehouse_pages()
    for p in posts:
        print("-", p["title"], "→", p["url"])
    # 로컬 테스트용 예시
    example = "https://koko.by/cafehouse/13610-tako-burrito"
    from pprint import pprint
    pprint(parse_post(example))
