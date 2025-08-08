# koko_crawler.py

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import time

BASE_PAGE = "https://koko.by/category/cafehouse"
LOAD_MORE = "https://koko.by/load-more"
HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

def crawl_all_posts(delay=1.0):
    session = requests.Session()
    session.headers.update(HEADERS)

    # 1) 첫 페이지 가져오기
    print("🔍 첫 페이지 로드:", BASE_PAGE)
    res = session.get(BASE_PAGE)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")

    # CSRF 토큰 추출
    csrf = soup.select_one("meta[name='csrf-token']")["content"]

    # 초기 게시글 수집 (js-post-item 항목들)
    posts = []
    for a in soup.select("div.w-post-name a.name__link"):
        href = a["href"].strip()
        title = a.get_text(strip=True)
        posts.append({"title": title, "url": urljoin(BASE_PAGE, href)})

    # 2) AJAX를 통한 추가 로드
    while True:
        offset = len(posts)
        print(f"🔍 AJAX 로드 – offset={offset}")

        data = {
            "offset": offset,
            "url": "/category/cafehouse"
        }
        headers = {
            "X-CSRF-Token": csrf,
            "Referer": BASE_PAGE
        }
        ajax = session.post(LOAD_MORE, data=data, headers=headers)
        ajax.raise_for_status()

        # 서버가 반환하는 JSON에 HTML 덩어리가 있을 수도 있으니 확인
        payload = ajax.json() if ajax.headers.get("Content-Type","").startswith("application/json") else {}
        html = payload.get("content", ajax.text)

        snippet = BeautifulSoup(html, "html.parser")
        new_items = snippet.select("div.w-post-name a.name__link")

        if not new_items:
            print("✅ 더 이상 게시글 없음. 종료.")
            break

        for a in new_items:
            href = a["href"].strip()
            title = a.get_text(strip=True)
            full = urljoin(BASE_PAGE, href)
            if full not in {p["url"] for p in posts}:
                posts.append({"title": title, "url": full})

        time.sleep(delay)

    print(f"🔗 총 {len(posts)}개 게시글 수집됨")
    return posts

if __name__ == "__main__":
    all_posts = crawl_all_posts()
    for p in all_posts:
        print("-", p["title"], "→", p["url"])

        time.sleep(delay)

    print(f"🔗 총 {len(results)}개 게시글 수집됨")
    return results
