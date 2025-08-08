# koko_crawler.py

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import time

BASE_URL = "https://koko.by/category/cafehouse"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

def crawl_cafehouse_pages(max_pages=10, delay=1.0):
    """
    인피니트 스크롤 방식 대응:
    - 첫 페이지: BASE_URL
    - 2페이지부터: BASE_URL + '?page=N'
    """
    results = []
    seen = set()
    for page in range(1, max_pages+1):
        if page == 1:
            url = BASE_URL
        else:
            url = f"{BASE_URL}?page={page}"
        print(f"🔍 크롤링 중: {url}")
        res = requests.get(url, headers=HEADERS)
        if res.status_code != 200:
            print(f"⛔️ 페이지 {page} 요청 실패: {res.status_code}")
            break

        soup = BeautifulSoup(res.text, "html.parser")
        items = soup.select("a[href*='/category/cafehouse/']")
        new_count = 0
        for a in items:
            href = a.get("href").strip()
            title = a.get_text(strip=True)
            if not title or href.rstrip("/") == BASE_URL.rstrip("/"):
                continue
            full_url = urljoin(BASE_URL, href)
            if full_url in seen:
                continue
            seen.add(full_url)
            results.append({"title": title, "url": full_url})
            new_count += 1

        if new_count == 0:
            print("✅ 더 이상 새로운 게시글이 없음. 종료.")
            break

        time.sleep(delay)

    print(f"🔗 총 {len(results)}개 게시글 수집됨")
    return results

if __name__ == "__main__":
    posts = crawl_cafehouse_pages()
    for p in posts:
        print(f"- {p['title']} → {p['url']}")
