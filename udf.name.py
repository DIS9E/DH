#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
udf.name.py – v3.1-no-media  (대표 이미지 WP 업로드 생략 버전)
─────────────────────────────────────────────────────────────────────────────
• 카테고리: ‘벨라루스 뉴스’(slug=belarus-news) ID 자동 조회
• 태그: ChatGPT가 출력한 키프레이즈 → 동적 생성/지정
• 대표 이미지: WP 업로드 생략, 본문 첫줄 <img src="..."> 삽입
• 중복 방지: HTML 주석 <!--source_url:...--> + REST search
"""

import os, sys, json, time, logging, re
from urllib.parse import urljoin, urlparse, urlunparse
import requests
from requests.auth import HTTPBasicAuth
from bs4 import BeautifulSoup

# ───────────────────── 1. 환경
WP_URL          = os.getenv("WP_URL", "https://belatri.info").rstrip("/")
WP_USERNAME     = os.getenv("WP_USERNAME")
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD")
OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY")

if not all([WP_USERNAME, WP_APP_PASSWORD, OPENAI_API_KEY]):
    sys.exit("❌  WP_USERNAME / WP_APP_PASSWORD / OPENAI_API_KEY 필요")

WP_POSTS_API = f"{WP_URL}/wp-json/wp/v2/posts"
WP_TAGS_API  = f"{WP_URL}/wp-json/wp/v2/tags"
WP_CATS_API  = f"{WP_URL}/wp-json/wp/v2/categories"

UDF_BASE      = "https://udf.name/news/"
UA_HEADER     = {"User-Agent": "UDFCrawler/3.1-no-media"}
SEEN_FILE     = "seen_urls.json"
CATEGORY_SLUG = "belarus-news"

# ───────────────────── 2. 카테고리 ID
def get_category_id(slug: str) -> int:
    r = requests.get(WP_CATS_API, params={"slug": slug, "per_page": 1},
                     auth=HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD), timeout=20)
    if r.status_code == 200 and r.json():
        return r.json()[0]["id"]
    c = requests.post(WP_CATS_API,
                      json={"name": "벨라루스 뉴스", "slug": slug},
                      auth=HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD), timeout=20)
    c.raise_for_status();  return c.json()["id"]

CATEGORY_ID = get_category_id(CATEGORY_SLUG)
print(f"✅ 카테고리 ID → {CATEGORY_ID}")

# ───────────────────── 3. 유틸
def norm(u: str) -> str:
    p = urlparse(u);  return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))

def load_seen() -> set[str]:
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, encoding="utf-8") as f: return set(json.load(f))
    return set()

def save_seen(s: set[str]):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(s), f, ensure_ascii=False, indent=2)

# ───────────────────── 4. 링크
def fetch_links() -> list[str]:
    soup = BeautifulSoup(requests.get(UDF_BASE, headers=UA_HEADER, timeout=10).text, "html.parser")
    return list({norm(urljoin(UDF_BASE, a["href"]))
                 for a in soup.select("div.article1 div.article_title_news a[href]")})

# ───────────────────── 5. 파싱
def parse_article(url: str):
    r = requests.get(url, headers=UA_HEADER, timeout=10)
    if r.status_code != 200: return None
    s = BeautifulSoup(r.text, "html.parser")
    t = s.find("h1", class_="newtitle");  b = s.find("div", id="zooming")
    if not (t and b): return None
    img = s.find("img", class_="lazy") or s.find("img")
    img_url = urljoin(url, img.get("data-src") or img.get("src")) if img else None
    return {"title": t.get_text(strip=True),
            "html": str(b),
            "image": img_url,
            "url": url}

# ───────────────────── 6. GPT 리라이팅
def rewrite(article: dict) -> str:
    prompt = f"""
다음은 벨라루스 관련 외신 기사입니다. 아래 양식에 맞춰 한국 독자를 위한 블로그 글을 작성해주세요.

🎯 조건
- 내용 요약·해석 금지, 문체·구조만 변경
- 제목(H1)/부제(H2)/문단(H3)을 사용
- 마지막 줄에 "이 기사는 벨라루스 현지 보도 내용을 재구성한 콘텐츠입니다." 추가
- 맨 끝에 "🏷️ 태그 키워드: ..." 형식으로 관련 키프레이즈 3~6개를 쉼표로 출력

📰 원문:
{article['html']}
"""
    res = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}",
                 "Content-Type": "application/json"},
        json={"model":"gpt-4o",
              "messages":[{"role":"user","content":prompt}],
              "temperature":0.3},
        timeout=90)
    res.raise_for_status()
    return res.json()["choices"][0]["message"]["content"]

# ───────────────────── 7. 태그
def extract_tag_names(text: str) -> list[str]:
    m = re.search(r"태그 키워드\s*[:：]\s*(.+)", text)
    if not m: return []
    return [t.strip() for t in re.split(r"[,\s]+", m.group(1)) if t.strip()]

def create_or_get_tag_id(name: str) -> int | None:
    q = requests.get(WP_TAGS_API, params={"search": name, "per_page": 1},
                     auth=HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD), timeout=10)
    if q.status_code==200 and q.json(): return q.json()[0]["id"]
    c = requests.post(WP_TAGS_API, json={"name": name},
                      auth=HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD), timeout=10)
    return c.json().get("id") if c.status_code==201 else None

# ───────────────────── 8. 중복 검사 (search + seen.json)
def is_duplicate(url_norm: str) -> bool:
    r = requests.get(WP_POSTS_API, params={"search": url_norm, "per_page": 1},
                     auth=HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD), timeout=10)
    return r.status_code==200 and bool(r.json())

# ───────────────────── 9. 발행
def publish(article, content, tag_ids):
    # 대표 이미지: 본문 첫줄 <img> + hidden source_url
    img_tag = f'<p><img src="{article["image"]}" alt=""></p>\n' if article["image"] else ""
    hidden  = f'<!--source_url:{article["url"]}-->\n'
    body    = hidden + img_tag + content

    title_line = next((l for l in content.splitlines() if l.startswith("# ")), article["title"])
    title = title_line.lstrip("# ").strip()

    data = {
        "title": title,
        "content": body,
        "status": "publish",
        "categories": [CATEGORY_ID],
        "tags": tag_ids
    }
    r = requests.post(WP_POSTS_API, json=data,
                      auth=HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD), timeout=30)
    print("  ↳ 게시 응답", r.status_code)
    r.raise_for_status()
    print("  ↳ 📝 ID", r.json()["id"])

# ───────────────────── 10. 메인
def main():
    logging.basicConfig(level=logging.WARNING)
    seen = load_seen()
    links = fetch_links()
    to_post = [u for u in links if norm(u) not in seen and not is_duplicate(norm(u))]
    print(f"총 {len(links)}개 중 새 기사 {len(to_post)}개\n")

    for url in to_post:
        print("=== 처리:", url)
        art = parse_article(url)
        if not art: continue
        try:
            content = rewrite(art)
        except Exception as e:
            print("  ↳ GPT 오류", e); continue

        tag_ids = [tid for n in extract_tag_names(content)
                   if (tid := create_or_get_tag_id(n))]
        try:
            publish(art, content, tag_ids)
            seen.add(norm(url)); save_seen(seen)
        except Exception as e:
            print("  ↳ 업로드 실패", e)
        time.sleep(2)

if __name__ == "__main__":
    main()
