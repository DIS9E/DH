# koko_crawler.py

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import time

BASE_URL = "https://koko.by/category/cafehouse"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

def crawl_cafehouse_pages(base_url=BASE_URL, max_pages=50, delay=1.0):
    results = []
    page = 1

    while True:
        print(f"🔍 크롤링 중: 페이지 {page}")
        url = f"{base_url}/page/{page}/" if page > 1 else base_url
        res = requests.get(url, headers=HEADERS)

        if res.status_code != 200:
            print(f"⛔️ 페이지 {page} 요청 실패: {res.status_code}")
            break

        soup = BeautifulSoup(res.text, "html.parser")
        articles = soup.select("article")

        if not articles:
            print("✅ 더 이상 게시글 없음. 종료.")
            break

        for article in articles:
            a_tag = article.select_one("a")
            title = a_tag.get("title", "").strip()
            link = a_tag.get("href", "").strip()
            if title and link:
                results.append({"title": title, "url": link})

        page += 1
        if page > max_pages:
            print("📛 최대 페이지 수 도달")
            break

        time.sleep(delay)  # 과도한 요청 방지용 딜레이

    return results

if __name__ == "__main__":
    posts = crawl_cafehouse_pages()
    print(f"🔗 총 {len(posts)}개 게시글 수집됨")
    for p in posts[:3]:  # 샘플 출력
        print(f"- {p['title']} → {p['url']}")
