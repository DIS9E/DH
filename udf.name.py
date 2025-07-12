import requests
import json
import os
from bs4 import BeautifulSoup, NavigableString, Tag

BASE_URL = "https://udf.name/news/"
HEADERS = {"User-Agent": "Mozilla/5.0"}
SEEN_FILE = "seen_urls.json"

# ✅ 이전에 본 URL 로딩
def load_seen_urls():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()

# ✅ 크롤링 완료 후 URL 저장
def save_seen_urls(urls):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(urls), f, ensure_ascii=False, indent=2)

# ✅ 기사 링크 수집
def get_article_links():
    response = requests.get(BASE_URL, headers=HEADERS)
    if response.status_code != 200:
        print(f"❌ 메인 페이지 요청 실패: {response.status_code}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if (
            href.startswith("https://udf.name/news/") and
            href.endswith(".html") and
            href.count("/") >= 5
        ):
            links.append(href)
    return list(set(links))

# ✅ 본문 추출 함수
def extract_article(url):
    response = requests.get(url, headers=HEADERS)
    if response.status_code != 200:
        print(f"❌ 요청 실패: {url} | {response.status_code}")
        return None

    soup = BeautifulSoup(response.text, "html.parser")

    title = soup.find("h1", class_="newtitle")
    title_text = title.get_text(strip=True) if title else "제목 없음"

    author = soup.find("div", class_="author")
    author_text = author.get_text(strip=True) if author else "출처 없음"

    image = soup.find("img", class_="lazy")
    image_url = "https://udf.name" + image["data-src"] if image else None

    content_block = soup.find("div", id="zooming")
    content_lines = []
    if content_block:
        for el in content_block.descendants:
            if isinstance(el, NavigableString):
                txt = el.strip()
                if txt:
                    content_lines.append(txt)
            elif isinstance(el, Tag) and el.name in ["p", "br"]:
                content_lines.append("\n")

    content = "\n".join(line for line in content_lines if line.strip())
    content = content.replace("dle_leech_begin", "").replace("dle_leech_end", "")
    content = content.strip()

    return {
        "title": title_text,
        "author": author_text,
        "image": image_url,
        "url": url,
        "content": content
    }

# ✅ 실행 메인
if __name__ == "__main__":
    print("🔍 크롤링 시작")

    seen = load_seen_urls()
    all_links = get_article_links()

    new_links = [link for link in all_links if link not in seen]
    print(f"📰 수집된 기사 수: {len(new_links)}")

    for link in new_links:
        article = extract_article(link)
        if article and article["content"]:
            print("\n📰 [기사 제목]", article["title"])
            print("👤 [출처]", article["author"])
            print("🖼 [이미지]", article["image"])
            print("🔗 [URL]", article["url"])
            print("\n📄 [본문 내용]")
            print(article["content"][:500] + "..." if len(article["content"]) > 500 else article["content"])

            # URL 저장
            seen.add(link)

    save_seen_urls(seen)
    print("\n✅ 크롤링 완료")