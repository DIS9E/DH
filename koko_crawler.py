# koko_crawler.py

import requests, time
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BASE_URL = "https://koko.by/category/cafehouse"
HEADERS  = {"User-Agent":"Mozilla/5.0"}

def crawl_cafehouse_pages(max_pages=5, delay=1.0):
    results, seen = [], set()
    for page in range(1, max_pages+1):
        url = BASE_URL if page==1 else f"{BASE_URL}?page={page}"
        print(f"🔍 크롤링 중: {url}")
        res = requests.get(url, headers=HEADERS)
        if res.status_code!=200: break

        soup = BeautifulSoup(res.text, "html.parser")
        cards = soup.select("div.w-post-name a.name__link")
        new_count = 0

        for a in cards:
            href, title = a["href"].strip(), a.get_text(strip=True)
            full = urljoin(BASE_URL, href)
            if full in seen or not title: continue
            seen.add(full)
            results.append({"title": title, "url": full})
            new_count += 1

        if new_count==0:
            print("✅ 더 이상 새로운 게시글이 없음. 종료.")
            break

        time.sleep(delay)

    print(f"🔗 총 {len(results)}개 게시글 수집됨")
    return results
